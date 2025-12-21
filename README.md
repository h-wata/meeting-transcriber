# Meeting Transcriber

リアルタイム議事録生成ツール。音声をWhisperで文字起こしし、Claudeで議事録を自動生成します。

## 特徴

- リアルタイム音声認識（faster-whisper）
- Claude APIによる議事録自動生成
- TUIインターフェース（Lazygit風の3パネル構成）
- 差分更新による効率的な議事録更新
- 複数のテンプレート対応（デフォルト、1on1、ブレスト、スタンドアップ、クライアント）
- Obsidian連携

## 必要要件

- Python 3.10以上
- マイク入力デバイス
- Claude API Key または Claude Code CLI（Maxプラン）

### GPU使用時（推奨）

- NVIDIA GPU（CUDA対応）
- CUDA 12.x
- cuDNN 9.x（自動インストール）

## インストール

### uvを使用（推奨）

```bash
git clone https://github.com/yourusername/meeting-transcriber.git
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

# 出力先を指定
meeting-transcriber -o ~/Documents/meetings/

# モデルサイズを指定（tiny/small/medium/large-v3）
meeting-transcriber -m medium

# GPU使用
meeting-transcriber --compute-device cuda
```

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

### Obsidian連携

```bash
meeting-transcriber --obsidian-vault ~/Documents/Obsidian/MyVault --obsidian-folder meetings
```

## コマンドラインオプション

```
使用方法: meeting-transcriber [OPTIONS]

Whisper設定:
  -m, --model {tiny,small,medium,large-v3}  モデルサイズ（default: small）
  -l, --language LANG                        認識言語（default: ja）
  -d, --device ID                            音声入力デバイスID
  --compute-device {auto,cuda,cpu}           計算デバイス（default: auto）

バックエンド:
  -b, --backend {api,claude-cli,auto}        LLMバックエンド（default: auto）

出力:
  -o, --output PATH                          出力ディレクトリ
  -f, --filename FORMAT                      ファイル名フォーマット
  --obsidian-vault PATH                      Obsidian Vaultパス
  --obsidian-folder NAME                     Vault内サブフォルダ

テンプレート:
  -t, --template NAME                        テンプレート名

その他:
  --list-devices                             音声デバイス一覧
  --list-templates                           テンプレート一覧
  --show-config                              現在の設定を表示
  --no-tui                                   シンプルモードで実行
```

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
- [Anthropic Claude](https://www.anthropic.com/) - 議事録生成AI
