# リアルタイム議事録生成ツール 仕様書

## 1. プロジェクト概要

### 1.1 目的

マイクからの音声入力をリアルタイムで文字起こしし、会議終了後にClaude APIを使用して構造化された議事録を自動生成するPythonツール。

### 1.2 現状の課題

- whisper.cppの`whisper-stream`で一時ファイルに書き込み
- 手動でClaude Codeに読み込ませて議事録生成
- 複数ステップが必要で非効率

### 1.3 解決策

音声入力 → 文字起こし → 議事録生成を一気通貫で行う Python ツール。
ブラウザ UI で議事録プレビューと AI チャットを統合し、会議中に Claude と議論しながら進められる。

---

## 2. システムアーキテクチャ

```
┌─────────────────────────────────────────────────────────────────┐
│                        メインプロセス                            │
│                                                                 │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────┐ │
│  │ AudioInput  │───▶│ Transcriber │───▶│ MinutesGenerator    │ │
│  │ (録音)      │    │ (Whisper)   │    │ (Backend)           │ │
│  └─────────────┘    └─────────────┘    └─────────────────────┘ │
│         │                  │                      │             │
│         ▼                  ▼                      ▼             │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │   UI 層: Web UI (FastAPI + WS) / TUI (Textual) / CLI    │   │
│  │     ├─ 文字起こし / ログ / 議事録プレビュー              │   │
│  │     └─ AIチャット（Web UIのみ、別 session_id）           │   │
│  └─────────────────────────────────────────────────────────┘   │
│                            │                                    │
│                            ▼                                    │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │   Backend 層（差替可、session_id 対応）                 │   │
│  │   claude-cli / claude-agent / api / openai_compat       │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. 機能要件

### 3.1 音声入力機能

- \[ ] デフォルトマイクからの音声キャプチャ
- \[ ] サンプルレート: 16000Hz（Whisper推奨）
- \[ ] モノラル入力
- \[ ] 録音開始/停止のキーボード制御（Ctrl+C or 'q'キー）

### 3.2 文字起こし機能

- \[ ] faster-whisperによるローカル音声認識
- \[ ] 日本語対応（`language="ja"`）
- \[ ] VADフィルタによる無音区間スキップ
- \[ ] チャンク単位（5秒程度）でのリアルタイム処理
- \[ ] タイムスタンプ付きテキスト出力
- \[ ] 文字起こし結果のリアルタイム表示（標準出力）

### 3.3 議事録生成機能

- \[x] 構造化された Markdown 形式の出力
- \[x] ファイル自動保存
- \[x] **5つのバックエンドから選択可能:**

#### 3.3.1 バックエンド選択

| バックエンド          | 課金                                  | 特徴                                        |
| --------------------- | ------------------------------------- | ------------------------------------------- |
| **claude-cli**        | Max プラン枠（Agent SDK クレジット）  | `claude -p` subprocess、`--session-id` 対応 |
| **claude-agent**      | Max プラン枠                          | SDK 経由、OAuth トークン必要                |
| **api**               | 従量課金                              | Anthropic API 直接                          |
| **openai_compat**     | ローカル無料 / cloud は API key 経由  | LM Studio / Ollama / Groq / OpenRouter 等   |
| `local`（旧名）       | —                                     | `openai_compat` の deprecated エイリアス    |

```bash
meeting-transcriber --backend claude-cli      # Claude Code CLI（推奨）
meeting-transcriber --backend openai_compat   # ローカル LLM や Groq 等
meeting-transcriber --backend auto            # 自動選択（デフォルト）
```

**auto（デフォルト）の優先順位:**

1. `openai_compat` でローカル LLM が応答 → `openai_compat` (ローカルのみ。cloud は明示指定が必要)
2. `CLAUDE_CODE_OAUTH_TOKEN` あり → `claude-agent`
3. `claude` CLI が利用可能 → `claude-cli`
4. `ANTHROPIC_API_KEY` あり → `api`
5. どれもなし → エラー

cloud OpenAI 互換（Groq 等）は **明示指定 (`-b openai_compat` + `api_key_env`) のみ** で選ばれる。
auto が勝手に課金経路へ倒さないための安全設計。詳細は ADR-0001 参照。

#### 3.3.2 Anthropic API方式（従量課金）

- 環境変数 `ANTHROPIC_API_KEY` が必要
- 安定したレスポンス、並列処理可能
- **コスト目安**: 1時間会議で5回更新 → 約 $0.03〜0.05

```python
import anthropic

class AnthropicAPIBackend:
    """Anthropic APIを直接使用（従量課金）"""

    def __init__(self):
        self.client = anthropic.Anthropic()

    def generate(self, prompt: str) -> str:
        response = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text
```

#### 3.3.3 Claude Agent SDK方式（Maxプラン + OAuthトークン）

- `pip install claude-agent-sdk` でインストール
- 環境変数 `CLAUDE_CODE_OAUTH_TOKEN` が必要
- Maxプラン（$100/200）の範囲内で利用可能

**OAuthトークンの取得方法:**

```bash
# Claude Code CLIでトークンを生成
claude setup-token

# 生成されたトークンを環境変数に設定
export CLAUDE_CODE_OAUTH_TOKEN=your-oauth-token-here
```

**実装:**

```python
import os
import anyio
from claude_agent_sdk import query, ClaudeAgentOptions

class ClaudeAgentBackend:
    """Claude Agent SDK + OAuthトークン（Maxプラン活用）"""

    def __init__(self):
        self.options = ClaudeAgentOptions(max_tokens=8192)

    async def generate_async(self, prompt: str) -> str:
        result_parts = []
        async for message in query(prompt=prompt, options=self.options):
            if hasattr(message, 'content'):
                for block in message.content:
                    if hasattr(block, 'text'):
                        result_parts.append(block.text)
        return ''.join(result_parts)

    def generate(self, prompt: str) -> str:
        return anyio.run(self.generate_async, prompt)

    @staticmethod
    def check_available() -> bool:
        try:
            from claude_agent_sdk import query
            return bool(os.environ.get('CLAUDE_CODE_OAUTH_TOKEN'))
        except ImportError:
            return False
```

**注意点:**

- OAuthトークンには有効期限あり（期限切れ時は `claude setup-token` で再生成）
- GitHub Actionsでは公式サポート済み

#### 3.3.4 Claude Code CLI方式（Maxプラン + subprocess）

- `claude` コマンドを subprocess で呼び出し
- Maxプランにログイン済みなら追加設定不要
- **最も安定した方式**

```python
import subprocess
import os

class ClaudeCLIBackend:
    """Claude Code CLIをsubprocessで呼び出し（Maxプラン活用）"""

    def generate(self, prompt: str) -> str:
        # ANTHROPIC_API_KEY があると API課金になるので一時的に除去
        env = os.environ.copy()
        env.pop('ANTHROPIC_API_KEY', None)

        result = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "text"],
            capture_output=True,
            text=True,
            timeout=120,
            env=env
        )

        if result.returncode != 0:
            raise RuntimeError(f"Claude CLI error: {result.stderr}")

        return result.stdout.strip()

    @staticmethod
    def check_available() -> bool:
        try:
            result = subprocess.run(
                ["claude", "--version"],
                capture_output=True,
                timeout=5
            )
            return result.returncode == 0
        except FileNotFoundError:
            return False
```

#### 3.3.5 OpenAI 互換バックエンド（ローカル & cloud）

`OpenAICompatBackend` は OpenAI 互換 API ならローカル・cloud どちらにも繋がる。
内部実装は同じで、`api_key_env` の有無で挙動が分岐:

| 種別     | base_url 例                          | api_key | コスト                     |
| -------- | ------------------------------------ | ------- | -------------------------- |
| ローカル | `http://localhost:1234/v1`           | 不要    | 無料（GPU 必須）           |
| Groq     | `https://api.groq.com/openai/v1`     | 必須    | 無料枠あり、500+ tok/s     |
| OpenRouter | `https://openrouter.ai/api/v1`     | 必須    | モデルごとに従量課金       |
| DeepSeek | `https://api.deepseek.com/v1`        | 必須    | 安価                       |

cloud 接続時は環境変数 (`api_key_env`) 経由で API key を渡す。`Authorization: Bearer <key>` を自動でセット。

#### 3.3.6 バックエンド共通 API

```python
class Backend(ABC):
    def generate(self, prompt: str) -> str: ...
    @staticmethod
    def check_available() -> bool: ...

    @property
    def has_persistent_context(self) -> bool: ...   # session 継続できるか
    def reset_context(self) -> None: ...            # session 破損時の復旧

    @property
    def last_cost_usd(self) -> float: ...            # 直近呼び出しコスト
    @property
    def cumulative_cost_usd(self) -> float: ...      # 累計コスト
```

`ClaudeCLIBackend` のみ `session_id` / コスト追跡を完全実装。他は基底クラスのデフォルト（False / 0.0）。

#### 3.3.7 バックエンド自動選択

```python
def get_backend(config: Config, session_id: str | None = None) -> Backend:
    """設定に基づいてバックエンドを選択。session_id は ClaudeCLI に渡される。"""

    if config.backend in ('local', 'local_llm'):
        warnings.warn(..., DeprecationWarning)
        config.backend = 'openai_compat'

    if config.backend == 'openai_compat':
        if config.local_llm.is_cloud():
            # cloud: api_key 必須
            if not config.local_llm.resolve_api_key():
                raise RuntimeError(f'API key 未設定: {config.local_llm.api_key_env}')
        else:
            # ローカル: 疎通確認
            if not OpenAICompatBackend.check_available(config.local_llm.base_url):
                raise RuntimeError('OpenAI 互換サーバーに接続できません')
        return OpenAICompatBackend(config.local_llm)

    if config.backend == 'claude-cli':
        return ClaudeCLIBackend(session_id=session_id)
    # ... claude-agent / api 省略 ...

    # auto: cloud は明示指定でのみ → ローカル → claude-agent → claude-cli → api
    if not config.local_llm.is_cloud():
        if OpenAICompatBackend.check_available(config.local_llm.base_url):
            return OpenAICompatBackend(config.local_llm)
    if ClaudeAgentBackend.check_available():
        return ClaudeAgentBackend()
    if ClaudeCLIBackend.check_available():
        return ClaudeCLIBackend(session_id=session_id)
    if os.environ.get('ANTHROPIC_API_KEY'):
        return AnthropicAPIBackend()
    raise RuntimeError('利用可能なバックエンドなし')
```

### 3.4 議事録更新機能（メイン機能）

#### 3.4.1 基本コンセプト

- **手動トリガー方式**: ユーザーが任意のタイミングでキーを押して議事録を更新
- 前回の更新時点から現在までの差分を理解して議事録に反映
- 自動更新はオプション（デフォルトはオフ）

#### 3.4.2 操作方法

- \[ ] `u` キー または `Enter` キーで議事録更新をトリガー
- \[ ] `s` キーで現在の状態を保存（議事録更新なし）
- \[ ] `q` キー または `Ctrl+C` で終了（最終議事録を生成）
- \[ ] `?` キーでヘルプ表示

#### 3.4.3 差分更新ロジック

```
初回更新時:
┌─────────────────────────────────────────────────────┐
│ [00:00] 発言1                                       │
│ [00:05] 発言2                                       │
│ [00:12] 発言3  ←── 全体から議事録v1を生成           │
└─────────────────────────────────────────────────────┘
                         ↓
                    議事録 v1

2回目以降の更新時:
┌─────────────────────────────────────────────────────┐
│ [00:00] 発言1  ┐                                    │
│ [00:05] 発言2  ├── 前回処理済み（議事録v1に反映済み）│
│ [00:12] 発言3  ┘                                    │
│ ─────────────── 前回更新ポイント ─────────────────  │
│ [00:18] 発言4  ┐                                    │
│ [00:25] 発言5  ├── 今回の差分（新規発言）           │
│ [00:30] 発言6  ┘                                    │
└─────────────────────────────────────────────────────┘
                         ↓
    議事録v1 + 差分発言 → Claude API → 議事録 v2
```

#### 3.4.4 差分更新時のプロンプト

```
あなたは議事録作成アシスタントです。
既存の議事録に新しい発言内容を統合して、議事録を更新してください。

【ルール】
- 新しい情報を適切なセクションに追加・統合する
- 既存の内容と重複する場合は統合してまとめる
- 議論の流れが分かるように時系列を意識する
- 決定事項やTODOが出たら該当セクションに追加
- 全体の構成・フォーマットは維持する

【現在の議事録】
{current_minutes}

【前回更新からの新しい発言】
{new_transcripts}

【出力】
更新後の議事録全体をMarkdown形式で出力してください。
```

#### 3.4.5 機能要件

- \[ ] 手動更新トリガー（キー入力）
- \[ ] 差分検出（前回更新位置の記録）
- \[ ] 差分ベースの議事録更新
- \[ ] 更新履歴の管理（何回目の更新か）
- \[ ] オプション: 自動更新モード（一定間隔）
- \[ ] 更新中も録音・文字起こしは継続（非同期処理）
- \[ ] 更新完了時にターミナル通知

### 3.5 長文対応（Map-Reduce方式）

長い会議（約20000文字以上の文字起こし）では、Map-Reduce方式で議事録を生成する。

#### 3.5.1 処理の流れ

```
文字起こし（長文）
    ↓
話題の区切りを検出（Claudeに分析させる）
    ↓
[チャンク1] [チャンク2] [チャンク3] ...
    ↓ 各チャンクから要点抽出（Map）
[要点1]    [要点2]    [要点3]
    ↓ 統合して議事録生成（Reduce）
   最終議事録
```

#### 3.5.2 閾値

- `CHUNK_THRESHOLD = 20000` 文字を超えると自動的にMap-Reduce方式に切り替え
- `BOUNDARY_DETECTION_MAX = 30000` 文字ごとに区切り検出を実行

#### 3.5.3 利点

- 長時間会議でもClaudeの出力が途中で切れない
- 話題の区切りで分割するため、文脈が保たれる
- 各チャンクの要点を抽出してから統合するため、品質が安定

### 3.6 設定機能

- \[ ] コマンドライン引数で設定可能
- \[ ] 設定ファイル（`~/.config/meeting-transcriber/config.yaml`）対応
- \[ ] Whisperモデルサイズ選択（tiny/small/medium/large）
- \[ ] 出力ディレクトリ / シンプル出力モード
- \[ ] 議事録テンプレートのカスタマイズ

#### 3.5.1 設定ファイル例

```yaml
# ~/.config/meeting-transcriber/config.yaml

# Whisper設定
model_size: small
language: ja

# LLMバックエンド設定
# api: Anthropic API（従量課金、ANTHROPIC_API_KEY必要）
# claude-agent: Claude Agent SDK（Maxプラン、CLAUDE_CODE_OAUTH_TOKEN必要）
# claude-cli: Claude Code CLI subprocess（Maxプラン、最も安定）
# auto: 利用可能な方式を自動選択（デフォルト）
backend: auto

# 出力設定
output_dir: ./output
simple_output_dir: null  # 指定時はシンプル出力モード（単一ファイル）
filename_format: "meeting_%Y%m%d_%H%M%S"
open_after: true

# テンプレート設定
default_template: default # デフォルトで使用するテンプレート

# オーディオ設定
device_id: null # null = デフォルトデバイス
sample_rate: 16000
chunk_duration: 5

# 議事録設定
auto_update: false
update_interval: 120
version_history: true  # デフォルトで有効（更新ごとにバージョン保存）
```

※ コマンドライン引数は設定ファイルより優先

### 3.7 テンプレート機能

#### 3.7.1 テンプレート保存場所

```
~/.config/meeting-transcriber/
├── config.yaml
└── templates/
    ├── default.md      # デフォルト（汎用）
    ├── 1on1.md         # 1on1ミーティング用
    ├── brainstorm.md   # ブレスト用
    ├── standup.md      # 朝会・スタンドアップ用
    ├── client.md       # 顧客打ち合わせ用
    └── custom.md       # 自作テンプレート
```

#### 3.7.2 テンプレート形式

テンプレートはMarkdown + プレースホルダー形式:

```markdown
---
# メタ情報（YAML形式）
name: "1on1ミーティング"
description: "1対1の定期ミーティング用"
tags:
  - meeting
  - 1on1
---

# 1on1 議事録 - {{date}}

## 基本情報

- **日時**: {{date}} {{time}}
- **参加者**:

## 前回からの進捗

-

## 今回の議題

### 業務について

-

### キャリア・成長について

-

### 困っていること・相談

-

## ネクストアクション

| 担当 | アクション | 期限 |
| ---- | ---------- | ---- |
|      |            |      |

## 次回までの目標

-

---

_自動生成: {{datetime}}_
```

#### 3.7.3 プレースホルダー一覧

| プレースホルダー   | 説明           | 例                         |
| ------------------ | -------------- | -------------------------- |
| `{{date}}`         | 日付           | 2024-12-19                 |
| `{{time}}`         | 開始時刻       | 14:30                      |
| `{{end_time}}`     | 終了時刻       | 15:45                      |
| `{{datetime}}`     | 日時（フル）   | 2024-12-19 14:30:52        |
| `{{duration}}`     | 所要時間       | 01:15:23                   |
| `{{update_count}}` | 更新回数       | 3                          |
| `{{transcript}}`   | 文字起こし全文 | （差分更新時は使用しない） |

#### 3.7.4 ビルトインテンプレート

**default.md（汎用）**

- 標準的な議事録フォーマット
- 議題、議論内容、決定事項、TODO

**1on1.md**

- 進捗確認、キャリア相談、困りごと
- ネクストアクション重視

**brainstorm.md**

- アイデア列挙、グルーピング
- 結論・採用アイデアのまとめ

**standup.md**

- 昨日やったこと、今日やること、困っていること
- シンプル・短時間向け

**client.md**

- 顧客情報、要件、合意事項
- フォーマルな形式

#### 3.7.5 テンプレート使用例

```bash
# デフォルトテンプレート
meeting-transcriber

# 1on1用テンプレート
meeting-transcriber -t 1on1

# ブレスト用
meeting-transcriber --template brainstorm

# テンプレート一覧表示
meeting-transcriber --list-templates

# 出力例:
# 利用可能なテンプレート:
#   default     - 汎用議事録
#   1on1        - 1on1ミーティング用
#   brainstorm  - ブレインストーミング用
#   standup     - 朝会・スタンドアップ用
#   client      - 顧客打ち合わせ用
```

### 3.8 Web UI モード

`--web` 起動で FastAPI + WebSocket サーバーが立ち上がり、ブラウザに3カラムUIを表示。

| カラム      | 内容                                                          |
| ----------- | ------------------------------------------------------------- |
| 左カラム    | 文字起こし（自動スクロール） + ログ                           |
| 中央カラム  | 議事録プレビュー（Markdown レンダリング、自動更新）           |
| 右カラム    | AIチャットパネル（後述 3.9）                                  |
| ヘッダ      | ステータスバー（状態 / 経過時間 / 発言数 / 累計コスト USD）   |
| フッタ      | 議事録への修正指示入力欄                                      |

セキュリティ:
- `Host` ヘッダ検証で DNS rebinding 攻撃を防止
- `Origin` ヘッダ検証で CSRF を防止（GET/HEAD 以外の POST 系すべて）
- WebSocket も accept 前に Origin/Host を検証

`--web-host` / `--web-port` で接続先変更、`--no-browser` でブラウザ自動起動を抑止。

### 3.9 AIチャットパネル（Web UI）

会議中に Claude と議論できる対話インタフェース。**議事録生成とは別 session_id で動作**するため、
チャットでの議論が議事録の構造に混入しない。

- 初回送信時: 会議文字起こし全体 + 質問を1メッセージで送信（プロンプトキャッシュ起点）
- 2回目以降: 前回送信以降の **差分発言** + 質問のみ（Claude セッションが履歴保持）
- WebSocket でチャット履歴をブロードキャスト → 複数タブ・再接続で履歴復元
- `--transcript-only` モードではチャットも無効

### 3.10 セッション継続によるコンテキスト活用

`ClaudeCLIBackend` が `--session-id <uuid>` 付きで `claude -p` を呼ぶ。会議1回 = 1セッション。

- 起動時に UUID を `MeetingTranscriber.__init__` で1度だけ生成
- `has_persistent_context` が True の間、議事録更新プロンプトは **新規発言のみ** を送る
  簡素版 (`SESSION_INCREMENTAL_PROMPT`) を使用
- セッション枯渇／破損のキーワード（`session` / `context` / `token` / `too long` / `limit`）を
  stderr または `is_error: true` レスポンスから検出したら `_session_dead = True`
- 失敗時 `reset_context()` で新規 UUID を生成し、従来パス（議事録全文 or 圧縮版）にフォールバック

詳細は `docs/adr/0001-claude-cli-auth-and-billing.md` 参照。

### 3.11 コスト可視化

2026/6/15 の Claude Agent SDK クレジット分離（Max 5x: $100/月、Max 20x: $200/月）に対応。

- `claude -p` を `--output-format json` で呼び、`total_cost_usd` を抽出
- `Backend.last_cost_usd` / `cumulative_cost_usd` プロパティで参照
- 議事録更新ログ・Web UI ステータスバーに累計 `$X.XXXX` を表示
- AIチャット側 backend のコストも合算
- JSON パース失敗時は生テキストフォールバック（後方互換）

### 3.12 文字起こし専用モード

`--transcript-only` で LLM バックエンドへの接続を完全にスキップ。

- backend / generator を `None` に初期化
- 議事録更新・AIチャット・Claude 指示送信を全てログ通知付きで no-op
- 終了時は `save_transcript_only` で文字起こしのみ保存

LLM 枠を節約したい場面、または後で `--from-file` でバッチ処理する想定で使用。

### 3.13 バッチ処理（テキスト → 議事録）

`--from-file PATH` で既存 `transcript_raw.txt` から議事録のみを後追い生成。

- 単一ファイル / ディレクトリ（再帰探索）/ glob パターンに対応
- 各ファイルを `parse_transcript_file` でエントリ化 → `generate_full` 実行
- 既に `minutes.md` がある対象はスキップ（冪等性）

### 3.14 音声/動画ファイル入力

`-i, --input PATH` で録音済みの音声/動画ファイルから文字起こし → 議事録生成。

- ffmpeg 必須（faster-whisper が内部で ffmpeg を呼び出す）
- 対応音声: \`.wav .mp3 .flac .m4a .ogg .opus .aac .wma\`
- 対応動画: \`.mp4 .mov .mkv .webm .avi .flv .wmv .m4v\`
  （動画は音声トラックを自動抽出）
- 単一ファイル / ディレクトリ / glob パターンに対応
- `Transcriber.transcribe_file()` が segment 単位の `(start_sec, end_sec, text)` をストリームで返す
  → 長尺ファイルでも省メモリ
- 出力先: \`<output_dir>/<filename>_<timestamp>/{minutes.md, transcript_raw.txt}\`
- `--transcript-only` 併用で文字起こしのみ
- 既存マイク入力経路 (\`AudioRecorder\`) は温存、選択肢を1つ増やすだけ

---

## 4. 技術要件

### 4.1 動作環境

- OS: Linux (Ubuntu 22.04+)
- Python: 3.10+
- GPU: NVIDIA CUDA対応GPU（推奨）、またはCPU動作

### 4.2 依存パッケージ

```txt
# requirements.txt
faster-whisper>=1.0.0
sounddevice>=0.4.6
numpy>=1.24.0
anthropic>=0.18.0        # API方式用
claude-code-sdk>=0.0.1   # Claude Agent SDK方式用（Maxプラン活用）
python-dotenv>=1.0.0
textual>=0.50.0          # TUIフレームワーク
pyyaml>=6.0              # 設定ファイル用
anyio>=4.0.0             # 非同期処理用
```

### 4.3 環境変数

```bash
# API方式を使用する場合
ANTHROPIC_API_KEY=sk-ant-xxxxx

# Claude Agent SDK方式を使用する場合（OAuthトークン）
CLAUDE_CODE_OAUTH_TOKEN=xxxxx  # claude setup-token で取得

# Claude CLI方式の場合は環境変数不要（CLIがMaxプラン認証を管理）
```

---

## 5. インターフェース設計

### 5.1 コマンドライン引数

```bash
meeting-transcriber [OPTIONS]

# Whisper 設定
  -m, --model {tiny|small|medium|large-v3}   モデルサイズ (default: small)
  -l, --language LANG                        認識言語 (default: ja)
  -d, --device ID                            音声入力デバイスID
  --compute-device {auto|cuda|cpu}           実行デバイス
  --list-devices                             マイク一覧表示
  --no-realtime                              リアルタイム表示を無効化

# LLM バックエンド
  -b, --backend {api|claude-agent|claude-cli|openai_compat|local|auto}
                                             LLM バックエンド (default: auto)
                                             local は openai_compat の旧名（deprecated）

# 出力
  -o, --output PATH                          出力ディレクトリ
  -f, --filename FORMAT                      ファイル名フォーマット
  --simple-output PATH                       単一ファイル出力モード
  --open-after                               終了後にファイルを開く

# テンプレート
  -t, --template NAME                        テンプレート名
  --list-templates                           テンプレート一覧

# 動作モード
  --auto-update                              自動更新を有効化
  --update-interval SEC                      自動更新間隔（秒）
  --version-history                          更新ごとにバージョン保存
  --transcript-only                          文字起こしのみ（LLM 接続なし）
  --from-file PATH                           既存文字起こしからバッチ生成

# UI
  --no-tui                                   TUI 無効（シンプル CLI）
  --web                                      Web UI モード
  --web-host HOST                            Web UI バインドホスト (default: 127.0.0.1)
  --web-port PORT                            Web UI ポート (default: 8765)
  --no-browser                               Web UI でブラウザを自動起動しない

# その他
  --show-config                              現在の設定を表示
  --help, -h                                 ヘルプ
```

### 5.2 キー操作（TUI / Web UI 共通）

| キー  | 動作                                       | TUI | Web UI |
| ----- | ------------------------------------------ | --- | ------ |
| `u`   | 議事録を差分更新                           | ✓   | ✓      |
| `f`   | 議事録をフル更新（全体再生成）             | ✓   | ✓      |
| `s`   | 文字起こしを保存                           | ✓   | ✓      |
| `p`   | 一時停止/再開                              | ✓   | ✓      |
| `c`   | コマンド入力（Claudeに議事録修正を指示）    | ✓   | —      |
| `q`   | 終了                                       | ✓   | ✓      |
| `?`   | ヘルプ                                     | ✓   | —      |

### 5.3 使用例

```bash
# 基本的な使用（TUIモード、バックエンド自動選択）
meeting-transcriber

# Claude Agent SDK を使用（Maxプラン + OAuthトークン）
meeting-transcriber --backend claude-agent

# Claude Code CLI を使用（Maxプラン + subprocess、最も安定）
meeting-transcriber --backend claude-cli

# API を使用（従量課金）
meeting-transcriber --backend api

# シンプル出力モード（単一ファイルを直接出力）
meeting-transcriber --simple-output ~/Documents/meetings/

# テンプレートを指定して起動
meeting-transcriber -t 1on1
meeting-transcriber --template brainstorm
meeting-transcriber -t client --simple-output ~/Documents/meetings/

# テンプレート一覧を表示
meeting-transcriber --list-templates

# 出力先を任意のフォルダに指定
meeting-transcriber -o ~/Documents/meetings

# TUIを無効化してシンプルモードで実行
meeting-transcriber --no-tui

# モデルとデバイスを指定
meeting-transcriber -m medium -d 2

# GPU使用
meeting-transcriber --compute-device cuda
```

---

## 6. クラス設計

### 6.1 メインクラス構成

```python
class AudioRecorder:
    """音声入力を管理"""
    def __init__(self, device_id: int | None, sample_rate: int)
    def start(self) -> None
    def stop(self) -> None
    def pause(self) -> None
    def resume(self) -> None
    def get_audio_data(self) -> np.ndarray

class Transcriber:
    """Whisperによる文字起こし"""
    def __init__(self, model_size: str, language: str, device: str)
    def transcribe(self, audio: np.ndarray) -> str

class TemplateManager:
    """テンプレートの管理"""
    def __init__(self, templates_dir: Path)
    def list_templates(self) -> list[TemplateInfo]
    def get_template(self, name: str) -> Template
    def render(self, template: Template, context: dict) -> str
    def install_builtin_templates(self) -> None  # 初回セットアップ

class MinutesGenerator:
    """バックエンドによる議事録生成"""
    def __init__(self, backend: Backend, template_manager: TemplateManager)
    def generate_full(self, transcripts: list[TranscriptEntry], template: Template) -> str
    def generate_incremental(self, current_minutes: str, new_transcripts: list[TranscriptEntry]) -> str

class MinutesUpdater:
    """議事録の更新状態を管理"""
    def __init__(self, generator: MinutesGenerator, output_dir: Path)
    def update(self, transcripts: list[TranscriptEntry], full: bool = False) -> str
    def get_new_transcripts(self, transcripts: list[TranscriptEntry]) -> list[TranscriptEntry]
    def save(self) -> Path
    def get_current_minutes(self) -> str

    # 状態
    last_update_index: int  # 前回更新時の文字起こしインデックス
    update_count: int
    current_minutes: str

class KeyboardHandler:
    """非ブロッキングキー入力を処理"""
    def __init__(self)
    def get_key(self) -> str | None  # 非ブロッキング
    def wait_key(self) -> str  # ブロッキング

class MeetingTranscriber:
    """メインオーケストレーター"""
    def __init__(self, config: Config)
    def run(self) -> None
    def handle_key(self, key: str) -> bool  # Falseで終了
    def save_output(self) -> Path
```

### 6.2 データクラス

```python
@dataclass
class Config:
    model_size: str = "small"
    language: str = "ja"
    chunk_duration: float = 5.0
    sample_rate: int = 16000
    device_id: int | None = None
    realtime_display: bool = True

    # LLMバックエンド設定
    backend: str = "auto"  # api | claude-agent | claude-cli | auto

    # 出力設定
    output_dir: Path = Path("./output")
    filename_format: str = "meeting_%Y%m%d_%H%M%S"
    simple_output_dir: Path | None = None  # 指定時はシンプル出力モード
    open_after: bool = False

    # テンプレート設定
    template: str = "default"  # テンプレート名
    templates_dir: Path = Path("~/.config/meeting-transcriber/templates").expanduser()

    # 議事録更新設定
    auto_update: bool = False  # デフォルトは手動更新
    update_interval: int = 120  # 自動更新時の間隔（秒）
    version_history: bool = True  # デフォルトで有効

    def get_output_path(self) -> Path:
        """実際の出力先パスを取得"""
        if self.simple_output_dir:
            return self.simple_output_dir
        return self.output_dir

    def get_template_path(self) -> Path:
        """テンプレートファイルのパスを取得"""
        return self.templates_dir / f"{self.template}.md"

@dataclass
class TranscriptEntry:
    timestamp: datetime
    text: str
    index: int  # 通し番号（差分検出用）

    def __str__(self) -> str:
        return f"[{self.timestamp.strftime('%H:%M:%S')}] {self.text}"

@dataclass
class TemplateInfo:
    """テンプレートのメタ情報"""
    name: str           # ファイル名（拡張子なし）
    display_name: str   # 表示名
    description: str    # 説明
    tags: list[str]     # Obsidian用タグ

@dataclass
class Template:
    """テンプレート本体"""
    info: TemplateInfo
    content: str        # テンプレート本文
    prompt_hint: str    # Claude APIへの追加指示（オプション）

@dataclass
class UpdateResult:
    """更新結果"""
    success: bool
    minutes: str
    new_entries_count: int
    total_entries_count: int
    update_number: int
    error: str | None = None
```

---

## 7. 出力形式

### 7.1 議事録テンプレート（デフォルト）

```markdown
---
date: { { date } }
time: "{{time}}"
duration: "{{duration}}"
tags:
  - meeting
  - auto-generated
aliases:
  - "{{date}} 会議"
---

# 議事録 - {{date}}

## 基本情報

- **日時**: {{date}} {{time}} - {{end_time}}
- **参加者**: （音声から推測、または「不明」）

## 議題・アジェンダ

-

## 議論内容

### トピック1

-

## 決定事項

- [ ]

## アクションアイテム

| 担当 | タスク | 期限 |
| ---- | ------ | ---- |
|      |        |      |

## 次回予定

-

---

_この議事録はAIによって自動生成されました（{{update_count}}回更新）_
```

### 7.2 出力ファイル構成

**通常モード（`--output`指定時）:**

```
output/
├── meeting_20241219_143052/
│   ├── minutes.md              # 最新の議事録（リアルタイム更新）
│   ├── minutes_final.md        # 最終版議事録（会議終了時に生成）
│   ├── transcript_raw.txt      # 生の文字起こしデータ
│   └── history/                # version_history有効時（デフォルト）
│       ├── minutes_v001.md     # 1回目更新
│       ├── minutes_v002.md     # 2回目更新
│       └── ...
```

**シンプル出力モード（`--simple-output`指定時）:**

```
~/Documents/meetings/
├── meeting_20241219_143052.md   # 議事録（単一ファイル）
├── meeting_20241219_160030.md
└── ...
```

※ シンプル出力モードではセッションディレクトリを作成せず、議事録ファイルのみを出力

### 7.3 実行時の表示例

```
🎙️ 録音開始...
────────────────────────────────────
操作: [u/Enter] 更新  [f] フル更新  [s] 保存  [p] 一時停止  [q] 終了  [?] ヘルプ
────────────────────────────────────
[14:30:05] 今日は新機能のリリースについて話し合いたいと思います
[14:30:12] まず、進捗状況を確認しましょう
[14:30:25] バックエンドの実装は完了しています
[14:30:35] フロントエンドはあと2日で完了予定です

> u  ← ユーザーが 'u' キーを押す

📋 議事録を更新中... (1回目)
✅ 議事録を更新しました → minutes.md
   新規発言: 4件 | 経過時間: 0:00:35
────────────────────────────────────
[14:31:02] テストの進捗はどうですか
[14:31:15] 単体テストは80%完了、結合テストはこれからです
[14:31:30] リリース日は来週の水曜日を予定しています
[14:31:45] 問題なければそれで進めましょう

> u  ← ユーザーが 'u' キーを押す

📋 議事録を更新中... (2回目, 差分: 4件)
✅ 議事録を更新しました → minutes.md
   新規発言: 4件 | 経過時間: 0:01:45
────────────────────────────────────
[14:32:10] 他に議題はありますか

> q  ← ユーザーが 'q' キーを押す

📋 最終議事録を生成中...
✅ 完了しました
   出力: ./output/20241219_143005/
   - minutes.md (最終版)
   - minutes_final.md
   - transcript_raw.txt
```

### 7.4 TUIモード（デフォルト）

Textualフレームワークを使用した3パネル構成のTUIインターフェース。

```
┌─────────────────────────────────────────────────────────────────┐
│  Meeting Transcriber          Model: small | Device: cuda      │
├─────────────────────────────────────────────────────────────────┤
│ [ Log ]                                                         │
│ 14:30:05 録音開始...                                            │
│ 14:30:35 更新完了 | 新規: 4件                                   │
├─────────────────────────────────────────────────────────────────┤
│ [ Transcript ]                                                  │
│ [14:30:05] 今日は新機能のリリースについて話し合いたいと思います │
│ [14:30:12] まず、進捗状況を確認しましょう                       │
│ [14:30:25] バックエンドの実装は完了しています                   │
├─────────────────────────────────────────────────────────────────┤
│ [ Minutes Preview ]                                             │
│ # 議事録 - 2024-12-19                                           │
│ ## 議題                                                         │
│ - 新機能リリースについて                                        │
├─────────────────────────────────────────────────────────────────┤
│ [ Claude Command ]                                              │
│ > 決定事項を箇条書きにして                                      │
├─────────────────────────────────────────────────────────────────┤
│ 録音中 | 経過: 0:05:30 | 発言: 15件 | 更新: 2回                  │
├─────────────────────────────────────────────────────────────────┤
│ u 差分更新  f フル更新  s 保存  p 一時停止  c コマンド  q 終了  │
└─────────────────────────────────────────────────────────────────┘
```

**パネル構成:**

| パネル           | 説明                                           |
| ---------------- | ---------------------------------------------- |
| Log              | 操作ログ・ステータスメッセージ                 |
| Transcript       | リアルタイム文字起こし                         |
| Minutes Preview  | 現在の議事録プレビュー（Markdown）             |
| Claude Command   | Claudeへの議事録修正指示を入力                 |
| Status Bar       | 録音状態・経過時間・発言数・更新回数           |
| Footer           | キーバインド一覧                               |

**コマンド入力例:**

`c`キーで入力欄にフォーカスし、Claudeに議事録修正の指示を送れます：

```
「アジェンダを議題に統一して」
「決定事項を箇条書きにして」
「参加者リストを追加して」
```

---

## 8. エラーハンドリング

### 8.1 対応すべきエラー

| エラー種別                   | 対応                                         |
| ---------------------------- | -------------------------------------------- |
| マイクアクセス失敗           | デバイス一覧表示して再選択を促す             |
| Whisperモデル読み込み失敗    | モデルダウンロードを試行、失敗時はエラー終了 |
| CUDA利用不可                 | 自動的にCPUフォールバック                    |
| API Key未設定                | 環境変数設定方法を表示（API方式の場合）      |
| OAuthトークン未設定/期限切れ | `claude setup-token` の実行を促す            |
| APIレート制限                | リトライ（exponential backoff）              |
| ディスク容量不足             | 警告表示して続行確認                         |
| Claude CLI未インストール     | 他のバックエンドにフォールバック             |
| Maxプラン レート制限         | 待機 or APIにフォールバック                  |

### 8.2 グレースフルシャットダウン

- Ctrl+C でクリーンに終了
- 録音中のデータは保存してから終了
- 部分的な文字起こしでも議事録生成を試行

---

## 9. 実装優先順位

### Phase 1: MVP（必須機能）

1. 基本的な音声録音機能
2. Whisperによるチャンク単位の文字起こし
3. リアルタイム文字起こし表示
4. **手動トリガーによる議事録更新（差分方式）** ← メイン機能
5. Claude APIによる議事録生成
6. Markdown形式での出力
7. キーボード操作（u: 更新, q: 終了）
8. デフォルトテンプレート1つ

### Phase 2: 改善

1. フル更新オプション（fキー）
2. 一時停止/再開機能
3. コマンドライン引数対応
4. **テンプレート選択機能（-t オプション）**
5. **ビルトインテンプレート（1on1, brainstorm, standup, client）**
6. Obsidian Vault出力対応
7. バージョン履歴保存
8. 自動更新モード（オプション）
9. 設定ファイル対応

### Phase 3: 拡張（オプション）

1. 話者分離（pyannote-audio）
2. Web UI（Gradio/Streamlit）でリアルタイム議事録表示
3. 既存音声ファイルの処理対応
4. カスタムテンプレート作成ガイド
5. WebSocket経由でブラウザにリアルタイム配信

---

## 10. テスト要件

### 10.1 動作確認項目

- \[ ] マイク入力が正常に取得できる
- \[ ] 5秒程度の発話が文字起こしされる
- \[ ] 日本語が正しく認識される
- \[ ] リアルタイムで文字起こしが表示される
- \[ ] `u`キーで議事録が更新される
- \[ ] 2回目以降の更新で差分が正しく反映される
- \[ ] `f`キーでフル更新ができる
- \[ ] `q`キーで正常終了し最終議事録が生成される
- \[ ] ファイルが正しく保存される
- \[ ] 更新中も録音が継続される
- \[ ] `--simple-output` 指定時に単一ファイルで出力される
- \[ ] 設定ファイルが正しく読み込まれる
- \[ ] TUIモードで正常に動作する
- \[ ] `--no-tui` でシンプルモードで動作する
- \[ ] `c`キーでClaudeへの指示入力ができる
- \[ ] `--list-templates` でテンプレート一覧が表示される
- \[ ] `-t` オプションで指定したテンプレートが使用される
- \[ ] テンプレートのプレースホルダーが正しく置換される
- \[ ] `--backend api` でAPI経由の議事録生成ができる
- \[ ] `--backend claude-agent` でClaude Agent SDK経由の生成ができる
- \[ ] `--backend claude-cli` でClaude Code CLI経由の生成ができる
- \[ ] `--backend auto` で適切なバックエンドが選択される
- \[ ] 各バックエンドの認証情報がない場合に適切なエラーが表示される

### 10.2 テスト用スクリプト

```bash
# デバイス確認
meeting-transcriber --list-devices

# 基本テスト（TUIモード、バックエンド自動選択）
meeting-transcriber

# バックエンド指定テスト
meeting-transcriber --backend api            # API方式
meeting-transcriber --backend claude-agent   # Claude Agent SDK方式
meeting-transcriber --backend claude-cli     # Claude Code CLI方式

# シンプル出力モードテスト
meeting-transcriber --simple-output ~/Documents/meetings/

# TUIなしでテスト
meeting-transcriber --no-tui

# 自動更新モードでテスト
meeting-transcriber --auto-update --update-interval 30

# 設定ファイルの場所を確認
meeting-transcriber --show-config

# フル機能テスト（Maxプラン + 1on1 + シンプル出力）
meeting-transcriber -b claude-cli -t 1on1 --simple-output ~/Documents/meetings/
```

### 10.3 テストシナリオ

**シナリオ1: 基本操作**

1. 起動して30秒程度発話
2. `u`キーで更新 → 議事録が生成されることを確認
3. さらに30秒発話
4. `u`キーで更新 → 差分が反映されることを確認
5. `q`キーで終了

**シナリオ2: フル更新**

1. 起動して発話
2. `u`キーで数回更新
3. `f`キーでフル更新 → 全体が再構成されることを確認

**シナリオ3: シンプル出力**

1. `--simple-output ~/Documents/meetings/` で起動
2. 発話して `u`キーで更新
3. `q`キーで終了
4. 指定フォルダに単一の議事録ファイルが作成されることを確認

**シナリオ4: テンプレート切り替え**

1. `--list-templates` でテンプレート一覧を確認
2. `-t 1on1` で起動
3. 発話して `u`キーで更新
4. 1on1用のフォーマットで議事録が生成されることを確認
5. `-t brainstorm` で再度起動し、異なるフォーマットになることを確認

**シナリオ5: バックエンド切り替え**

1. `--backend api` で起動 → APIが使用されることを確認
2. `--backend claude-agent` で起動 → Claude Agent SDKが使用されることを確認
3. `--backend claude-cli` で起動 → Claude Code CLIが使用されることを確認
4. `--backend auto` で起動 → 適切なバックエンドが自動選択されることを確認
5. 環境変数なしで `--backend auto` → 利用可能な方式にフォールバックすることを確認

---

## 11. 注意事項

### 11.1 セキュリティ

- APIキーは環境変数または.envファイルで管理（.gitignore必須）
- 音声データはローカル処理、外部送信しない（Whisperはローカル実行）
- Claude APIへは文字起こしテキストのみ送信

### 11.2 パフォーマンス

- GPUがある場合は`device="cuda"`を使用
- メモリ8GB以上推奨（mediumモデル使用時）
- smallモデルで十分な精度が得られる場合が多い

### 11.3 コスト比較（バックエンド別）

#### API方式（従量課金）

```
Claude Sonnet 料金:
  入力: $3 / 1M tokens
  出力: $15 / 1M tokens

1時間会議で5回更新した場合:
  → 約10k tokens → 約 $0.03〜0.05

月100回会議: 約 $3〜5
```

#### Claude Agent SDK / Claude CLI方式（Maxプラン）

```
Maxプラン料金:
  Max5:  $100/月（5倍の使用量）
  Max20: $200/月（20倍の使用量）

議事録生成はMaxプランの使用量にカウント
→ 追加コストなし（プラン内）

注意:
  - 他のClaude使用と合算される
  - レート制限に達する可能性あり
  - 大量の会議がある場合はAPI方式推奨
```

#### どちらを選ぶべきか

| ユースケース                    | 推奨バックエンド        |
| ------------------------------- | ----------------------- |
| Maxプラン加入済み、安定性重視   | `claude-cli`            |
| Maxプラン加入済み、クリーン実装 | `claude-agent`          |
| Maxプラン加入済み、会議多め     | `api`（レート制限回避） |
| Maxプラン未加入                 | `api`                   |

**デフォルト（auto）の挙動:**

1. `CLAUDE_CODE_OAUTH_TOKEN` あり → `claude-agent`
2. `claude` CLI が利用可能 → `claude-cli`
3. `ANTHROPIC_API_KEY` あり → `api`

### 11.4 既知の制限

- 複数話者の区別は基本機能では非対応
- 雑音の多い環境では認識精度低下
- 長時間（2時間以上）の会議はメモリ使用量に注意

### 11.5 実装上の注意点

#### 非ブロッキングキー入力

録音中もキー入力を受け付けるため、非ブロッキング方式が必要:

```python
# Linux向け実装例
import sys
import select
import termios
import tty

def get_key_nonblocking() -> str | None:
    """非ブロッキングでキー入力を取得"""
    if select.select([sys.stdin], [], [], 0)[0]:
        return sys.stdin.read(1)
    return None

# または curses / readchar ライブラリを使用
```

#### スレッド構成

```
┌─────────────────────────────────────────────────────────────┐
│  Main Thread                                                │
│  └─ キー入力監視 + 表示制御                                  │
│                                                             │
│  Audio Thread (daemon)                                      │
│  └─ sounddevice callback → audio_queue                     │
│                                                             │
│  Transcribe Thread (daemon)                                 │
│  └─ audio_queue → Whisper → transcript_list                │
│                                                             │
│  Update Thread (on-demand)                                  │
│  └─ 'u'キー押下時に起動 → Claude API → minutes更新          │
└─────────────────────────────────────────────────────────────┘
```

---

## 12. 参考リンク

- [faster-whisper GitHub](https://github.com/SYSTRAN/faster-whisper)
- [Anthropic API Documentation](https://docs.anthropic.com/)
- [Claude Agent SDK (PyPI)](https://pypi.org/project/claude-agent-sdk/)
- [Claude Agent SDK (GitHub)](https://github.com/anthropics/claude-agent-sdk-python)
- [sounddevice Documentation](https://python-sounddevice.readthedocs.io/)
