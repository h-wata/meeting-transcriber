# Meeting Transcriber

リアルタイム議事録生成ツール。faster-whisper で文字起こし、Claude などの LLM で議事録化。

## 特徴

- ブラウザ UI（推奨）／ ターミナル TUI ／ シンプル CLI の3モード
- Web UI に **AIチャットパネル**: 会議中に「この議論どう思う？」を Claude に相談
- LLM バックエンド: Claude Code CLI / Anthropic API / OpenAI互換（Groq・OpenRouter・LM Studio等）
- セッション継続・圧縮更新・Map-Reduce による効率的な議事録生成
- バッチ処理（`--from-file`）、文字起こし専用（`--transcript-only`）

## インストール

```bash
# uv（推奨）
git clone https://github.com/h-wata/meeting-transcriber.git
cd meeting-transcriber
uv sync                # CPU
uv sync --extra cuda   # GPU

# pip
pip install meeting-transcriber          # CPU
pip install meeting-transcriber[cuda]    # GPU
```

Linux は別途 PortAudio が必要:

```bash
sudo apt install libportaudio2 portaudio19-dev
```

## セットアップ

LLM バックエンドのいずれか1つを用意:

```bash
# Claude Code CLI（Max プラン推奨）
npm install -g @anthropic-ai/claude-code && claude auth login

# Anthropic API
export ANTHROPIC_API_KEY="sk-ant-..."

# Groq（爆速・無料枠あり）
export GROQ_API_KEY="gsk_..."

# ローカル LLM（LM Studio / Ollama / vLLM）は起動してあれば auto で検出
```

## 使い方

```bash
meeting-transcriber --web                 # Web UI（推奨）
meeting-transcriber                       # TUI
meeting-transcriber --no-tui              # シンプル CLI

meeting-transcriber --list-devices        # マイク一覧
meeting-transcriber -m medium             # Whisper モデル変更
meeting-transcriber --compute-device cuda # GPU 使用
meeting-transcriber -t 1on1               # テンプレート (default/1on1/brainstorm/standup/client)
```

### Web UI

`--web` で `http://127.0.0.1:8765` がブラウザで開きます。3カラム構成（文字起こし+ログ ／ 議事録プレビュー ／ AIチャット）。

`-w, --web-host`, `--web-port`, `--no-browser` で挙動を調整可能。

### キー操作（TUI / Web UI 共通）

| キー | 機能 |
| --- | --- |
| `u` / `f` | 差分更新 / フル更新 |
| `s` | 保存 |
| `p` | 一時停止/再開 |
| `q` | 終了 |
| `c` | コマンド入力（TUI のみ、Claude に修正指示） |

### 音声/動画ファイル入力

録音済みの音声/動画ファイルから直接議事録を生成（要 `ffmpeg`）:

```bash
meeting-transcriber --input meeting.wav             # 音声ファイル
meeting-transcriber --input meeting.mp4             # 動画ファイル
meeting-transcriber --input "~/recordings/*.wav"    # glob
meeting-transcriber --input ./recordings/           # ディレクトリ
meeting-transcriber --input meeting.mp4 --transcript-only  # 文字起こしのみ
```

対応形式: `.wav .mp3 .flac .m4a .ogg .opus .aac` / `.mp4 .mov .mkv .webm .avi` など ffmpeg がデコードできるもの全般。
出力は `<output_dir>/<filename>_<timestamp>/{minutes.md, transcript_raw.txt}`。

```bash
# Ubuntu/Debian
sudo apt install ffmpeg
# macOS
brew install ffmpeg
```

### バッチ処理

既存の `transcript_raw.txt` から議事録だけ後で生成:

```bash
meeting-transcriber --from-file <path>                # 単一 / ディレクトリ / glob
```

既に `minutes.md` があるディレクトリはスキップされます。

### 文字起こし専用

```bash
meeting-transcriber --transcript-only    # LLM 接続なし
```

### シンプル出力

```bash
meeting-transcriber --simple-output ~/Documents/meetings/    # 単一ファイル出力
```

## LLM バックエンド

`-b` または config の `backend` で指定。`auto` は ローカルLLM → Claude Agent → Claude CLI → API の順で自動選択（cloud OpenAI 互換は明示指定のみ、課金経路に勝手に倒さない）。

| backend | 用途 | 必要環境 |
| --- | --- | --- |
| `claude-cli` | Claude Code CLI（Max プラン枠） | `claude` コマンド + ログイン済み |
| `claude-agent` | Claude Agent SDK | `CLAUDE_CODE_OAUTH_TOKEN` |
| `api` | Anthropic API（従量課金） | `ANTHROPIC_API_KEY` |
| `openai_compat` | OpenAI 互換（ローカル & cloud） | エンドポイント / API key |
| `auto` | 上記から自動選択 | — |

### OpenAI 互換の設定例

`~/.config/meeting-transcriber/config.yaml` の `local_llm` セクションで切替:

```yaml
backend: openai_compat
local_llm:
  # ローカル LM Studio
  base_url: http://localhost:1234/v1
  model: ""                                # 空ならロード済みモデルを自動検出

  # Groq の場合
  # base_url: https://api.groq.com/openai/v1
  # api_key_env: GROQ_API_KEY
  # model: llama-3.3-70b-versatile

  # OpenRouter の場合
  # base_url: https://openrouter.ai/api/v1
  # api_key_env: OPENROUTER_API_KEY
  # model: anthropic/claude-sonnet-4.6

  # DeepSeek の場合
  # base_url: https://api.deepseek.com/v1
  # api_key_env: DEEPSEEK_API_KEY
  # model: deepseek-chat

  max_tokens: 8192
  temperature: 0.3
```

> API key は必ず環境変数 (`api_key_env`) 経由で渡してください。設定ファイルへの直書きは漏洩リスクがあります。

## 設定ファイル

雛形を自動生成:

```bash
meeting-transcriber --init-config              # ~/.config/meeting-transcriber/config.yaml を作成
meeting-transcriber --init-config --force      # 既存があれば上書き
```

[`examples/config.yaml`](examples/config.yaml) に全項目を網羅したリファレンスがあります（Groq/OpenRouter/DeepSeek の cloud 設定例つき）。

`~/.config/meeting-transcriber/config.yaml` の基本構造（全項目オプション、未指定はデフォルト値）:

```yaml
model_size: small          # tiny / small / medium / large-v3
language: ja
compute_device: auto       # auto / cuda / cpu
backend: auto              # auto / claude-cli / claude-agent / api / openai_compat
output_dir: ./output
template: default          # default / 1on1 / brainstorm / standup / client
auto_update: true
update_interval: 120
version_history: true
transcript_only: false
```

テンプレートは `~/.config/meeting-transcriber/templates/` に追加可能。全 CLI オプションは `meeting-transcriber --help` を参照。

## 補足

- **セッション継続**: Claude Code CLI 使用時、会議1回 = 1セッション ID で `--session-id` 付き呼び出し → プロンプトキャッシュ有効化。設定不要。詳細は [docs/adr/0001-claude-cli-auth-and-billing.md](docs/adr/0001-claude-cli-auth-and-billing.md)
- **コスト可視化**: `claude -p --output-format json` から `total_cost_usd` を取得し、Web UI ステータスバーに累計表示

## トラブルシューティング

| 症状 | 対処 |
| --- | --- |
| `Unable to load libcudnn_ops.so.9` | `uv sync --reinstall` で依存再構築 |
| マイクが認識されない | `--list-devices` で ID 確認 → `-d <ID>` で指定 |
| 認識精度が低い | `-m medium` または `-m large-v3 --compute-device cuda` |

## ライセンス・謝辞

MIT License.

[faster-whisper](https://github.com/SYSTRAN/faster-whisper) / [Textual](https://github.com/Textualize/textual) / [FastAPI](https://fastapi.tiangolo.com/) / [Anthropic Claude](https://www.anthropic.com/)
