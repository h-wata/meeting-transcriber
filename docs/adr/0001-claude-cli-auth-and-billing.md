# ADR-0001: Claude CLI バックエンドの認証戦略と 2026/6/15 課金変更への対応

- ステータス: Accepted
- 日付: 2026-06-07
- 関連 Issue: #4, #5

## コンテキスト

本プロジェクトは Claude Code CLI (`claude -p`) を `subprocess` 経由で呼び出して議事録生成のバックエンドとして使用している (`src/meeting_transcriber/backends/claude_cli.py`)。

ユーザーは Anthropic の Claude Max プランを契約しており、API 従量課金ではなくサブスクリプション枠で運用したい。実装では `ANTHROPIC_API_KEY` を環境変数から除去してから `claude -p` を呼ぶことで、Claude Code が OAuth/keychain にフォールバックして Max プランとして認証する設計になっている。

2026 年に入ってから Anthropic 側で以下の変更があった：

- **2026-02**: Consumer Terms 改定。OAuth トークンは Claude Code と claude.ai 専用と明記。`claude` バイナリ経由なら従来通り利用可。OAuth トークンを抜き出して別ツールから直接 API を叩くのは違反。
- **2026-05-06**: Claude Code の 5 時間窓上限が 2 倍化、Pro/Max のピーク時間スロットル撤廃。
- **2026-06-15**: **`claude -p` / Agent SDK の利用が Max プラン本体枠（chat.claude.ai 共有枠）から分離され、新設の「Agent SDK クレジット」枠を消費する仕様に変更。**
  - Max 5x: 月 $100 分（API レート換算）
  - Max 20x: 月 $200 分
  - 個人アカウント単位、プール／共有／繰越不可、毎月リセット
  - クレジット枯渇後は `usage credits`（従量課金）が有効なら API レートで継続、未有効なら失敗
- **`--bare` フラグの罠**: `claude -p --bare` は OAuth/keychain 読み取りをスキップし、`ANTHROPIC_API_KEY` か `apiKeyHelper` 経由でしか認証できない。今後 `-p` のデフォルトが `--bare` 化する予定との記述が公式ドキュメントにある。

## 決定

### 1. 認証経路は OAuth フォールバックを継続採用

`ClaudeCLIBackend.generate()` で `ANTHROPIC_API_KEY` を環境変数から除去してから `claude -p` を呼ぶ実装を維持する。これにより：

- Max プラン契約者は OAuth/keychain 認証で Agent SDK クレジット枠を消費
- API キー契約者向けには別バックエンド (`api`, `claude-agent`) が既に存在するので影響なし

### 2. `--bare` は使わない

将来 `claude -p` のデフォルトが `--bare` 化された場合、明示的に OAuth 認証を要求するフラグ（あるいは環境変数）が必要になる可能性がある。CI のリリースノートをウォッチし、必要なら対応する。

### 3. 規約遵守の境界

- `claude` バイナリ経由の subprocess 呼び出しは Anthropic 公認 → 現実装は規約上問題なし
- OAuth トークンを keychain から取り出して別プロセスから直接 Anthropic API を叩く構造には**しない**
- 自動化頻度は常識的範囲（会議数分/日）に抑える

### 4. クレジット消費の可視化（別 Issue で実装）

6/15 以降の運用では Max プラン本体枠とは別の Agent SDK クレジットを消費するため、消費量を可視化する仕組みを追加する。具体的には：

- `claude -p` を `--output-format json` で呼び、レスポンスから `total_cost_usd` を取得
- セッション中・終了時に累計消費額をログ／UI に表示
- 月間集計はユーザーが Anthropic ダッシュボードで確認する想定（プロジェクト側では累計のみ提供）

### 5. セッション継続 (`--session-id`) は別 ADR で扱う

`--session-id` を使ったコンテキスト継続化は Issue #4 で扱う独立した改善。Max プランでの利用に規約上の問題はない。

## 影響

- **現状コード**: `backends/claude_cli.py` の `ANTHROPIC_API_KEY` 除去ロジックを維持。コメントを更新して「OAuth/keychain にフォールバックさせるための意図的な削除」であることを明記する。
- **新規実装**: `--output-format json` への変更と `total_cost_usd` ログ出力（Issue #5）。
- **監視義務**: Anthropic 公式ドキュメントとリリースノートを定期確認する運用責任が発生する。特に `--bare` のデフォルト化と Agent SDK クレジットの料金改定。

## 代替案

### 代替案 A: API 従量課金に切り替える
- メリット: 規約変更の影響を受けない、コスト予測が容易
- デメリット: Max プラン契約者の意図に反する。月額固定の利点を捨てることになる
- → 採用しない

### 代替案 B: `claude-agent` SDK バックエンドを主に使う
- メリット: 公式の Agent SDK 経由なのでサポート手厚い
- デメリット: 6/15 以降は同じく Agent SDK クレジット枠を消費する。subprocess より複雑
- → 補助的に維持（既存実装あり）。デフォルトは `claude-cli` のまま

### 代替案 C: ローカル LLM (`local` バックエンド) をデフォルトに
- メリット: 完全に課金から切り離せる
- デメリット: 議事録品質が大きく落ちる。GPU 必須
- → 補助的に維持（既存実装あり）

## 参考

- [Run Claude Code programmatically — 公式](https://code.claude.com/docs/en/headless)
- [Use the Claude Agent SDK with your Claude plan — 公式サポート](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan)
- [Use Claude Code with your Pro or Max plan — 公式サポート](https://support.claude.com/en/articles/11145838-use-claude-code-with-your-pro-or-max-plan)
- [Authentication — 公式](https://code.claude.com/docs/en/authentication)
- [Anthropic Acceptable Use Policy](https://www.anthropic.com/legal/aup)
