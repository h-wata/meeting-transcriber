"""長文分割・Map-Reduce処理モジュール."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from meeting_transcriber.backends.base import Backend
    from meeting_transcriber.config import TranscriptEntry

# チャンク分割の閾値（文字数）
CHUNK_THRESHOLD = 20000
# 区切り検出用の最大文字数
BOUNDARY_DETECTION_MAX = 30000


BOUNDARY_DETECTION_PROMPT = """以下の会議の文字起こしを読んで、話題が変わる区切り位置を特定してください。

【文字起こし】
{transcript}

【指示】
- 話題や議論テーマが明確に変わる箇所を見つけてください
- 区切り位置は発言のインデックス番号（[HH:MM:SS]の前の番号）で指定してください
- 区切りがない場合は「なし」と回答してください
- 複数ある場合はカンマ区切りで回答してください

【出力形式】
区切り位置のインデックス番号のみを出力してください。例: 5,12,23
区切りがない場合: なし
"""

EXTRACT_POINTS_PROMPT = """以下の会議の文字起こしから要点を抽出してください。

【文字起こし】
{transcript}

【抽出項目】
1. 議論されたトピック・テーマ
2. 重要な発言・意見
3. 決定事項
4. TODO・アクションアイテム
5. 未解決の課題・質問

【出力形式】
箇条書きで簡潔に出力してください。発言者が特定できる場合は記載してください。
"""

MERGE_POINTS_PROMPT = """以下は会議の各パートから抽出した要点です。
これらを統合して、テンプレートに沿った議事録を作成してください。

【テンプレート】
{template}

【抽出された要点】
{points}

【指示】
- 重複する内容は統合してください
- 時系列を意識して整理してください
- 決定事項とTODOは明確に分けてください

【出力】
テンプレートに沿った議事録をMarkdown形式で出力してください。
"""


@dataclass
class Chunk:
    """分割されたチャンク."""

    entries: list[TranscriptEntry]
    start_index: int
    end_index: int

    def to_text(self) -> str:
        """テキストに変換."""
        return '\n'.join(str(e) for e in self.entries)


class ChunkSplitter:
    """話題の区切りで文字起こしを分割するクラス."""

    def __init__(self, backend: Backend) -> None:
        self.backend = backend

    def split(self, transcripts: list[TranscriptEntry]) -> list[Chunk]:
        """文字起こしを話題の区切りで分割する."""
        if not transcripts:
            return []

        total_text = '\n'.join(str(t) for t in transcripts)

        # 閾値以下なら分割不要
        if len(total_text) <= CHUNK_THRESHOLD:
            return [Chunk(entries=transcripts, start_index=0, end_index=len(transcripts) - 1)]

        # 区切り位置を検出
        boundaries = self._detect_boundaries(transcripts)

        # 区切り位置でチャンクを作成
        chunks = []
        start_idx = 0

        for boundary_idx in boundaries:
            if boundary_idx > start_idx:
                chunks.append(
                    Chunk(
                        entries=transcripts[start_idx:boundary_idx],
                        start_index=start_idx,
                        end_index=boundary_idx - 1,
                    )
                )
                start_idx = boundary_idx

        # 残りのエントリ
        if start_idx < len(transcripts):
            chunks.append(
                Chunk(
                    entries=transcripts[start_idx:],
                    start_index=start_idx,
                    end_index=len(transcripts) - 1,
                )
            )

        return chunks if chunks else [Chunk(entries=transcripts, start_index=0, end_index=len(transcripts) - 1)]

    def _detect_boundaries(self, transcripts: list[TranscriptEntry]) -> list[int]:
        """話題の区切り位置を検出する."""
        boundaries = []
        window_start = 0

        while window_start < len(transcripts):
            # ウィンドウ内のエントリを取得
            window_entries = []
            window_text_len = 0

            for i in range(window_start, len(transcripts)):
                entry_text = str(transcripts[i])
                if window_text_len + len(entry_text) > BOUNDARY_DETECTION_MAX:
                    break
                window_entries.append(transcripts[i])
                window_text_len += len(entry_text) + 1

            if not window_entries:
                break

            # ウィンドウが小さすぎる場合はスキップ
            if window_text_len < CHUNK_THRESHOLD:
                break

            # 区切り位置を検出
            window_text = '\n'.join(f'{window_start + i}: {e}' for i, e in enumerate(window_entries))
            prompt = BOUNDARY_DETECTION_PROMPT.format(transcript=window_text)

            try:
                result = self.backend.generate(prompt)
                detected = self._parse_boundaries(result, window_start, window_start + len(window_entries))

                if detected:
                    # 最初の区切りを採用して次のウィンドウへ
                    first_boundary = detected[0]
                    boundaries.append(first_boundary)
                    window_start = first_boundary
                else:
                    # 区切りがなければ強制的に分割
                    mid_point = window_start + len(window_entries) // 2
                    boundaries.append(mid_point)
                    window_start = mid_point
            except Exception:
                # エラー時は強制分割
                mid_point = window_start + len(window_entries) // 2
                boundaries.append(mid_point)
                window_start = mid_point

        return boundaries

    def _parse_boundaries(self, result: str, min_idx: int, max_idx: int) -> list[int]:
        """区切り位置のパース結果を解析する."""
        result = result.strip()

        if result == 'なし' or not result:
            return []

        boundaries = []
        for part in result.replace(' ', '').split(','):
            try:
                idx = int(part)
                if min_idx < idx < max_idx:
                    boundaries.append(idx)
            except ValueError:
                continue

        return sorted(boundaries)


class MapReduceGenerator:
    """Map-Reduce方式で議事録を生成するクラス."""

    def __init__(self, backend: Backend) -> None:
        self.backend = backend
        self.splitter = ChunkSplitter(backend)

    def generate(self, transcripts: list[TranscriptEntry], template_text: str) -> str:
        """Map-Reduce方式で議事録を生成する."""
        # チャンクに分割
        chunks = self.splitter.split(transcripts)

        # 各チャンクから要点を抽出（Map）
        points_list = []
        for i, chunk in enumerate(chunks):
            points = self._extract_points(chunk, i + 1, len(chunks))
            points_list.append(points)

        # 要点を統合して議事録を生成（Reduce）
        return self._merge_points(points_list, template_text)

    def _extract_points(self, chunk: Chunk, chunk_num: int, total_chunks: int) -> str:
        """チャンクから要点を抽出する."""
        prompt = EXTRACT_POINTS_PROMPT.format(transcript=chunk.to_text())

        result = self.backend.generate(prompt)
        return f'## パート {chunk_num}/{total_chunks}\n{result}'

    def _merge_points(self, points_list: list[str], template_text: str) -> str:
        """抽出した要点を統合して議事録を生成する."""
        all_points = '\n\n'.join(points_list)

        prompt = MERGE_POINTS_PROMPT.format(
            template=template_text,
            points=all_points,
        )

        return self.backend.generate(prompt)
