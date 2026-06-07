# 音声入力セットアップガイド

会議録音で「自分の声しか録れない」「Zoom の相手の声が録音されない」問題への対処と、
推奨機材のまとめ。

## 用途別おすすめ構成

| シナリオ                             | おすすめ構成                                 |
| ------------------------------------ | -------------------------------------------- |
| 個人の1on1や少人数                   | PCマイク + `--input zoom_recording.mp4`     |
| 定期チームMTG（対面）                | USB会議マイク + リアルタイム文字起こし       |
| クライアントMTG（要録音）            | Zoom録画 → `--input` でバッチ処理            |
| 重要会議をリアルタイム議論したい     | 会議マイク + ループバック + AIチャット併用   |

**実用的に最もハマりにくいのは「Zoom録画 → `--input`」**です。リアルタイム経路は
構築コストが高い割に、終わってから議事録を吟味する方が落ち着いて確認できます。

## USB会議用マイク（対面会議向け）

| 機材                    | 価格帯  | 特徴                                 |
| ----------------------- | ------- | ------------------------------------ |
| Anker PowerConf S330    | 約$80   | コスパ◎、6人会議室OK                  |
| Jabra Speak 510         | 約$150  | 業務定番、ノイキャン優秀             |
| Yamaha YVC-200          | 約$200  | 音質トップクラス                     |
| Logicool MeetUp         | 約$800  | 映像込み、大会議室向け               |

接続後の手順:

```bash
meeting-transcriber --list-devices    # ID確認
meeting-transcriber -d <ID> --web     # 起動
```

## オンライン会議の相手側音声を録る（ループバック）

オンライン会議で **相手の声を含めて録音** するには OS 側で
「スピーカー出力を入力として扱う」ループバック設定が必要。

### macOS

#### 仮想オーディオデバイス

- [BlackHole](https://existential.audio/blackhole/)（無料）
- [Loopback](https://rogueamoeba.com/loopback/)（約$100、GUI付き）

#### BlackHole + Multi-Output Device 構成

1. BlackHole をインストール（`brew install blackhole-2ch`）
2. **Audio MIDI設定** で `Multi-Output Device` を作成
   - BlackHole 2ch + 内蔵スピーカー を含める
3. システム設定の出力先を `Multi-Output Device` に
4. Zoom などの会議アプリは出力先を変えなくてもシステム経由で BlackHole に流れる
5. `meeting-transcriber --list-devices` で `BlackHole 2ch` の ID を確認
6. `meeting-transcriber -d <BlackHole ID>`

自分の声も同時に録りたい場合: `Aggregate Device` で BlackHole + マイクをまとめる。

### Linux（PulseAudio）

```bash
# pavucontrol（GUI）をインストール
sudo apt install pavucontrol

# モニター入力を有効化（必要な場合）
pacmd load-module module-loopback latency_msec=1
```

1. Zoom などを起動
2. `pavucontrol` を開く → **録音** タブ
3. meeting-transcriber に対して入力ソースを **"Monitor of <出力デバイス名>"** に切り替える

### Linux（PipeWire、Ubuntu 22.04+）

モニター出力はデフォルトで入力として認識可能。

```bash
# 利用可能な monitor を確認
pw-link --output | grep monitor

# meeting-transcriber --list-devices で "Monitor of XXX" として出る
meeting-transcriber --list-devices
```

該当 ID で `-d <ID>` 指定。

GUI が良ければ `pavucontrol` (PulseAudio互換レイヤー経由) でも同じ操作可能。
[Helvum](https://gitlab.freedesktop.org/pipewire/helvum) を使うとノードを GUI で接続できる。

### Windows

#### VB-CABLE（推奨、無料）

1. [VB-CABLE](https://vb-audio.com/Cable/) をインストール
2. Zoom のスピーカー出力を `CABLE Input` に設定
3. `meeting-transcriber --list-devices` で `CABLE Output` の ID を確認
4. `meeting-transcriber -d <CABLE Output ID>`

自分の声も録るなら **VoiceMeeter Banana**（同じくVB-Audio製、無料）で
マイク + CABLE をミックスして1チャンネルにまとめる。

#### Stereo Mix

サウンドカードによっては「ステレオミキサー」が有効化可能:

1. 設定 → サウンド → 入力デバイス を右クリック → **ステレオミキサー** を有効化
2. meeting-transcriber で選択

ドライバ依存で安定しないので VB-CABLE 推奨。

## ハイブリッド会議（対面 + リモート）

USB 会議マイク + ループバックの両方が必要。仮想ミキサーで合成:

- **VoiceMeeter Banana**（Windows、無料）
- **Loopback**（macOS、有料）
- **JACK + qjackctl**（Linux、本格派）

## 録画運用との使い分け

リアルタイム録音にこだわらないなら **録画→バッチ処理** が一番楽:

```bash
# Zoom 録画 (.mp4) から議事録生成
meeting-transcriber --input meeting_recording.mp4 -t client

# Teams 録画 (.mp4) も同じ
meeting-transcriber --input ~/Downloads/Teams\ recording.mp4

# 複数まとめて処理
meeting-transcriber --input ~/zoom-recordings/
```

`ffmpeg` 経由なので動画の音声トラックを自動抽出。途中のスキップや無音区間は
Whisper の VAD フィルタで自動カット。

## トラブルシューティング

| 症状                                | 原因と対処                                                                |
| ----------------------------------- | ------------------------------------------------------------------------- |
| 「マイクが認識されない」            | `--list-devices` で ID 確認 → `-d <ID>` で明示指定                       |
| 「録音はできるが音が小さい」        | OS の入力ゲイン調整、または `pavucontrol` で対象アプリの音量を上げる      |
| 「Zoom の相手の声だけ消える」       | ループバック設定が抜けている（上記OS別手順を参照）                        |
| 「自分の声と相手の声を別チャネルで録りたい」 | 仮想ミキサー（VoiceMeeter / Loopback）で Aggregate Device を作る  |
| 「ハウリングする」                  | ループバック有効時はスピーカー再生先を別経路に（ヘッドホン推奨）          |
| 「ファイルなら確実」                | リアルタイム諦めて `--input` バッチ運用に切り替え                         |
