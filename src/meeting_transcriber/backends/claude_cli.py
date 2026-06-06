"""Claude Code CLIバックエンド."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import uuid

from meeting_transcriber.backends.base import Backend

# Claude CLI のエラーメッセージからセッション無効を判定するキーワード
_SESSION_ERROR_KEYWORDS = ('session', 'context', 'token', 'too long', 'limit')

logger = logging.getLogger(__name__)


class ClaudeCLIBackend(Backend):
    """Claude Code CLIをsubprocessで呼び出し（Maxプラン活用）.

    session_id を渡すと --session-id でセッションを継続し、Claude側に会議の文脈を蓄積できる。
    プロンプトキャッシュも効くため、長時間の議事録更新ではコスト・速度・品質すべてで有利。

    2026/6/15以降、claude -p は Max プラン本体枠とは別の
    Agent SDK クレジット枠（Max 5x: $100/月、Max 20x: $200/月）を消費するため、
    --output-format json から total_cost_usd を取得して累計を可視化する。
    """

    def __init__(self, session_id: str | None = None) -> None:
        self.session_id = session_id
        self._session_dead = False
        self._last_cost_usd = 0.0
        self._cumulative_cost_usd = 0.0
        self._call_count = 0

    @property
    def has_persistent_context(self) -> bool:
        """session_idが有効ならTrue."""
        return self.session_id is not None and not self._session_dead

    def reset_context(self) -> None:
        """セッションIDを新規生成して文脈をリセットする."""
        if self.session_id is not None:
            self.session_id = str(uuid.uuid4())
            self._session_dead = False

    @property
    def last_cost_usd(self) -> float:
        return self._last_cost_usd

    @property
    def cumulative_cost_usd(self) -> float:
        return self._cumulative_cost_usd

    @property
    def call_count(self) -> int:
        return self._call_count

    def generate(self, prompt: str) -> str:
        """プロンプトから議事録を生成する."""
        # ANTHROPIC_API_KEY があるとAPI課金になるので一時的に除去
        # （Max プラン枠で動かすため OAuth/keychain にフォールバックさせる）
        env = os.environ.copy()
        env.pop('ANTHROPIC_API_KEY', None)

        cmd = ['claude', '-p', prompt, '--output-format', 'json', '--model', 'sonnet']
        if self.has_persistent_context:
            cmd += ['--session-id', self.session_id]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
            check=False,
        )

        if result.returncode != 0:
            stderr_lower = result.stderr.lower()
            # セッション関連のエラーならセッションを破損扱いにして次回は新規UUIDで再生成
            if self.session_id is not None and any(k in stderr_lower for k in _SESSION_ERROR_KEYWORDS):
                self._session_dead = True
            raise RuntimeError(f'Claude CLI error: {result.stderr}')

        return self._parse_json_response(result.stdout)

    def _parse_json_response(self, stdout: str) -> str:
        """Parse `claude -p --output-format json` の出力からテキスト本体を返す.

        副作用: total_cost_usd を _last_cost_usd / _cumulative_cost_usd に反映する。
        """
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as e:
            # JSONとして読めないケース: 後方互換として生テキストを返す
            logger.warning('Claude CLI JSON decode failed, falling back to raw text: %s', e)
            return stdout.strip()

        # エラーレスポンス
        if payload.get('is_error'):
            err_msg = payload.get('result') or payload.get('error') or 'unknown error'
            err_str = str(err_msg).lower()
            if self.session_id is not None and any(k in err_str for k in _SESSION_ERROR_KEYWORDS):
                self._session_dead = True
            raise RuntimeError(f'Claude CLI error: {err_msg}')

        cost = payload.get('total_cost_usd')
        if isinstance(cost, (int, float)):
            self._last_cost_usd = float(cost)
            self._cumulative_cost_usd += float(cost)
            self._call_count += 1
            logger.info(
                'Claude CLI cost: this call $%.4f / cumulative $%.4f (%d calls)',
                self._last_cost_usd,
                self._cumulative_cost_usd,
                self._call_count,
            )

        text = payload.get('result', '')
        if not isinstance(text, str):
            text = str(text)
        return text.strip()

    @staticmethod
    def check_available() -> bool:
        """Claude CLIが利用可能か確認する."""
        try:
            result = subprocess.run(
                ['claude', '--version'],
                capture_output=True,
                timeout=5,
                check=False,
            )
            return result.returncode == 0
        except FileNotFoundError:
            return False
