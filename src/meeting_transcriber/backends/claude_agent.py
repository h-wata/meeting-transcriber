"""Claude Agent SDKバックエンド."""

from __future__ import annotations

import os

import anyio
from meeting_transcriber.backends.base import Backend


class ClaudeAgentBackend(Backend):
    """Claude Agent SDK + OAuthトークン（Maxプラン活用）."""

    def __init__(self) -> None:
        from claude_code_sdk import ClaudeCodeOptions

        self.options = ClaudeCodeOptions(max_tokens=8192)

    async def generate_async(self, prompt: str) -> str:
        """非同期でテキストを生成する."""
        from claude_code_sdk import query

        result_parts = []
        async for message in query(prompt=prompt, options=self.options):
            if hasattr(message, 'content'):
                for block in message.content:
                    if hasattr(block, 'text'):
                        result_parts.append(block.text)
        return ''.join(result_parts)

    def generate(self, prompt: str) -> str:
        """プロンプトから議事録を生成する."""
        return anyio.from_thread.run_sync(lambda: anyio.run(self.generate_async, prompt))

    @staticmethod
    def check_available() -> bool:
        """Claude Agent SDKとOAuthトークンが利用可能か確認する."""
        try:
            from claude_code_sdk import query  # noqa: F401

            return bool(os.environ.get('CLAUDE_CODE_OAUTH_TOKEN'))
        except ImportError:
            return False
