"""バックエンドファクトリ."""

from __future__ import annotations

import os

from meeting_transcriber.backends.api import AnthropicAPIBackend
from meeting_transcriber.backends.base import Backend
from meeting_transcriber.backends.claude_agent import ClaudeAgentBackend
from meeting_transcriber.backends.claude_cli import ClaudeCLIBackend
from meeting_transcriber.backends.openai_compat import OpenAICompatBackend
from meeting_transcriber.config import Config


def get_backend(config: Config, session_id: str | None = None) -> Backend:
    """設定に基づいてバックエンドを選択.

    session_id を渡すと ClaudeCLIBackend がセッション継続モードで動作する。
    他のバックエンドは無視。
    """
    if config.backend in ('local', 'local_llm'):
        if not OpenAICompatBackend.check_available(config.local_llm.base_url):
            raise RuntimeError(f'ローカルLLMサーバーに接続できません: {config.local_llm.base_url}')
        print(f'ローカルLLM を使用します: {config.local_llm.base_url}')
        return OpenAICompatBackend(config.local_llm)

    if config.backend == 'api':
        if not os.environ.get('ANTHROPIC_API_KEY'):
            raise RuntimeError('ANTHROPIC_API_KEY が設定されていません')
        print('Anthropic API を使用します（従量課金）')
        return AnthropicAPIBackend()

    if config.backend == 'claude-agent':
        if not ClaudeAgentBackend.check_available():
            msg = 'CLAUDE_CODE_OAUTH_TOKEN が見つかりません\nclaude setup-token で OAuthトークンを取得してください'
            raise RuntimeError(msg)
        print('Claude Agent SDK を使用します（Maxプラン）')
        return ClaudeAgentBackend()

    if config.backend == 'claude-cli':
        if not ClaudeCLIBackend.check_available():
            raise RuntimeError('Claude Code CLI が見つかりません')
        print('Claude Code CLI を使用します（Maxプラン）')
        return ClaudeCLIBackend(session_id=session_id)

    # auto: 利用可能なバックエンドを自動選択（ローカルLLM最優先）
    if OpenAICompatBackend.check_available(config.local_llm.base_url):
        print(f'ローカルLLM を使用します: {config.local_llm.base_url}')
        return OpenAICompatBackend(config.local_llm)

    if ClaudeAgentBackend.check_available():
        print('Claude Agent SDK を使用します（Maxプラン）')
        return ClaudeAgentBackend()

    if ClaudeCLIBackend.check_available():
        print('Claude Code CLI を使用します（Maxプラン）')
        return ClaudeCLIBackend(session_id=session_id)

    if os.environ.get('ANTHROPIC_API_KEY'):
        print('Anthropic API を使用します（従量課金）')
        return AnthropicAPIBackend()

    raise RuntimeError(
        '利用可能なバックエンドがありません。以下のいずれかを設定:\n'
        '1. ローカルLLMサーバー (LM Studio等)\n'
        '2. CLAUDE_CODE_OAUTH_TOKEN (claude setup-token)\n'
        '3. Claude Code CLI インストール\n'
        '4. ANTHROPIC_API_KEY'
    )
