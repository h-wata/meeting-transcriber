"""メインオーケストレーター."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import subprocess
import sys
import threading
import time

from meeting_transcriber.audio import AudioRecorder
from meeting_transcriber.backends import get_backend
from meeting_transcriber.config import Config
from meeting_transcriber.config import TranscriptEntry
from meeting_transcriber.minutes import MinutesGenerator
from meeting_transcriber.minutes import MinutesUpdater
from meeting_transcriber.templates import TemplateManager
from meeting_transcriber.transcriber import Transcriber


class MeetingTranscriber:
    """メインオーケストレータークラス."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.start_time = datetime.now()
        self.transcripts: list[TranscriptEntry] = []
        self.transcript_index = 0
        self._running = False
        self._updating = False
        self._lock = threading.Lock()

        # テンプレートマネージャーの初期化
        self.template_manager = TemplateManager(config.templates_dir)
        self.template_manager.install_builtin_templates()

        # テンプレートの取得
        self.template = self.template_manager.get_template(config.template)
        if not self.template:
            raise RuntimeError(f'テンプレートが見つかりません: {config.template}')

        # バックエンドの初期化
        self.backend = get_backend(config)

        # 各コンポーネントの初期化
        self.recorder = AudioRecorder(
            device_id=config.device_id,
            sample_rate=config.sample_rate,
            step_duration=config.step_duration,
            window_duration=config.window_duration,
        )

        self.transcriber = Transcriber(
            model_size=config.model_size,
            language=config.language,
            device=config.compute_device,
        )

        self.generator = MinutesGenerator(self.backend, self.template_manager)

        output_dir = config.get_output_path()
        self.updater = MinutesUpdater(
            generator=self.generator,
            output_dir=output_dir,
            template=self.template,
            start_time=self.start_time,
            filename_format=config.filename_format,
            version_history=config.version_history,
            obsidian_mode=config.obsidian_vault is not None,
        )

    def run_tui(self) -> None:
        """TUIモードで実行する."""
        from meeting_transcriber.tui import MeetingTranscriberApp

        app = MeetingTranscriberApp(
            config=self.config,
            recorder=self.recorder,
            transcriber=self.transcriber,
            updater=self.updater,
            transcripts=self.transcripts,
            lock=self._lock,
        )
        result = app.run()

        # 終了後に出力先を表示
        if result is not None:
            print(f'\n出力: {result}')

    def _on_audio_chunk(self, _audio) -> None:  # noqa: ANN001
        """音声チャンクを受け取った時のコールバック."""
        # 文字起こしは別スレッドで実行するので、ここでは何もしない
        pass

    def _transcribe_loop(self) -> None:
        """文字起こしループ."""
        while self._running:
            audio = self.recorder.get_audio_chunk(timeout=0.5)
            if audio is None:
                continue

            text = self.transcriber.transcribe(audio)
            if text:
                with self._lock:
                    entry = TranscriptEntry(
                        timestamp=datetime.now(),
                        text=text,
                        index=self.transcript_index,
                    )
                    self.transcripts.append(entry)
                    self.transcript_index += 1

                    if self.config.realtime_display:
                        print(f'\r{entry}')

    def _handle_update(self, full: bool = False) -> None:
        """議事録更新を処理する."""
        if self._updating:
            print('\r更新中です...')
            return

        with self._lock:
            transcripts_copy = list(self.transcripts)

        if not transcripts_copy:
            print('\rまだ文字起こしがありません')
            return

        self._updating = True
        update_type = 'フル更新' if full else '差分更新'
        new_count = len(transcripts_copy) - self.updater.last_update_index

        print(f'\r議事録を{update_type}中... ({self.updater.update_count + 1}回目, 新規: {new_count}件)')

        def update_task() -> None:
            try:
                result = self.updater.update(transcripts_copy, full=full)
                if result.success:
                    elapsed = datetime.now() - self.start_time
                    print(f'\r議事録を更新しました'
                          f' | 新規: {result.new_entries_count}件'
                          f' | 経過: {str(elapsed).split(".")[0]}')
                else:
                    print(f'\r更新に失敗しました: {result.error}')
            finally:
                self._updating = False

        thread = threading.Thread(target=update_task, daemon=True)
        thread.start()

    def _handle_save(self) -> None:
        """文字起こしを保存する."""
        with self._lock:
            transcripts_copy = list(self.transcripts)

        if not transcripts_copy:
            print('\rまだ文字起こしがありません')
            return

        path = self.updater.save_transcript_only(transcripts_copy)
        print(f'\r文字起こしを保存しました: {path}')

    def _handle_pause(self) -> None:
        """一時停止/再開を切り替える."""
        if self.recorder.is_paused():
            self.recorder.resume()
            print('\r録音を再開しました')
        else:
            self.recorder.pause()
            print('\r録音を一時停止しました')

    def handle_key(self, key: str) -> bool:
        """キー入力を処理する。Falseで終了."""
        if key in ('q', 'ctrl+c'):
            return False

        if key in ('u', 'enter'):
            self._handle_update(full=False)
        elif key == 'f':
            self._handle_update(full=True)
        elif key == 's':
            self._handle_save()
        elif key == 'p':
            self._handle_pause()
        elif key == '?':
            self.keyboard.print_help()

        return True

    def _print_header(self) -> None:
        """ヘッダーを表示する."""
        print('\n録音開始...')
        print('-' * 60)
        print('操作: [u/Enter] 更新  [f] フル更新  [s] 保存  [p] 一時停止  [q] 終了  [?] ヘルプ')
        print('-' * 60)

    def run(self) -> None:
        """メインループを実行する."""
        self._running = True

        # 文字起こしスレッドを開始
        transcribe_thread = threading.Thread(target=self._transcribe_loop, daemon=True)
        transcribe_thread.start()

        # 録音を開始
        self.recorder.start(on_chunk=self._on_audio_chunk)
        self._print_header()

        try:
            with self.keyboard.raw_mode():
                while self._running:
                    key = self.keyboard.get_key(timeout=0.1)
                    if key and not self.handle_key(key):
                        break

                    # 自動更新モード
                    if self.config.auto_update:
                        elapsed = (datetime.now() - self.start_time).total_seconds()
                        if elapsed > 0 and int(elapsed) % self.config.update_interval == 0:
                            if not self._updating:
                                self._handle_update(full=False)
                            time.sleep(1)

        except KeyboardInterrupt:
            pass
        finally:
            self._finalize()

    def _finalize(self) -> None:
        """終了処理を行う."""
        print('\n\n終了処理中...')
        self._running = False
        self.recorder.stop()

        with self._lock:
            transcripts_copy = list(self.transcripts)

        if transcripts_copy:
            print('最終議事録を生成中...')

            # 最終更新
            if not self.updater.current_minutes:
                self.updater.update(transcripts_copy, full=True)
            else:
                new_transcripts = self.updater.get_new_transcripts(transcripts_copy)
                if new_transcripts:
                    self.updater.update(transcripts_copy, full=False)

            # 保存
            path = self.updater.save(transcripts_copy)
            print('完了しました')
            print(f'  出力: {path}')

            # ファイルを開く
            if self.config.open_after:
                self._open_file(path)
        else:
            print('文字起こしがありませんでした')

    def _open_file(self, path: Path) -> None:
        """ファイルを開く."""
        try:
            if sys.platform == 'linux':
                subprocess.run(['xdg-open', str(path)], check=False)
            elif sys.platform == 'darwin':
                subprocess.run(['open', str(path)], check=False)
        except Exception:
            pass
