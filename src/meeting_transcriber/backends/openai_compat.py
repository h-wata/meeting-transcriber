"""OpenAI互換APIバックエンド（ローカル & cloud 両対応）.

ローカル: Ollama / LM Studio / vLLM 等（api_key 不要）
cloud: Groq / OpenRouter / DeepSeek / Together AI 等（api_key 必須）
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx

from meeting_transcriber.backends.base import Backend

if TYPE_CHECKING:
    from meeting_transcriber.config import LocalLLMConfig

logger = logging.getLogger(__name__)


class OpenAICompatBackend(Backend):
    """OpenAI互換APIを使用（Ollama / LM Studio / vLLM / Groq / OpenRouter等）."""

    def __init__(self, config: LocalLLMConfig) -> None:
        self.config = config
        self._client: httpx.Client | None = None
        self._model: str | None = None

    def _build_headers(self) -> dict:
        """Build Authorization ヘッダ（cloud 用、ローカルなら空 dict）."""
        headers: dict[str, str] = {}
        api_key = self.config.resolve_api_key()
        if api_key:
            headers['Authorization'] = f'Bearer {api_key}'
        return headers

    @property
    def client(self) -> httpx.Client:
        """HTTPクライアントを取得."""
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.config.base_url,
                timeout=300.0,
                headers=self._build_headers(),
            )
        return self._client

    @property
    def model(self) -> str:
        """使用するモデル名を取得."""
        if self._model is None:
            if self.config.model:
                self._model = self.config.model
            else:
                self._model = self._detect_model()
        return self._model

    def _detect_model(self) -> str:
        """利用可能なモデルを自動検出."""
        try:
            response = self.client.get('/models')
            response.raise_for_status()
            data = response.json()
            models = data.get('data', [])
            if models:
                return models[0].get('id', 'default')
        except Exception:  # noqa: BLE001
            pass
        return 'default'

    def generate(self, prompt: str) -> str:
        """プロンプトから議事録を生成する."""
        messages = []
        if self.config.system_prompt:
            messages.append({'role': 'system', 'content': self.config.system_prompt})
        messages.append({'role': 'user', 'content': prompt})

        response = self.client.post(
            '/chat/completions',
            json={
                'model': self.model,
                'messages': messages,
                'max_tokens': self.config.max_tokens,
                'temperature': self.config.temperature,
            },
        )
        response.raise_for_status()
        data = response.json()
        return data['choices'][0]['message']['content']

    def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        max_iterations: int = 4,
        on_tool_call: 'callable | None' = None,
        on_iteration: 'callable | None' = None,
    ) -> str:
        """Tool calling ループ対応のチャット.

        messages: OpenAI 形式のメッセージリスト（system / user / assistant）
        tools: function calling 用の tool 定義
        max_iterations: tool_call → tool result → 再生成 のループ上限
        on_tool_call: tool 呼び出しごとに (name, args_json, result) を通知するコールバック

        モデルが tool_calls を返さなくなった時点で content を返す。
        ループ上限に達した場合は最後のレスポンスの content を返す。
        """
        from meeting_transcriber.tools import execute_tool_call

        # 渡された messages を破壊しないようコピー
        msgs = [dict(m) for m in messages]
        if self.config.system_prompt and (not msgs or msgs[0].get('role') != 'system'):
            msgs.insert(0, {'role': 'system', 'content': self.config.system_prompt})

        for iteration in range(max_iterations):
            payload = {
                'model': self.model,
                'messages': msgs,
                'max_tokens': self.config.max_tokens,
                'temperature': self.config.temperature,
                'tools': tools,
                'tool_choice': 'auto',
            }
            response = self.client.post('/chat/completions', json=payload)
            if response.status_code >= 400:
                # 400 等の中身を見て debug しやすくする
                try:
                    err_body = response.json()
                except Exception:  # noqa: BLE001
                    err_body = response.text
                logger.error(
                    'vLLM %s: %s | request roles=%s',
                    response.status_code,
                    err_body,
                    [m.get('role') for m in msgs],
                )
                raise httpx.HTTPStatusError(
                    f'{response.status_code} from {response.url}: {err_body}',
                    request=response.request,
                    response=response,
                )
            data = response.json()
            msg = data['choices'][0]['message']
            tool_calls = msg.get('tool_calls')
            content = msg.get('content') or ''
            reasoning = msg.get('reasoning_content') or msg.get('reasoning') or ''
            n_tool_calls = len(tool_calls) if tool_calls else 0
            finish_reason = data['choices'][0].get('finish_reason')
            logger.info(
                'chat_with_tools iter=%d tool_calls=%s content_len=%d reasoning_len=%d finish_reason=%s',
                iteration,
                n_tool_calls,
                len(content),
                len(reasoning),
                finish_reason,
            )
            if on_iteration is not None:
                try:
                    on_iteration(
                        iteration=iteration,
                        n_tool_calls=n_tool_calls,
                        content_len=len(content),
                        reasoning_len=len(reasoning),
                        finish_reason=finish_reason,
                    )
                except Exception:  # noqa: BLE001
                    pass

            if not tool_calls:
                # reasoning_content はモデルの内部思考なのでユーザーには見せない（content のみ返す）
                return content

            # assistant ターン（tool_calls 付き）を履歴に積む
            msgs.append(
                {
                    'role': 'assistant',
                    'content': msg.get('content') or '',
                    'tool_calls': tool_calls,
                }
            )
            # 各 tool_call を実行して role:"tool" メッセージとして追加
            for tc in tool_calls:
                fn_obj = tc.get('function') or {}
                name = fn_obj.get('name', '')
                args_json = fn_obj.get('arguments', '') or '{}'
                tool_result = execute_tool_call(name, args_json)
                if on_tool_call is not None:
                    try:
                        on_tool_call(name, args_json, tool_result)
                    except Exception:  # noqa: BLE001
                        pass
                msgs.append(
                    {
                        'role': 'tool',
                        'tool_call_id': tc.get('id'),
                        'content': tool_result,
                    }
                )

        # ループ上限に達した場合: 最後の assistant content を返す
        return msg.get('content') or '(tool loop が上限に達しました)'

    @staticmethod
    def check_available(
        base_url: str = 'http://localhost:1234/v1',
        api_key: str | None = None,
    ) -> bool:
        """OpenAI互換APIサーバーが応答するか確認.

        ローカル: api_key=None なら GET /models で疎通確認。
        cloud: api_key 指定時は Authorization ヘッダ付きで /models を叩く。
        """
        try:
            headers = {'Authorization': f'Bearer {api_key}'} if api_key else {}
            response = httpx.get(f'{base_url}/models', timeout=5.0, headers=headers)
            return response.status_code == 200
        except Exception:  # noqa: BLE001
            return False

    def __del__(self) -> None:
        """クリーンアップ."""
        if self._client is not None:
            self._client.close()
