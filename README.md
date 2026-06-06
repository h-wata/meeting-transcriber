# Meeting Transcriber

リアルタイム議事録生成ツール。音声をWhisperで文字起こしし、Claudeで議事録を自動生成します。

## 特徴

- リアルタイム音声認識（faster-whisper）
- 複数LLMバックエンド対応（Claude Code CLI / Anthropic API / Claude Agent SDK / ローカルLLM）
- 2種類のUI（ブラウザ向け **Web UI** ／ ターミナル向け **TUI**）
- 会議中に Claude に相談できる **AIチャットパネル**（Web UI）
- セッション継続で会議の文脈を Claude に蓄積（プロンプトキャッシュ最適化）
- 差分更新／圧縮更新／Map-Reduce による効率的な議事録更新
- 複数のテンプレート対応（デフォルト、1on1、ブレスト、スタンドアップ、クライアント）
- 既存文字起こしからのバッチ処理（`--from-file`）
- 文字起こし専用モード（`--transcript-only`、LLM接続なし）
- シンプル出力モード（単一ファイル出力）

## 必要要件

- Python 3.10以上
- マイク入力デバイス
- LLMバックエンド（いずれか1つ）:
  - ローカルLLM: LM Studio / Ollama / vLLM等（無料）
  - Claude Code CLI（Maxプラン）
  - Anthropic API Key（従量課金）

### Linux

PortAudioライブラリが必要です：

```bash
sudo apt install libportaudio2 portaudio19-dev
```

### GPU使用時（推奨）

- NVIDIA GPU（CUDA対応）
- CUDA 12.x
- cuDNN 9.x（自動インストール）

## インストール

### uvを使用（推奨）

```bash
git clone https://github.com/h-wata/meeting-transcriber.git
cd meeting-transcriber
uv sync
```

**GPU (CUDA) を使用する場合：**

```bash
uv sync --extra cuda
```

### pipを使用

```bash
pip install meeting-transcriber

# GPU (CUDA) を使用する場合
pip install meeting-transcriber[cuda]
```

## セットアップ

### Claude認証（いずれか1つ）

**方法1: Claude Code CLI（Maxプラン向け・推奨）**

```bash
# Claude Code CLIをインストール
npm install -g @anthropic-ai/claude-code

# 認証
claude auth login
```

**方法2: Anthropic API Key**

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

### 音声デバイスの確認

```bash
meeting-transcriber --list-devices
```

## 使い方

### 基本的な使用方法

```bash
# TUIモードで起動（デフォルト）
meeting-transcriber

# Web UIモードで起動（ブラウザが自動で開く）
meeting-transcriber --web

# 出力先を指定
meeting-transcriber -o ~/Documents/meetings/

# モデルサイズを指定（tiny/small/medium/large-v3）
meeting-transcriber -m medium

# GPU使用
meeting-transcriber --compute-device cuda
```

### Web UIモード（推奨）

```bash
meeting-transcriber --web
```

`http://127.0.0.1:8765` がブラウザで自動的に開きます。3 カラム構成：

- **文字起こし** + **ログ**（左カラム）: リアルタイム表示
- **議事録プレビュー**（中央）: Markdown レンダリング、自動更新
- **AIに聞く**（右カラム）: 会議中にClaudeに相談できるチャットパネル

#### AIチャットパネル

「この2人の意見、噛み合ってる？」「この議論の論点を整理して」といった
質問を、その時点の文字起こしを文脈として Claude が答えます。
議事録生成とは別セッションで動くため、議事録の構造には影響しません。

```bash
# Web UI起動時のオプション
meeting-transcriber --web                          # デフォルト（127.0.0.1:8765）
meeting-transcriber --web --web-port 8080          # ポート変更
meeting-transcriber --web --no-browser             # ブラウザ自動起動なし
```

#### キーボードショートカット（Web UI）

| キー | 機能       |
| ---- | ---------- |
| `u`  | 差分更新   |
| `f`  | フル更新   |
| `s`  | 保存       |
| `p`  | 一時停止/再開 |
| `q`  | 終了       |

### TUI操作

| キー | 機能                           |
| ---- | ------------------------------ |
| `u`  | 差分更新（新しい発言のみ反映） |
| `f`  | フル更新（全体を再生成）       |
| `s`  | 文字起こしを保存               |
| `p`  | 一時停止/再開                  |
| `c`  | コマンド入力（Claudeに指示）   |
| `?`  | ヘルプ表示                     |
| `q`  | 終了                           |

### コマンド入力例

`c`キーで入力欄にフォーカスし、Claudeに議事録修正の指示を送れます：

```
「アジェンダを議題に統一して」
「決定事項を箇条書きにして」
「参加者リストを追加して」
```

### テンプレート

```bash
# 利用可能なテンプレート一覧
meeting-transcriber --list-templates

# テンプレートを指定
meeting-transcriber -t 1on1
meeting-transcriber -t brainstorm
meeting-transcriber -t standup
meeting-transcriber -t client
```

### ローカルLLMバックエンド（LM Studio等）

OpenAI互換APIサーバー（LM Studio, Ollama, vLLM等）をバックエンドとして使用できます。

```bash
# LM Studioサーバーを起動してモデルをロード
lms server start
lms load google/gemma-4-e4b -y

# ローカルLLMで起動
meeting-transcriber --backend local
```

`auto`モードではローカルLLMサーバーが起動していれば最優先で使用されます。

設定ファイルでの指定：

```yaml
backend: local  # または auto（サーバー起動時に自動選択）
local_llm:
  base_url: http://localhost:1234/v1
  model: ""  # 空の場合はロード済みモデルを自動検出
  max_tokens: 8192
  temperature: 0.3
```

### バッチ処理（既存の文字起こしから議事録生成）

`transcript_raw.txt` が既にある場合、バッチ処理で議事録を生成できます。

```bash
# 単一ファイル
meeting-transcriber --from-file ~/Documents/v2t/meeting_20251219_172043/transcript_raw.txt --backend local

# ディレクトリ指定（配下のtranscript_raw.txtを全て処理）
meeting-transcriber --from-file ~/Documents/v2t/ --backend local

# globパターン
meeting-transcriber --from-file "~/Documents/v2t/meeting_202512*/transcript_raw.txt" --backend local
```

既に `minutes.md` が存在するディレクトリはスキップされます。

### シンプル出力モード

セッションディレクトリを作成せず、単一のMarkdownファイルを直接出力します。

```bash
meeting-transcriber --simple-output ~/Documents/meetings/
```

### 文字起こし専用モード

LLMバックエンドに接続せず、文字起こしだけ実行します。後でバッチ処理で議事録を生成する想定や、
LLM枠を消費したくない場面に便利です。

```bash
meeting-transcriber --transcript-only
```

### セッション継続によるコンテキスト活用

Claude Code CLIバックエンド使用時、会議1回 = 1セッション ID として `--session-id` 付きで
`claude -p` を呼び出します。これにより：

- プロンプトキャッシュが効いてコスト・速度が改善
- Claude側に会議の流れが蓄積され、議事録品質が向上
- AIチャットも別セッションで会議文脈を保持

ユーザーが意識する設定は不要で、起動時に自動でUUIDが生成されます。
詳細は [docs/adr/0001-claude-cli-auth-and-billing.md](docs/adr/0001-claude-cli-auth-and-billing.md) を参照。

## コマンドラインオプション

```
使用方法: meeting-transcriber [OPTIONS]

Whisper設定:
  -m, --model {tiny,small,medium,large-v3}  モデルサイズ（default: small）
  -l, --language LANG                        認識言語（default: ja）
  -d, --device ID                            音声入力デバイスID
  --compute-device {auto,cuda,cpu}           計算デバイス（default: auto）

バックエンド:
  -b, --backend {api,claude-agent,claude-cli,local,auto}
                                             LLMバックエンド（default: auto）

バッチ処理:
  --from-file PATH                           既存の文字起こしファイルから議事録を生成

出力:
  -o, --output PATH                          出力ディレクトリ
  -f, --filename FORMAT                      ファイル名フォーマット
  --simple-output PATH                       シンプル出力モード（単一ファイル出力）
  --open-after                               終了後にファイルを開く

テンプレート:
  -t, --template NAME                        テンプレート名

更新設定:
  --auto-update                              自動更新モードを有効化
  --update-interval SEC                      自動更新間隔（秒）
  --version-history                          更新ごとにバージョン保存
  --transcript-only                          文字起こしのみ（議事録を生成しない）

UI:
  --no-tui                                   シンプルモードで実行（TUI無効）
  --web                                      Web UIモードで実行
  --web-host HOST                            Web UIのバインドホスト（default: 127.0.0.1）
  --web-port PORT                            Web UIのポート（default: 8765）
  --no-browser                               Web UIモードでブラウザを自動起動しない

その他:
  --list-devices                             音声デバイス一覧
  --list-templates                           テンプレート一覧
  --show-config                              現在の設定を表示
```

## 設定ファイル

`~/.config/meeting-transcriber/config.yaml` で設定を保存できます。

```yaml
# Whisper設定
model_size: small          # tiny, small, medium, large-v3
language: ja
compute_device: auto       # auto, cuda, cpu
step_duration: 5.0         # ステップ間隔（秒）
window_duration: 15.0      # ウィンドウ長（秒）
# device_id: 0             # 音声入力デバイスID

# LLMバックエンド
backend: auto              # api, claude-agent, claude-cli, auto

# 出力設定
output_dir: ./output
filename_format: meeting_%Y%m%d_%H%M%S
# simple_output_dir: ~/Obsidian/meetings  # シンプルモード用

# テンプレート
template: default          # default, 1on1, brainstorm, standup, client

# 議事録更新設定
auto_update: true          # 自動更新を有効化
update_interval: 120       # 自動更新間隔（秒）
version_history: true      # 更新ごとにバージョン保存
transcript_only: false     # 文字起こしのみ（議事録を生成しない）
```

テンプレートは `~/.config/meeting-transcriber/templates/` に配置されます。

## トラブルシューティング

### CUDAエラー

```
Unable to load libcudnn_ops.so.9
```

→ cuDNNは自動インストールされますが、問題がある場合：

```bash
# 依存関係を再インストール
uv sync --reinstall
```

### マイクが認識されない

```bash
# デバイス一覧を確認
meeting-transcriber --list-devices

# デバイスIDを指定
meeting-transcriber -d 2
```

### Whisperの認識精度が悪い

```bash
# より大きなモデルを使用
meeting-transcriber -m medium  # または large-v3

# GPU使用で高速化
meeting-transcriber -m large-v3 --compute-device cuda
```

## ライセンス

MIT License

## 謝辞

- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) - 高速なWhisper実装
- [Textual](https://github.com/Textualize/textual) - TUIフレームワーク
- [FastAPI](https://fastapi.tiangolo.com/) - Web UIサーバー
- [Anthropic Claude](https://www.anthropic.com/) - 議事録生成AI
