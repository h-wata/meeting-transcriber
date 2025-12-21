"""Anthropic APIバックエンド."""

from __future__ import annotations

import os

import anthropic
from meeting_transcriber.backends.base import Backend


class AnthropicAPIBackend(Backend):
    """Anthropic APIを直接使用（従量課金）."""

    def __init__(self) -> None:
        self.client = anthropic.Anthropic()

    def generate(self, prompt: str) -> str:
        """プロンプトから議事録を生成する."""
        response = self.client.messages.create(
            model='claude-sonnet-4-20250514',
            max_tokens=8192,
            messages=[{
                'role': 'user',
                'content': prompt
            }],
        )
        return response.content[0].text

    @staticmethod
    def check_available() -> bool:
        """APIキーが設定されているか確認する."""
        return bool(os.environ.get('ANTHROPIC_API_KEY'))
