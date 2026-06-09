"""バックエンドファクトリ."""

from __future__ import annotations

import os
import warnings

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

    backend 識別子:
    - openai_compat (推奨): OpenAI互換API (ローカル & cloud)
    - local / local_llm (deprecated): openai_compat のエイリアス
    - claude-cli / claude-agent / api / auto: 既存の Claude 系
    """
    backend_name = config.backend

    # 旧名 'local' / 'local_llm' は deprecation 警告を出して openai_compat 扱いにする
    if backend_name in ('local', 'local_llm'):
        warnings.warn(
            f"backend='{backend_name}' は将来削除されます。'openai_compat' を使ってください。",
            DeprecationWarning,
            stacklevel=2,
        )
        backend_name = 'openai_compat'

    if backend_name == 'openai_compat':
        api_key = config.local_llm.resolve_api_key()
        if config.local_llm.is_cloud():
            # cloud: api_key 必須
            if not api_key:
                raise RuntimeError(
                    f'OpenAI互換 cloud バックエンドの API key が取得できません。'
                    f'環境変数 {config.local_llm.api_key_env} を設定してください。'
                )
            print(f'OpenAI互換 cloud を使用します: {config.local_llm.base_url}')
        else:
            # ローカル: 疎通確認
            if not OpenAICompatBackend.check_available(config.local_llm.base_url):
                raise RuntimeError(f'OpenAI互換サーバーに接続できません: {config.local_llm.base_url}')
            print(f'OpenAI互換 ローカルを使用します: {config.local_llm.base_url}')
        return OpenAICompatBackend(config.local_llm)

    if backend_name == 'api':
        if not os.environ.get('ANTHROPIC_API_KEY'):
            raise RuntimeError('ANTHROPIC_API_KEY が設定されていません')
        print('Anthropic API を使用します（従量課金）')
        return AnthropicAPIBackend()

    if backend_name == 'claude-agent':
        if not ClaudeAgentBackend.check_available():
            msg = 'CLAUDE_CODE_OAUTH_TOKEN が見つかりません\nclaude setup-token で OAuthトークンを取得してください'
            raise RuntimeError(msg)
        print('Claude Agent SDK を使用します（Maxプラン）')
        return ClaudeAgentBackend()

    if backend_name == 'claude-cli':
        if not ClaudeCLIBackend.check_available():
            raise RuntimeError('Claude Code CLI が見つかりません')
        print('Claude Code CLI を使用します（Maxプラン）')
        return ClaudeCLIBackend(session_id=session_id, model=config.claude_cli_model)

    # auto: 利用可能なバックエンドを自動選択
    # cloud OpenAI 互換は明示指定でのみ選ばれる（勝手に課金経路に倒さない）
    if not config.local_llm.is_cloud():
        if OpenAICompatBackend.check_available(config.local_llm.base_url):
            print(f'OpenAI互換 ローカルを使用します: {config.local_llm.base_url}')
            return OpenAICompatBackend(config.local_llm)

    if ClaudeAgentBackend.check_available():
        print('Claude Agent SDK を使用します（Maxプラン）')
        return ClaudeAgentBackend()

    if ClaudeCLIBackend.check_available():
        print('Claude Code CLI を使用します（Maxプラン）')
        return ClaudeCLIBackend(session_id=session_id, model=config.claude_cli_model)

    if os.environ.get('ANTHROPIC_API_KEY'):
        print('Anthropic API を使用します（従量課金）')
        return AnthropicAPIBackend()

    raise RuntimeError(
        '利用可能なバックエンドがありません。以下のいずれかを設定:\n'
        '1. ローカルLLMサーバー (LM Studio等) または cloud OpenAI 互換 (Groq等、-b openai_compat)\n'
        '2. CLAUDE_CODE_OAUTH_TOKEN (claude setup-token)\n'
        '3. Claude Code CLI インストール\n'
        '4. ANTHROPIC_API_KEY'
    )
