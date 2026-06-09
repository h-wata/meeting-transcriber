# ADR-0002: AI チャットの Web 検索を Local LLM の tool calling で実現する

- ステータス: Accepted
- 日付: 2026-06-09
- 関連: なし（議事録は別系統。チャットのみ）

## コンテキスト

Web UI 右下の「AI に聞く」チャットは、これまで会議の文字起こしを背景に Claude CLI (Max プラン) または Local LLM (vLLM + Qwen3-30B-A3B-FP8 等) に丸投げするだけの単発プロンプト方式だった。

実際に運用してみると以下の問題があった：

1. **会話の文脈が連続しない**: OpenAI 互換 backend は session_id を持たないため、2 ターン目以降の質問が前の回答を踏まえられない。Claude CLI 経路では `--session-id` で session 継続できていたが、Local LLM 経路では毎回スタンドアロンになっていた。
2. **議事録用 system_prompt がチャットでも使われていた**: `local_llm.system_prompt: "あなたは日本語の議事録作成の専門家です..."` がチャット経路にも適用され、Qwen が「議事録を作るべきか、ユーザーの質問に答えるべきか」で迷ってしまい、reasoning だけ多く content が空になる事象が発生した。
3. **会議外の情報源にアクセスできない**: 「最新の Whisper 系モデルの情報」「ボーナス相場」など、会議の文脈外の質問に対しては Qwen の事前学習知識でしか答えられず、最新性・正確性が不足する。

## 決定

### 1. チャット経路を `chat_with_tools()` に分離

`OpenAICompatBackend` に **`chat_with_tools(messages, tools, ...)` メソッドを追加**し、OpenAI 互換 function calling のループ (tool_call → tool 実行 → 結果フィードバック → 再生成) を実装する。`generate(prompt)` は議事録生成用で従来通り単発。

### 2. Local LLM (vLLM + Qwen3) を tool calling 経路の前提とする

ユーザー環境の vLLM は以下のオプションで起動されている：

```bash
vllm serve Qwen/Qwen3.6-35B-A3B-FP8 \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_coder \
  --reasoning-parser qwen3 \
  ...
```

`--tool-call-parser qwen3_coder` により Qwen3 のネイティブ `<tool_call>` タグ形式が OpenAI 互換 `tool_calls` JSON に変換される。クライアント側は普通の OpenAI tool calling を叩くだけで Qwen がツールを選択してくれる。

### 3. 検索ツールは DuckDuckGo (`ddgs` パッケージ) を採用

API キー不要・依存追加 1 つ・レート制限が緩い、を理由に DuckDuckGo HTML 検索を `web_search(query, max_results)` として実装する (`src/meeting_transcriber/tools.py`)。

検索プロバイダ比較：

| プロバイダ | キー | 品質 | レート制限 | 採用 |
|----|----|----|----|----|
| DuckDuckGo (`ddgs`) | 不要 | 中 | 緩い | ◎ |
| SearXNG セルフホスト | 不要 (要構築) | 中〜高 | 自分次第 | △ |
| Brave Search API | 必要 (無料枠あり) | 高 | 2k/月無料 | × (将来検討) |
| Tavily | 必要 | 高 (AI 向け整形) | 1k/月無料 | × (将来検討) |

### 4. 検索すべきかの判断はモデルに委ねる

「いつ検索するか」のヒューリスティクスをアプリ側に持たず、tool calling の `tool_choice: "auto"` で **Qwen が必要と判断したときだけ呼ばれる**形にする。会議の文脈や一般常識で答えられる質問では検索しない (実測でその通り動いた)。

### 5. 会話履歴は multi-turn messages で復元

`_invoke_chat_with_history()` で `_chat_history` (UI 用) から user/assistant メッセージを復元して OpenAI 形式 messages 配列を組み立てる。session_id を持たない backend でも会話の連続性を保てる。

### 6. チャット専用 system_prompt をハードコード

議事録用 system_prompt とは分離し、`WebUIServer._CHAT_SYSTEM_PROMPT` に「会議に同席する AI アシスタント。web_search を必要なときに使う」旨を明記する。

### 7. 複数 system messages は 1 つに統合

vLLM/Qwen 系で複数の system message が 400 Bad Request を返す事例があったため、文字起こし context も同一 system 内に連結する。

### 8. reasoning_content は返さない

Qwen3 + `--reasoning-parser qwen3` では `message.reasoning_content` にモデルの思考過程が入る。これはユーザーに見せず、`content` のみを返す。content が空の場合は再試行を促すメッセージを表示。

## 影響

- **チャットが文脈持続する**: 「2025 年の平均は？」が前のターンの「ボーナス」を引き継ぐ
- **検索が必要なときだけ走る**: 余計なトークン消費なし、検索失敗時は事前学習知識でフォールバック
- **依存追加**: `ddgs>=6.0.0` を必須依存に追加 (要 `uv sync`)
- **vLLM 起動オプションの前提**: `--enable-auto-tool-choice --tool-call-parser qwen3_coder` (Qwen3 系) が必須。違うモデルでは parser を差し替える必要あり
- **議事録生成パスは無影響**: `generate(prompt)` は従来通り。tool calling は使わない

## 代替案

### 代替案 A: アプリ側で「常に DuckDuckGo 検索 → 結果をプロンプトにプリインジェクト」

- メリット: tool calling 非対応モデルでも動く。実装が単純 (50 行)
- デメリット: 検索不要な質問でも常に検索が走りトークン浪費。会話履歴管理は別途必要
- → 採用しない (モデルが判断する方が自然)

### 代替案 B: Claude CLI の WebSearch ツールを使う

- メリット: 既に session 管理ができており、`--allowed-tools WebSearch,WebFetch` で web 検索を解禁可能
- デメリット: ユーザーは現状チャット backend を `local_llm` に固定して運用したい。Claude CLI に分岐するとマシン跨ぎ・料金経路が変わる
- → 採用しない (chat backend を分岐させると運用が複雑)

### 代替案 C: SearXNG セルフホスト

- メリット: プライバシー、検索ソースの選択肢、レート制限なし
- デメリット: 別コンテナ運用、SearXNG 自体のメンテ
- → 将来 DuckDuckGo の品質に不満が出たら検討

## 参考

- [vLLM Tool Calling 公式ドキュメント](https://docs.vllm.ai/en/latest/serving/openai_compatible_server.html#tool-calling)
- [OpenAI Function Calling 仕様](https://platform.openai.com/docs/guides/function-calling)
- [Qwen3 公式リリースノート](https://qwenlm.github.io/blog/qwen3/)
- [ddgs (DuckDuckGo Search) PyPI](https://pypi.org/project/ddgs/)
