"""議事録生成モジュール."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from meeting_transcriber.chunking import CHUNK_THRESHOLD, MapReduceGenerator
from meeting_transcriber.config import TranscriptEntry, UpdateResult
from meeting_transcriber.templates import TemplateManager

if TYPE_CHECKING:
    from meeting_transcriber.backends.base import Backend
    from meeting_transcriber.config import Template

# 圧縮モードを適用するしきい値（文字数）
COMPRESS_THRESHOLD = 2000

# 圧縮時に中身を残すセクション（重複防止に必要）
_KEEP_FULL_KEYWORDS = ('決定事項', 'アクションアイテム', 'TODO', 'ネクストアクション', '基本情報', '次回')

# 圧縮時にナラティブセクションで残す最大行数
_COMPRESS_MAX_LINES = 2

# セクションヘッダーの正規表現
_SECTION_RE = re.compile(r'^(#{2,6})\s+(.+)$', re.MULTILINE)

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

SESSION_INCREMENTAL_PROMPT = """新しい発言が追加されました。これまでの議事録に統合した完全版を出力してください。

【ルール】
- 新しい情報を適切なセクションに追加・統合する
- 既存の内容と重複する場合は統合してまとめる
- 議論の流れが分かるように時系列を意識する
- 決定事項やTODOが出たら該当セクションに追加
- 全体の構成・フォーマットは維持する

【新しい発言】
{new_transcripts}

【出力】
更新後の議事録全体をMarkdown形式で出力してください。余計な説明は不要です。
"""

COMPRESSED_UPDATE_PROMPT = """あなたは議事録更新アシスタントです。
議事録の現在の構成を確認し、新しい発言から追加すべき内容だけを出力してください。

【ルール】
- 既存の内容を繰り返さない
- 追加・更新する内容のみをセクションヘッダー付きで出力する
- 新しいトピックがあれば ### ヘッダーで追加する
- 決定事項やTODOがあれば該当セクションに追記する
- 追加すべき内容がない場合は「更新なし」とだけ出力する

【現在の議事録（要約）】
{compressed_minutes}

【新しい発言】
{new_transcripts}

【出力形式】
追加するセクションのヘッダーと内容のみを出力してください。例:

## 議論内容

### 新しいトピック名
- 内容

## 決定事項
- 新しい決定事項
"""


def parse_sections(markdown: str) -> list[tuple[str, str]]:
    """Markdownをセクション(ヘッダー, 本文)のリストに分割する.

    戻り値の各要素は (header, body) のタプル。
    ヘッダー前のテキストは header='' で返す。
    """
    sections: list[tuple[str, str]] = []
    matches = list(_SECTION_RE.finditer(markdown))

    if not matches:
        return [('', markdown)]

    # ヘッダー前のテキスト
    preamble = markdown[: matches[0].start()].rstrip('\n')
    if preamble:
        sections.append(('', preamble))

    for i, match in enumerate(matches):
        header = match.group(0)
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
        body = markdown[start:end].strip('\n')
        sections.append((header, body))

    return sections


def compress_minutes(minutes: str) -> str:
    """議事録を構造的に圧縮する（LLM不要）."""
    sections = parse_sections(minutes)
    compressed_parts: list[str] = []

    for header, body in sections:
        if not header:
            compressed_parts.append(body)
            continue

        # 中身を残すべきセクションはそのまま保持
        if any(kw in header for kw in _KEEP_FULL_KEYWORDS):
            compressed_parts.append(f'{header}\n\n{body}' if body else header)
            continue

        # 空のセクションはそのまま
        content_lines = [line for line in body.split('\n') if line.strip()]
        if len(content_lines) <= _COMPRESS_MAX_LINES:
            compressed_parts.append(f'{header}\n\n{body}' if body else header)
            continue

        # ナラティブセクション: 先頭行 + 件数表示に圧縮
        kept = '\n'.join(content_lines[:_COMPRESS_MAX_LINES])
        omitted = len(content_lines) - _COMPRESS_MAX_LINES
        compressed_parts.append(f'{header}\n\n{kept}\n（他{omitted}件の記載あり）')

    return '\n\n'.join(compressed_parts)


def merge_additions(current_minutes: str, additions: str) -> str:
    """LLM出力（追加分のみ）を現在の議事録にマージする."""
    addition_sections = parse_sections(additions)
    # ヘッダーのないテキストのみの場合はフォールバック
    headers = [h for h, _ in addition_sections if h]
    if not headers:
        return current_minutes

    current_sections = parse_sections(current_minutes)

    # LLM出力の親セクション名を追跡（## X → ### Y の関係で使う）
    current_parent_name: str | None = None

    for add_header, add_body in addition_sections:
        if not add_header:
            continue

        add_level = add_header.count('#')
        add_name = add_header.lstrip('#').strip()

        # ## レベルのセクションは親コンテキストとして記録
        if add_level == 2:
            current_parent_name = add_name
            # 本文が空なら子セクションのコンテキストマーカーなのでスキップ
            if not add_body.strip():
                continue

        if not add_body.strip():
            continue

        inserted = False

        # 既存セクションに一致するか探す
        for i, (cur_header, _cur_body) in enumerate(current_sections):
            if not cur_header:
                continue
            cur_name = cur_header.lstrip('#').strip()
            if cur_name == add_name:
                # 既存セクションの末尾に追記
                current_sections[i] = (cur_header, _cur_body.rstrip('\n') + '\n' + add_body)
                inserted = True
                break

        if inserted:
            continue

        # ### サブセクションの場合、親セクション名で配下に挿入
        if add_level >= 3:
            parent_idx = _find_named_parent(current_sections, current_parent_name, add_level)
            if parent_idx is not None:
                insert_at = _find_section_end(current_sections, parent_idx, add_level - 1)
                current_sections.insert(insert_at, (add_header, add_body))
                inserted = True

        # マッチしない場合はフッター前に追加
        if not inserted:
            footer_idx = _find_footer(current_sections)
            current_sections.insert(footer_idx, (add_header, add_body))

    return _reconstruct(current_sections)


def _find_named_parent(
    sections: list[tuple[str, str]],
    parent_name: str | None,
    child_level: int,
) -> int | None:
    """名前で親セクションを探す。名前がなければレベルで後方検索する."""
    parent_level = child_level - 1
    if parent_name:
        for i, (header, _) in enumerate(sections):
            if header and header.lstrip('#').strip() == parent_name and header.count('#') == parent_level:
                return i
    # フォールバック: レベルで後方検索
    for i in range(len(sections) - 1, -1, -1):
        header = sections[i][0]
        if header and header.count('#') == parent_level:
            return i
    return None


def _find_section_end(
    sections: list[tuple[str, str]],
    parent_idx: int,
    parent_level: int,
) -> int:
    """parent_idx の子セクション群の末尾位置を返す."""
    for i in range(parent_idx + 1, len(sections)):
        header = sections[i][0]
        if header and header.count('#') <= parent_level:
            return i
    return len(sections)


def _find_footer(sections: list[tuple[str, str]]) -> int:
    """フッター行（--- や _この議事録は...）の位置を返す."""
    for i in range(len(sections) - 1, -1, -1):
        header, body = sections[i]
        text = (header + body).strip()
        if text.startswith('---') or text.startswith('_この議事録'):
            return i
    return len(sections)


def _reconstruct(sections: list[tuple[str, str]]) -> str:
    """セクションリストからMarkdownを再構築する."""
    parts: list[str] = []
    for header, body in sections:
        if header and body:
            parts.append(f'{header}\n\n{body}')
        elif header:
            parts.append(header)
        else:
            parts.append(body)
    return '\n\n'.join(parts)


class MinutesGenerator:
    """議事録を生成するクラス."""

    def __init__(self, backend: Backend, template_manager: TemplateManager) -> None:
        self.backend = backend
        self.template_manager = template_manager
        self._map_reduce_generator: MapReduceGenerator | None = None

    @property
    def map_reduce_generator(self) -> MapReduceGenerator:
        """Map-Reduceジェネレーターを遅延初期化."""
        if self._map_reduce_generator is None:
            self._map_reduce_generator = MapReduceGenerator(self.backend)
        return self._map_reduce_generator

    def generate_full(
        self,
        transcripts: list[TranscriptEntry],
        template: Template,
        context: dict,
    ) -> str:
        """文字起こし全体から議事録を生成する."""
        transcript_text = '\n'.join(str(t) for t in transcripts)

        # transcriptをコンテキストに追加してテンプレートをレンダリング
        render_context = {**context, 'transcript': transcript_text}
        rendered_template = self.template_manager.render(template, render_context)

        # 長文の場合はMap-Reduce方式を使用
        if len(transcript_text) > CHUNK_THRESHOLD:
            return self.map_reduce_generator.generate(transcripts, rendered_template)

        # 短い場合は従来方式
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

        # セッション継続モード: Claudeが議事録履歴を覚えているので新規発言のみ送る
        if self.backend.has_persistent_context:
            prompt = SESSION_INCREMENTAL_PROMPT.format(new_transcripts=new_transcript_text)
            try:
                return self.backend.generate(prompt)
            except RuntimeError:
                # セッション枯渇・破損時: 新規UUIDで再生成して非セッションパスにフォールバック
                self.backend.reset_context()

        # 議事録が短い場合は従来方式（全文送信・全文出力）
        if len(current_minutes) <= COMPRESS_THRESHOLD:
            return self._generate_incremental_full(current_minutes, new_transcript_text)

        # 圧縮方式: 骨格のみ送信・追加分のみ出力
        compressed = compress_minutes(current_minutes)
        prompt = COMPRESSED_UPDATE_PROMPT.format(
            compressed_minutes=compressed,
            new_transcripts=new_transcript_text,
        )

        additions = self.backend.generate(prompt)

        if '更新なし' in additions.strip():
            return current_minutes

        return merge_additions(current_minutes, additions)

    def _generate_incremental_full(
        self,
        current_minutes: str,
        new_transcript_text: str,
    ) -> str:
        """従来方式の差分更新（全文送信・全文出力）."""
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
        return transcripts[self.last_update_index :]

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
