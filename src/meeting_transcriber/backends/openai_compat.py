"""OpenAI互換APIバックエンド（Ollama, LM Studio, vLLM等）."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
from meeting_transcriber.backends.base import Backend

if TYPE_CHECKING:
    from meeting_transcriber.config import LocalLLMConfig


class OpenAICompatBackend(Backend):
    """OpenAI互換APIを使用（Ollama, LM Studio, vLLM等）."""

    def __init__(self, config: LocalLLMConfig) -> None:
        self.config = config
        self._client: httpx.Client | None = None
        self._model: str | None = None

    @property
    def client(self) -> httpx.Client:
        """HTTPクライアントを取得."""
        if self._client is None:
            self._client = httpx.Client(base_url=self.config.base_url, timeout=300.0)
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
        except Exception:
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

    @staticmethod
    def check_available(base_url: str = 'http://localhost:1234/v1') -> bool:
        """ローカルLLMサーバーが起動しているか確認."""
        try:
            response = httpx.get(f'{base_url}/models', timeout=5.0)
            return response.status_code == 200
        except Exception:
            return False

    def __del__(self) -> None:
        """クリーンアップ."""
        if self._client is not None:
            self._client.close()
