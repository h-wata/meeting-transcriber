# ADR 0004: uvicorn 埋め込み時の Ctrl-C 評価戦略

- **Status**: Accepted
- **Date**: 2026-06-09
- **Supersedes**: なし
- **Related**: [[0003-save-and-reset-session-flow]]

## Context

`meeting-transcriber --web` は `uvicorn.Server` を埋め込みでホストして Web UI を提供している (`src/meeting_transcriber/server.py`)。

これまで Ctrl-C しても `uv run meeting-transcriber --web` のプロセスが落ち切らない事象が頻繁に発生していた。原因を追ったところ複数要因が複合していた：

1. **自前の SIGINT ハンドラが上書きされる**: `server.run()` 内で `signal.signal(SIGINT, _signal_handler)` を設定しても、その直後に呼ぶ `uvicorn.Server.run() → asyncio.run(serve())` の中で `Server.install_signal_handlers()` が SIGINT/SIGTERM を上書きしてしまう。結果、議事録保存などを行う自前の `_shutdown` が呼ばれない。
2. **WebSocket クライアントが残ると graceful shutdown が完了しない**: uvicorn の graceful shutdown は接続中の WS が close するまで待つ。ブラウザタブが開いたままだと永久に待たされる。
3. **transcribe_loop の Whisper 推論で daemon スレッドが詰まる**: daemon=True にしてあるが、faster-whisper の subprocess 経由の cudnn 呼び出しが GIL を解放せずに数秒間ブロックすることがある。

ADR-0003 で「保存してリセット」フローを実装したことで、サーバー自体を落とすのは Ctrl-C 専用に絞られた。だからこそ Ctrl-C は確実に効かないと困る。

## Decision

### 1. `uvicorn.Server` のシグナル登録を抑止するサブクラスを用意する

`server.run()` 内で `_NoSignalServer(uvicorn.Server)` を定義し、`install_signal_handlers()` を no-op で上書きする。これにより自前の `signal.signal(SIGINT, ...)` が生き残る。

```python
class _NoSignalServer(uvicorn.Server):
    def install_signal_handlers(self) -> None:
        return
```

### 2. 1 回目 Ctrl-C は graceful、2 回目で強制終了

自前ハンドラはカウントを持ち：

- **1 回目**: `_shutdown` を別スレッドで起動して議事録保存等を実行。コンソールに `終了処理中... (もう一度 Ctrl-C で強制終了)` を表示
- **2 回目**: `os._exit(130)` で即座に落とす

### 3. 1 回目 Ctrl-C と同時に 8 秒タイムアウトの強制終了スレッドを起動

graceful shutdown が WS 待ちで詰まるケースの保険として、`_force_exit_after_timeout(8.0)` を daemon スレッドで起動しておく。8 秒経っても落ち切らなければ `os._exit(0)`。

ユーザー視点では「Ctrl-C 1 回押せば最大 8 秒以内に必ず落ちる」ことが保証される。

### 4. グローバル `outer = self` バインディングで内部関数からアクセスする

`run()` 内のローカルクラス `_NoSignalServer` と signal handler は WebUIServer のメソッド (`_shutdown`, `_force_exit_after_timeout`) を呼ぶ必要がある。`outer = self` で閉じ込めてアクセスする。型チェッカー視点で「private member access」になるので `# noqa: SLF001` を付ける。

## Consequences

- **良い点**:
  - Ctrl-C で必ず落ちる。連続会議の運用 (ADR-0003) と組み合わせて UX が安定
  - 1 回目で graceful (保存される)、2 回目で即死、というユーザー体験は他の TUI ツール (vim, less 等) と整合的で覚えやすい
  - 8 秒の hard timeout により「WS 接続が残ってて落ちない」事故をユーザーが意識せず済む
  - uvicorn のバージョン更新で `install_signal_handlers` の挙動が変わっても、抑止しているので影響を受けにくい

- **悪い点**:
  - `uvicorn.Server.install_signal_handlers` は public API ではなく内部実装。upstream で名前が変わるとサブクラス側を追従する必要がある
  - 8 秒のタイムアウト中は graceful shutdown 経路 (議事録の保存等) が走るので、保存に 8 秒以上かかる長尺会議では救えない可能性がある（今後 transcribe が肥大化したら閾値見直し）
  - `os._exit` を使うので Python の atexit や finally は走らない。一時ファイルなどは別途明示的に flush する必要がある

## 代替案

### 代替案 A: loop.add_signal_handler を lifespan 内で登録する

- 純正の asyncio 流儀に沿う形だが、`lifespan` イベントは uvicorn の startup よりさらに後で走るので、graceful shutdown 中に SIGINT が来た時の挙動制御が複雑になる。
- → 採用しない

### 代替案 B: uvicorn を別プロセスで起動して subprocess で管理

- 親プロセスが SIGINT を受けたら子の uvicorn に kill を投げる方式
- メリット: シンプル
- デメリット: Whisper モデルや AudioRecorder の共有が面倒。プロセス間 IPC が増える
- → 採用しない (現状の埋め込み構造を維持する方が小さい変更)

### 代替案 C: 何もしない (Ctrl-C で落ちないのを諦める)

- ユーザーが kill コマンドで対処すれば動く
- 通常運用 (毎回会議ごとに起動・終了) では負荷が大きすぎる
- → 採用しない
