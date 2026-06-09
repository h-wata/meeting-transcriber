"""LLM から呼ばれるツール群（function calling 用）.

各ツールは:
- TOOL_DEFINITIONS に OpenAI function calling 形式の JSON Schema を持つ
- TOOL_DISPATCH 経由で関数名 → Python 関数にマップされる
- 引数は dict、戻り値は LLM に渡せる string
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


# OpenAI 互換 tool calling 形式
TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        'type': 'function',
        'function': {
            'name': 'web_search',
            'description': (
                'Web を検索して関連情報の上位結果（タイトル・URL・スニペット）を返す。'
                '最新情報・固有名詞の事実確認・専門用語の補足情報が必要なときに使う。'
                '会議の文脈だけで答えられる質問では呼ばない。'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'query': {
                        'type': 'string',
                        'description': '検索クエリ（日本語可、3〜10語程度）',
                    },
                    'max_results': {
                        'type': 'integer',
                        'description': '取得件数（1〜8、デフォルト5）',
                    },
                },
                'required': ['query'],
            },
        },
    },
]


def web_search(query: str, max_results: int = 5) -> str:
    """DuckDuckGo で検索して上位結果を整形して返す（APIキー不要）.

    依存: `ddgs` パッケージ。インストールされていなければインストール案内のエラー文字列を返す。
    """
    max_results = max(1, min(int(max_results or 5), 8))
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            # 旧パッケージ名でもフォールバック
            from duckduckgo_search import DDGS  # type: ignore[no-redef]
        except ImportError:
            return (
                '[web_search エラー] ddgs パッケージがインストールされていません。'
                '`uv add ddgs` でインストールしてください。'
            )

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results, region='jp-jp'))
    except Exception as e:  # noqa: BLE001
        logger.warning('web_search failed: %s', e)
        return f'[web_search エラー] {e}'

    if not results:
        return f'[web_search] "{query}" の検索結果は0件でした。'

    lines = [f'[web_search "{query}" 上位{len(results)}件]']
    for i, r in enumerate(results, 1):
        title = (r.get('title') or '').strip()
        url = (r.get('href') or r.get('url') or '').strip()
        body = (r.get('body') or '').strip().replace('\n', ' ')
        if len(body) > 300:
            body = body[:300] + '...'
        lines.append(f'{i}. {title}\n   URL: {url}\n   {body}')
    return '\n'.join(lines)


# tool_call.function.name → Python 関数 のマッピング
TOOL_DISPATCH = {
    'web_search': web_search,
}


def execute_tool_call(name: str, arguments_json: str) -> str:
    """LLM から来た tool_call を実行して結果文字列を返す.

    arguments_json: tool_call.function.arguments（JSON 文字列）
    """
    fn = TOOL_DISPATCH.get(name)
    if fn is None:
        return f'[tool エラー] 未知のツール: {name}'
    try:
        args = json.loads(arguments_json) if arguments_json else {}
    except json.JSONDecodeError as e:
        return f'[tool エラー] 引数 JSON のパース失敗: {e}'
    if not isinstance(args, dict):
        return '[tool エラー] 引数が dict ではありません'
    try:
        result = fn(**args)
    except TypeError as e:
        return f'[tool エラー] 引数不整合: {e}'
    except Exception as e:  # noqa: BLE001
        logger.exception('tool execution failed: %s', name)
        return f'[tool エラー] {type(e).__name__}: {e}'
    return str(result)
