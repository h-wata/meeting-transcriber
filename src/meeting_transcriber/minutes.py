"""議事録生成モジュール."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
import warnings

from meeting_transcriber.config import TranscriptEntry
from meeting_transcriber.config import UpdateResult
from meeting_transcriber.templates import TemplateManager

if TYPE_CHECKING:
    from meeting_transcriber.backends.base import Backend
    from meeting_transcriber.config import Template

# 文字起こしの最大文字数（約100K tokens相当、それ以上は最新のものを優先）
MAX_TRANSCRIPT_CHARS = 150000

FULL_GENERATION_PROMPT = """あなたは議事録作成アシスタントです。
以下の文字起こしテキストから、構造化された議事録を作成してください。

【ルール】
- 提供されたテンプレートの形式に従う
- 議論の要点を簡潔にまとめる
- 決定事項やTODOを明確に抽出する
- 発言者が特定できる場合は記載する
- 時系列を意識して整理する

【テンプレート】
{template}

【文字起こし】
{transcript}

【出力】
テンプレートに沿った議事録をMarkdown形式で出力してください。
"""

INCREMENTAL_UPDATE_PROMPT = """あなたは議事録作成アシスタントです。
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
"""


class MinutesGenerator:
    """議事録を生成するクラス."""

    def __init__(self, backend: Backend, template_manager: TemplateManager) -> None:
        self.backend = backend
        self.template_manager = template_manager

    def generate_full(
        self,
        transcripts: list[TranscriptEntry],
        template: Template,
        context: dict,
    ) -> str:
        """文字起こし全体から議事録を生成する."""
        transcript_text = '\n'.join(str(t) for t in transcripts)

        # 長すぎる場合は最新のエントリを優先して切り詰め
        if len(transcript_text) > MAX_TRANSCRIPT_CHARS:
            warnings.warn(
                f'文字起こしが長すぎるため切り詰めます（{len(transcript_text)} -> {MAX_TRANSCRIPT_CHARS}文字）',
                stacklevel=2,
            )
            # 最新のエントリから逆順に追加して制限内に収める
            truncated_entries = []
            total_len = 0
            for entry in reversed(transcripts):
                entry_str = str(entry)
                if total_len + len(entry_str) + 1 > MAX_TRANSCRIPT_CHARS:
                    break
                truncated_entries.append(entry_str)
                total_len += len(entry_str) + 1
            transcript_text = '\n'.join(reversed(truncated_entries))

        # transcriptをコンテキストに追加してテンプレートをレンダリング
        render_context = {**context, 'transcript': transcript_text}
        rendered_template = self.template_manager.render(template, render_context)

        prompt = FULL_GENERATION_PROMPT.format(
            template=rendered_template,
            transcript=transcript_text,
        )

        return self.backend.generate(prompt)

    def generate_incremental(
        self,
        current_minutes: str,
        new_transcripts: list[TranscriptEntry],
    ) -> str:
        """差分から議事録を更新する."""
        new_transcript_text = '\n'.join(str(t) for t in new_transcripts)

        prompt = INCREMENTAL_UPDATE_PROMPT.format(
            current_minutes=current_minutes,
            new_transcripts=new_transcript_text,
        )

        return self.backend.generate(prompt)


class MinutesUpdater:
    """議事録の更新状態を管理するクラス."""

    def __init__(
        self,
        generator: MinutesGenerator,
        output_dir: Path,
        template: Template,
        start_time: datetime,
        filename_format: str = 'meeting_%Y%m%d_%H%M%S',
        version_history: bool = False,
        simple_mode: bool = False,
    ) -> None:
        self.generator = generator
        self.output_dir = output_dir
        self.template = template
        self.start_time = start_time
        self.filename_format = filename_format
        self.version_history = version_history
        self.simple_mode = simple_mode

        self.last_update_index = 0
        self.update_count = 0
        self.current_minutes = ''

        # 出力ディレクトリを作成
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # セッションディレクトリ（通常モード）
        if not simple_mode:
            self.session_dir = output_dir / start_time.strftime(filename_format)
            self.session_dir.mkdir(parents=True, exist_ok=True)
            if version_history:
                (self.session_dir / 'history').mkdir(exist_ok=True)

    def update(
        self,
        transcripts: list[TranscriptEntry],
        full: bool = False,
    ) -> UpdateResult:
        """議事録を更新する."""
        if not transcripts:
            return UpdateResult(
                success=False,
                minutes='',
                new_entries_count=0,
                total_entries_count=0,
                update_number=self.update_count,
                error='文字起こしがありません',
            )

        try:
            self.update_count += 1
            context = TemplateManager.get_default_context(
                self.start_time,
                datetime.now(),
                self.update_count,
            )

            if full or self.update_count == 1:
                # フル生成
                self.current_minutes = self.generator.generate_full(
                    transcripts,
                    self.template,
                    context,
                )
                new_entries_count = len(transcripts)
            else:
                # 差分更新
                new_transcripts = self.get_new_transcripts(transcripts)
                if not new_transcripts:
                    self.update_count -= 1
                    return UpdateResult(
                        success=True,
                        minutes=self.current_minutes,
                        new_entries_count=0,
                        total_entries_count=len(transcripts),
                        update_number=self.update_count,
                    )

                self.current_minutes = self.generator.generate_incremental(
                    self.current_minutes,
                    new_transcripts,
                )
                new_entries_count = len(new_transcripts)

            self.last_update_index = len(transcripts)

            # バージョン履歴を保存
            if self.version_history and not self.simple_mode:
                self._save_version()

            return UpdateResult(
                success=True,
                minutes=self.current_minutes,
                new_entries_count=new_entries_count,
                total_entries_count=len(transcripts),
                update_number=self.update_count,
            )

        except Exception as e:
            self.update_count -= 1
            return UpdateResult(
                success=False,
                minutes=self.current_minutes,
                new_entries_count=0,
                total_entries_count=len(transcripts),
                update_number=self.update_count,
                error=str(e),
            )

    def get_new_transcripts(
        self,
        transcripts: list[TranscriptEntry],
    ) -> list[TranscriptEntry]:
        """前回更新以降の新しい文字起こしを取得する."""
        return transcripts[self.last_update_index:]

    def save(self, transcripts: list[TranscriptEntry]) -> Path:
        """議事録と文字起こしを保存する."""
        if self.simple_mode:
            # シンプルモード: 単一ファイル
            filename = self.start_time.strftime(self.filename_format) + '.md'
            minutes_path = self.output_dir / filename
            minutes_path.write_text(self.current_minutes, encoding='utf-8')
            return minutes_path

        # 通常モード: セッションディレクトリ
        minutes_path = self.session_dir / 'minutes.md'
        minutes_path.write_text(self.current_minutes, encoding='utf-8')

        # 最終版を別名で保存
        final_path = self.session_dir / 'minutes_final.md'
        final_path.write_text(self.current_minutes, encoding='utf-8')

        # 生の文字起こしを保存
        transcript_path = self.session_dir / 'transcript_raw.txt'
        transcript_text = '\n'.join(str(t) for t in transcripts)
        transcript_path.write_text(transcript_text, encoding='utf-8')

        return minutes_path

    def save_transcript_only(self, transcripts: list[TranscriptEntry]) -> Path:
        """文字起こしのみを保存する."""
        if self.simple_mode:
            filename = self.start_time.strftime(self.filename_format) + '_transcript.txt'
            path = self.output_dir / filename
        else:
            path = self.session_dir / 'transcript_raw.txt'

        transcript_text = '\n'.join(str(t) for t in transcripts)
        path.write_text(transcript_text, encoding='utf-8')
        return path

    def get_current_minutes(self) -> str:
        """現在の議事録を取得する."""
        return self.current_minutes

    def _save_version(self) -> None:
        """バージョン履歴を保存する."""
        version_path = self.session_dir / 'history' / f'minutes_v{self.update_count:03d}.md'
        version_path.write_text(self.current_minutes, encoding='utf-8')
