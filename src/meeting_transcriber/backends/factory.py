"""バックエンドファクトリ."""

from __future__ import annotations

import os

from meeting_transcriber.backends.api import AnthropicAPIBackend
from meeting_transcriber.backends.base import Backend
from meeting_transcriber.backends.claude_agent import ClaudeAgentBackend
from meeting_transcriber.backends.claude_cli import ClaudeCLIBackend
from meeting_transcriber.config import Config


def get_backend(config: Config) -> Backend:
    """設定に基づいてバックエンドを選択."""
    if config.backend == 'api':
        if not os.environ.get('ANTHROPIC_API_KEY'):
            raise RuntimeError('ANTHROPIC_API_KEY が設定されていません')
        print('Anthropic API を使用します（従量課金）')
        return AnthropicAPIBackend()

    if config.backend == 'claude-agent':
        if not ClaudeAgentBackend.check_available():
            raise RuntimeError(
                'CLAUDE_CODE_OAUTH_TOKEN が見つかりません\nclaude setup-token で OAuthトークンを取得してください'
            )
        print('Claude Agent SDK を使用します（Maxプラン）')
        return ClaudeAgentBackend()

    if config.backend == 'claude-cli':
        if not ClaudeCLIBackend.check_available():
            raise RuntimeError('Claude Code CLI が見つかりません')
        print('Claude Code CLI を使用します（Maxプラン）')
        return ClaudeCLIBackend()

    # auto: 利用可能なバックエンドを自動選択
    if ClaudeAgentBackend.check_available():
        print('Claude Agent SDK を使用します（Maxプラン）')
        return ClaudeAgentBackend()

    if ClaudeCLIBackend.check_available():
        print('Claude Code CLI を使用します（Maxプラン）')
        return ClaudeCLIBackend()

    if os.environ.get('ANTHROPIC_API_KEY'):
        print('Anthropic API を使用します（従量課金）')
        return AnthropicAPIBackend()

    raise RuntimeError(
        '利用可能なバックエンドがありません。以下のいずれかを設定:\n'
        '1. CLAUDE_CODE_OAUTH_TOKEN (claude setup-token)\n'
        '2. Claude Code CLI インストール\n'
        '3. ANTHROPIC_API_KEY'
    )
