"""TUIアプリケーション."""

from __future__ import annotations

from datetime import datetime
import threading
from typing import TYPE_CHECKING

from textual.app import App
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.containers import VerticalScroll
from textual.widgets import Footer
from textual.widgets import Header
from textual.widgets import Input
from textual.widgets import RichLog
from textual.widgets import Static
from textual.worker import get_current_worker

if TYPE_CHECKING:
    from meeting_transcriber.audio import AudioRecorder
    from meeting_transcriber.config import Config
    from meeting_transcriber.minutes import MinutesUpdater
    from meeting_transcriber.transcriber import Transcriber


class LogPanel(RichLog):
    """ログパネル."""

    DEFAULT_CSS = """
    LogPanel {
        height: 6;
        border: solid white;
        background: $surface;
    }
    """


class TranscriptPanel(RichLog):
    """文字起こしパネル."""

    DEFAULT_CSS = """
    TranscriptPanel {
        height: 1fr;
        border: solid white;
        background: $surface;
    }
    """


class MinutesPanel(Static):
    """議事録プレビューパネル."""

    DEFAULT_CSS = """
    MinutesPanel {
        padding: 1;
    }
    """


class StatusBar(Static):
    """ステータスバー."""

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        background: $primary;
        color: $text;
        text-align: center;
    }
    """


class CommandInput(Input):
    """コマンド入力フィールド."""

    DEFAULT_CSS = """
    CommandInput {
        border: solid white;
        background: $surface;
    }
    """


class MeetingTranscriberApp(App):
    """議事録生成TUIアプリケーション."""

    CSS = """
    Screen {
        layout: vertical;
    }

    #main-container {
        height: 1fr;
    }

    #minutes-scroll {
        height: 2fr;
        border: solid white;
        background: $surface;
    }

    .panel-title {
        text-style: bold;
        color: $text;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding('u', 'update_minutes', '差分更新'),
        Binding('f', 'full_update', 'フル更新'),
        Binding('s', 'save', '保存'),
        Binding('p', 'pause', '一時停止/再開'),
        Binding('q', 'quit', '終了'),
        Binding('?', 'help', 'ヘルプ'),
        Binding('c', 'focus_command', 'コマンド'),
    ]

    def __init__(
        self,
        config: 'Config',
        recorder: 'AudioRecorder',
        transcriber: 'Transcriber',
        updater: 'MinutesUpdater',
        transcripts: list,
        lock: threading.Lock,
    ) -> None:
        super().__init__()
        self.config = config
        self.recorder = recorder
        self.transcriber = transcriber
        self.updater = updater
        self.transcripts = transcripts
        self.lock = lock
        self.start_time = datetime.now()
        self.transcript_index = 0
        self._running = True
        self._updating = False

    def compose(self) -> ComposeResult:
        """UIを構成する."""
        yield Header()
        with Vertical(id='main-container'):
            yield Static('[ Log ]', classes='panel-title')
            yield LogPanel(id='log-panel', highlight=True, markup=True, auto_scroll=True)
            yield Static('[ Transcript ]', classes='panel-title')
            yield TranscriptPanel(id='transcript-panel', highlight=True, markup=True, auto_scroll=True)
            yield Static('[ Minutes Preview ]', classes='panel-title')
            with VerticalScroll(id='minutes-scroll'):
                yield MinutesPanel(id='minutes-panel')
            yield Static('[ Claude Command ]', classes='panel-title')
            yield CommandInput(id='command-input', placeholder='議事録への指示を入力...')
        yield StatusBar(id='status-bar')
        yield Footer()

    def on_mount(self) -> None:
        """アプリケーション起動時の処理."""
        self.title = 'Meeting Transcriber'
        self.sub_title = f'Model: {self.config.model_size} | Device: {self.config.compute_device}'

        self.log_message('[green]録音開始...[/green]')
        self.log_message(f'ステップ: {self.config.step_duration}秒 | ウィンドウ: {self.config.window_duration}秒')
        if self.config.auto_update:
            self.log_message(f'[cyan]自動更新: {self.config.update_interval}秒間隔[/cyan]')
        self.update_status('録音中')

        # 録音開始
        self.recorder.start()

        # 文字起こしワーカーを開始（スレッドで実行）
        self.run_worker(self.transcribe_worker, exclusive=True, thread=True)

        # 自動更新タイマーを開始
        if self.config.auto_update:
            self.set_interval(self.config.update_interval, self._auto_update)

    def _auto_update(self) -> None:
        """自動更新を実行する."""
        if self._updating or self.recorder.is_paused():
            return

        with self.lock:
            transcript_count = len(self.transcripts)
            new_count = transcript_count - self.updater.last_update_index

        # 新しい発言がなければスキップ
        if new_count == 0:
            return

        self.log_message(f'[dim]自動更新開始 (新規: {new_count}件)[/dim]')
        self._do_update(full=False)

    def transcribe_worker(self) -> None:
        """文字起こしワーカー（スレッドプールで実行）."""
        worker = get_current_worker()

        while self._running and not worker.is_cancelled:
            audio = self.recorder.get_audio_chunk(timeout=0.5)
            if audio is None:
                continue

            text = self.transcriber.transcribe(audio)
            if text:
                timestamp = datetime.now()

                # TranscriptEntryを作成
                from meeting_transcriber.config import TranscriptEntry

                entry = TranscriptEntry(
                    timestamp=timestamp,
                    text=text,
                    index=self.transcript_index,
                )

                with self.lock:
                    self.transcripts.append(entry)
                    self.transcript_index += 1

                # UIを更新
                self.call_from_thread(self.add_transcript, str(entry))

    def add_transcript(self, text: str) -> None:
        """文字起こしを追加する."""
        panel = self.query_one('#transcript-panel', TranscriptPanel)
        panel.write(text)

    def log_message(self, message: str) -> None:
        """ログメッセージを追加する."""
        panel = self.query_one('#log-panel', LogPanel)
        timestamp = datetime.now().strftime('%H:%M:%S')
        panel.write(f'[dim]{timestamp}[/dim] {message}')
        panel.refresh()

    def update_status(self, status: str) -> None:
        """ステータスバーを更新する."""
        elapsed = datetime.now() - self.start_time
        elapsed_str = str(elapsed).split('.')[0]

        with self.lock:
            transcript_count = len(self.transcripts)

        bar = self.query_one('#status-bar', StatusBar)
        update_count = self.updater.update_count
        bar.update(f'{status} | 経過: {elapsed_str} | 発言: {transcript_count}件 | 更新: {update_count}回')

    def update_minutes_preview(self) -> None:
        """議事録プレビューを更新する."""
        panel = self.query_one('#minutes-panel', MinutesPanel)
        minutes = self.updater.get_current_minutes()
        if minutes:
            # Markdownを簡易表示
            panel.update(minutes[:2000] + ('...' if len(minutes) > 2000 else ''))
        else:
            panel.update('[dim]議事録はまだ生成されていません。[u]キーで更新してください。[/dim]')

    def action_update_minutes(self) -> None:
        """議事録を差分更新する."""
        self._do_update(full=False)

    def action_full_update(self) -> None:
        """議事録をフル更新する."""
        self._do_update(full=True)

    def _do_update(self, full: bool = False) -> None:
        """議事録を更新する."""
        if self._updating:
            self.log_message('[yellow]更新中です...[/yellow]')
            return

        with self.lock:
            transcripts_copy = list(self.transcripts)

        if not transcripts_copy:
            self.log_message('[yellow]まだ文字起こしがありません[/yellow]')
            return

        self._updating = True
        update_type = 'フル更新' if full else '差分更新'
        new_count = len(transcripts_copy) - self.updater.last_update_index

        self.log_message(f'[cyan]{update_type}中... ({self.updater.update_count + 1}回目, 新規: {new_count}件)[/cyan]')
        self.update_status(f'{update_type}中...')

        # バックグラウンドで更新（スレッドで実行）
        self.run_worker(lambda: self._update_task(transcripts_copy, full), exclusive=False, thread=True)

    def _update_task(self, transcripts: list, full: bool) -> None:
        """更新タスク（スレッドプールで実行）."""
        try:
            result = self.updater.update(transcripts, full=full)
            if result.success:
                count = result.new_entries_count
                self.call_from_thread(self.log_message, f'[green]更新完了 | 新規: {count}件[/green]')
                self.call_from_thread(self.update_minutes_preview)
            else:
                self.call_from_thread(self.log_message, f'[red]更新失敗: {result.error}[/red]')
        finally:
            self._updating = False
            self.call_from_thread(self.update_status, '録音中')

    def action_save(self) -> None:
        """文字起こしを保存する."""
        with self.lock:
            transcripts_copy = list(self.transcripts)

        if not transcripts_copy:
            self.log_message('[yellow]まだ文字起こしがありません[/yellow]')
            return

        try:
            path = self.updater.save_transcript_only(transcripts_copy)
            self.log_message(f'[green]保存しました: {path}[/green]')
        except Exception as e:
            self.log_message(f'[red]保存エラー: {e}[/red]')

    def action_pause(self) -> None:
        """一時停止/再開を切り替える."""
        if self.recorder.is_paused():
            self.recorder.resume()
            self.log_message('[green]録音を再開しました[/green]')
            self.update_status('録音中')
        else:
            self.recorder.pause()
            self.log_message('[yellow]録音を一時停止しました[/yellow]')
            self.update_status('一時停止中')

    def action_help(self) -> None:
        """ヘルプを表示する."""
        self.log_message('[dim]─[/dim]' * 30)
        self.log_message('[bold]操作方法:[/bold]')
        self.log_message('  [cyan]u[/cyan] 差分更新  [cyan]f[/cyan] フル更新  [cyan]s[/cyan] 保存')
        self.log_message('  [cyan]p[/cyan] 一時停止  [cyan]c[/cyan] コマンド入力  [cyan]q[/cyan] 終了')
        self.log_message('[dim]─[/dim]' * 30)

    def action_focus_command(self) -> None:
        """コマンド入力欄にフォーカスする."""
        self.query_one('#command-input', CommandInput).focus()

    def action_quit(self) -> None:
        """アプリケーションを終了する."""
        self._running = False

        # 録音停止
        self.recorder.stop()

        with self.lock:
            transcripts_copy = list(self.transcripts)

        output_path = None
        if transcripts_copy:
            # 最終更新
            if not self.updater.current_minutes:
                self.updater.update(transcripts_copy, full=True)
            else:
                new_transcripts = self.updater.get_new_transcripts(transcripts_copy)
                if new_transcripts:
                    self.updater.update(transcripts_copy, full=False)

            # 保存
            output_path = self.updater.save(transcripts_copy)

        # 終了（出力パスを返す）
        self.exit(output_path)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """コマンド入力が送信されたときの処理."""
        if event.input.id != 'command-input':
            return

        command = event.value.strip()
        if not command:
            return

        # 入力欄をクリア
        event.input.value = ''

        # 議事録がなければエラー
        if not self.updater.current_minutes:
            self.log_message('[yellow]議事録がまだ生成されていません。先に[u]キーで更新してください。[/yellow]')
            return

        # 更新中なら待つ
        if self._updating:
            self.log_message('[yellow]更新中です。完了をお待ちください。[/yellow]')
            return

        self._updating = True
        self.log_message(f'[magenta]指示を送信中: {command}[/magenta]')
        self.update_status('Claude処理中...')

        # バックグラウンドで処理
        self.run_worker(lambda: self._send_to_claude(command), exclusive=False, thread=True)

    def _send_to_claude(self, instruction: str) -> None:
        """Claudeに指示を送信して議事録を修正する."""
        prompt = f"""あなたは議事録修正アシスタントです。
ユーザーの指示に従って議事録を修正してください。

【ユーザーの指示】
{instruction}

【現在の議事録】
{self.updater.current_minutes}

【出力】
修正後の議事録全体をMarkdown形式で出力してください。余計な説明は不要です。"""

        try:
            # バックエンドで生成
            result = self.updater.generator.backend.generate(prompt)

            # 結果を反映
            self.updater.current_minutes = result
            self.call_from_thread(self.update_minutes_preview)
            self.call_from_thread(self.log_message, '[green]議事録を修正しました[/green]')
        except Exception as e:
            self.call_from_thread(self.log_message, f'[red]エラー: {e}[/red]')
        finally:
            self._updating = False
            self.call_from_thread(self.update_status, '録音中')
