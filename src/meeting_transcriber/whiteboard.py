"""ホワイトボードエンジン: 会話からホワイトボード・図・LPを自動生成."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from meeting_transcriber.backends.base import Backend
    from meeting_transcriber.config import TranscriptEntry


@dataclass
class WhiteboardItem:
    """ホワイトボード上のアイテム."""

    id: str
    text: str
    category: str = ''
    color: str = '#fffde7'
    x: int = 0
    y: int = 0


@dataclass
class WhiteboardSection:
    """ホワイトボードのセクション."""

    title: str
    items: list[WhiteboardItem] = field(default_factory=list)
    color: str = '#e3f2fd'


@dataclass
class WhiteboardState:
    """ホワイトボードの全体状態."""

    title: str = ''
    sections: list[WhiteboardSection] = field(default_factory=list)
    diagram: str = ''
    landing_page: str = ''
    summary: str = ''
    transcript_count: int = 0

    def to_dict(self) -> dict:
        """辞書に変換."""
        return {
            'title': self.title,
            'sections': [
                {
                    'title': s.title,
                    'color': s.color,
                    'items': [
                        {
                            'id': item.id,
                            'text': item.text,
                            'category': item.category,
                            'color': item.color,
                        }
                        for item in s.items
                    ],
                }
                for s in self.sections
            ],
            'diagram': self.diagram,
            'landing_page': self.landing_page,
            'summary': self.summary,
            'transcript_count': self.transcript_count,
        }


WHITEBOARD_GENERATION_PROMPT = """あなたは会議のリアルタイムビジュアライゼーションアシスタントです。
会議の文字起こしから、以下の3つのビジュアルを生成してください。

必ず以下のJSON形式で出力してください。他の説明テキストは一切出力しないでください。

```json
{{
  "title": "会議のタイトル（簡潔に）",
  "summary": "議論の概要（2-3文）",
  "sections": [
    {{
      "title": "セクション名",
      "color": "#色コード",
      "items": [
        {{
          "id": "item_1",
          "text": "付箋の内容",
          "category": "アイデア|課題|決定|質問|タスク",
          "color": "#色コード"
        }}
      ]
    }}
  ],
  "diagram": "Mermaid記法の図（graphやmindmap等）",
  "landing_page": "HTMLコード（スタイル付き、完全なセクション）"
}}
```

【カテゴリ別の色指定ルール】
- アイデア: #fffde7（黄色系）
- 課題: #fce4ec（赤系）
- 決定: #e8f5e9（緑系）
- 質問: #e3f2fd（青系）
- タスク: #f3e5f5（紫系）
- セクション色: #e3f2fd, #fff3e0, #e8f5e9, #fce4ec のローテーション

【ホワイトボードのルール】
- 議論のトピックごとにセクションを分ける
- 各アイテムは付箋のように簡潔に（1-2文）
- 関連するアイデアは同じセクションにまとめる
- 最低2つ、最大6つのセクション

【Mermaid図のルール】
- 議論の流れや関係性を図示する
- graph TD（トップダウン）またはmindmapを使用
- ノード名は日本語で簡潔に
- 色やスタイルは使わず、シンプルに
- 必ず有効なMermaid記法であること

【ランディングページのルール】
- 議論内容を元にした製品・サービスのランディングページ
- モダンなデザイン（グラデーション、カード、アイコン）
- レスポンシブ対応のHTML+CSS（インラインスタイル）
- ヒーローセクション、特徴、CTA等を含む
- 議論で出たアイデアや価値提案を反映する
- 完結したHTMLフラグメント（bodyの中身のみ）

【文字起こし】
{transcript}
"""

WHITEBOARD_UPDATE_PROMPT = """あなたは会議のリアルタイムビジュアライゼーションアシスタントです。
既存のホワイトボード状態を、新しい発言内容で更新してください。

必ず以下のJSON形式で出力してください。他の説明テキストは一切出力しないでください。

```json
{{
  "title": "会議のタイトル（更新後）",
  "summary": "議論の概要（更新後、2-3文）",
  "sections": [
    {{
      "title": "セクション名",
      "color": "#色コード",
      "items": [
        {{
          "id": "item_1",
          "text": "付箋の内容",
          "category": "アイデア|課題|決定|質問|タスク",
          "color": "#色コード"
        }}
      ]
    }}
  ],
  "diagram": "Mermaid記法の図（更新後）",
  "landing_page": "HTMLコード（更新後）"
}}
```

【現在のホワイトボード状態】
タイトル: {current_title}
要約: {current_summary}
セクション数: {section_count}
付箋数: {item_count}

【前回更新からの新しい発言】
{new_transcripts}

【ルール】
- 新しい情報を既存のセクションに統合するか、新しいセクションを追加する
- 不要になった項目は削除してよい
- 全体の整合性を保つ
- Mermaid図も最新の議論を反映して更新する
- ランディングページも新しいアイデアを反映する
"""


def _extract_json(text: str) -> dict:
    """LLM出力からJSONを抽出する."""
    # ```json ... ``` ブロックを探す
    json_match = re.search(r'```json\s*\n(.*?)\n```', text, re.DOTALL)
    if json_match:
        text = json_match.group(1)

    # 直接JSONの場合
    text = text.strip()
    if text.startswith('{'):
        # 末尾のゴミを除去
        brace_count = 0
        end_idx = 0
        for i, ch in enumerate(text):
            if ch == '{':
                brace_count += 1
            elif ch == '}':
                brace_count -= 1
                if brace_count == 0:
                    end_idx = i + 1
                    break
        if end_idx > 0:
            text = text[:end_idx]

    return json.loads(text)


class WhiteboardEngine:
    """ホワイトボード生成エンジン."""

    def __init__(self, backend: Backend) -> None:
        self.backend = backend
        self.state = WhiteboardState()
        self.last_update_index = 0

    def generate(self, transcripts: list[TranscriptEntry]) -> WhiteboardState:
        """文字起こし全体からホワイトボードを生成."""
        if not transcripts:
            return self.state

        transcript_text = '\n'.join(str(t) for t in transcripts)

        prompt = WHITEBOARD_GENERATION_PROMPT.format(transcript=transcript_text)
        result = self.backend.generate(prompt)

        self.state = self._parse_result(result)
        self.state.transcript_count = len(transcripts)
        self.last_update_index = len(transcripts)

        return self.state

    def update(
        self,
        transcripts: list[TranscriptEntry],
    ) -> WhiteboardState:
        """新しい発言でホワイトボードを更新."""
        new_transcripts = transcripts[self.last_update_index:]
        if not new_transcripts:
            return self.state

        # 初回は全体生成
        if not self.state.title:
            return self.generate(transcripts)

        new_text = '\n'.join(str(t) for t in new_transcripts)

        # アイテム数を計算
        item_count = sum(len(s.items) for s in self.state.sections)

        prompt = WHITEBOARD_UPDATE_PROMPT.format(
            current_title=self.state.title,
            current_summary=self.state.summary,
            section_count=len(self.state.sections),
            item_count=item_count,
            new_transcripts=new_text,
        )

        result = self.backend.generate(prompt)

        self.state = self._parse_result(result)
        self.state.transcript_count = len(transcripts)
        self.last_update_index = len(transcripts)

        return self.state

    def _parse_result(self, raw: str) -> WhiteboardState:
        """LLMの結果をパースしてWhiteboardStateに変換."""
        try:
            data = _extract_json(raw)
        except (json.JSONDecodeError, ValueError):
            # パース失敗時はフォールバック
            return WhiteboardState(
                title='パースエラー',
                summary=raw[:200],
                sections=[
                    WhiteboardSection(
                        title='生のレスポンス',
                        items=[
                            WhiteboardItem(
                                id='raw_1',
                                text=raw[:500],
                                category='課題',
                                color='#fce4ec',
                            ),
                        ],
                    ),
                ],
            )

        sections = []
        for i, s in enumerate(data.get('sections', [])):
            items = []
            for j, item in enumerate(s.get('items', [])):
                items.append(
                    WhiteboardItem(
                        id=item.get('id', f'item_{i}_{j}'),
                        text=item.get('text', ''),
                        category=item.get('category', ''),
                        color=item.get('color', '#fffde7'),
                    )
                )
            sections.append(
                WhiteboardSection(
                    title=s.get('title', f'セクション{i + 1}'),
                    items=items,
                    color=s.get('color', '#e3f2fd'),
                )
            )

        return WhiteboardState(
            title=data.get('title', ''),
            sections=sections,
            diagram=data.get('diagram', ''),
            landing_page=data.get('landing_page', ''),
            summary=data.get('summary', ''),
        )
