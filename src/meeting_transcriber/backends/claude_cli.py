"""Claude Code CLIバックエンド."""

from __future__ import annotations

import os
import subprocess
import uuid

from meeting_transcriber.backends.base import Backend

# Claude CLI のエラーメッセージからセッション無効を判定するキーワード
_SESSION_ERROR_KEYWORDS = ('session', 'context', 'token', 'too long', 'limit')


class ClaudeCLIBackend(Backend):
    """Claude Code CLIをsubprocessで呼び出し（Maxプラン活用）.

    session_id を渡すと --session-id でセッションを継続し、Claude側に会議の文脈を蓄積できる。
    プロンプトキャッシュも効くため、長時間の議事録更新ではコスト・速度・品質すべてで有利。
    """

    def __init__(self, session_id: str | None = None) -> None:
        self.session_id = session_id
        self._session_dead = False

    @property
    def has_persistent_context(self) -> bool:
        """session_idが有効ならTrue."""
        return self.session_id is not None and not self._session_dead

    def reset_context(self) -> None:
        """セッションIDを新規生成して文脈をリセットする."""
        if self.session_id is not None:
            self.session_id = str(uuid.uuid4())
            self._session_dead = False

    def generate(self, prompt: str) -> str:
        """プロンプトから議事録を生成する."""
        # ANTHROPIC_API_KEY があるとAPI課金になるので一時的に除去
        # （Max プラン枠で動かすため OAuth/keychain にフォールバックさせる）
        env = os.environ.copy()
        env.pop('ANTHROPIC_API_KEY', None)

        cmd = ['claude', '-p', prompt, '--output-format', 'text']
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

        return result.stdout.strip()

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
