"""テンプレート管理モジュール."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re

from meeting_transcriber.config import Template
from meeting_transcriber.config import TemplateInfo
import yaml

BUILTIN_TEMPLATES = {
    'default': """---
name: "汎用議事録"
description: "標準的な議事録フォーマット"
tags:
  - meeting
  - auto-generated
---

# 議事録 - {{date}}

## 基本情報

- **日時**: {{date}} {{time}} - {{end_time}}
- **所要時間**: {{duration}}
- **参加者**: （音声から推測、または「不明」）

## 議題・アジェンダ

-

## 議論内容

### トピック1

-

## 決定事項

- [ ]

## アクションアイテム

| 担当 | タスク | 期限 |
| ---- | ------ | ---- |
|      |        |      |

## 次回予定

-

---

_この議事録はAIによって自動生成されました（{{update_count}}回更新）_
""",
    '1on1': """---
name: "1on1ミーティング"
description: "1対1の定期ミーティング用"
tags:
  - meeting
  - 1on1
---

# 1on1 議事録 - {{date}}

## 基本情報

- **日時**: {{date}} {{time}}
- **参加者**:

## 前回からの進捗

-

## 今回の議題

### 業務について

-

### キャリア・成長について

-

### 困っていること・相談

-

## ネクストアクション

| 担当 | アクション | 期限 |
| ---- | ---------- | ---- |
|      |            |      |

## 次回までの目標

-

---

_自動生成: {{datetime}}_
""",
    'brainstorm': """---
name: "ブレインストーミング"
description: "アイデア出し・ブレスト用"
tags:
  - meeting
  - brainstorm
---

# ブレインストーミング - {{date}}

## テーマ

-

## 参加者

-

## アイデア一覧

### カテゴリ1

-

### カテゴリ2

-

### その他

-

## 有望なアイデア

-

## 次のアクション

-

---

_自動生成: {{datetime}}_
""",
    'standup': """---
name: "スタンドアップ"
description: "朝会・デイリースタンドアップ用"
tags:
  - meeting
  - standup
  - daily
---

# デイリースタンドアップ - {{date}}

## 参加者

-

## 報告

### 昨日やったこと

-

### 今日やること

-

### 困っていること・ブロッカー

-

## メモ

-

---

_自動生成: {{datetime}}_
""",
    'client': """---
name: "顧客打ち合わせ"
description: "顧客・クライアントとの打ち合わせ用"
tags:
  - meeting
  - client
  - external
---

# 打ち合わせ議事録 - {{date}}

## 基本情報

- **日時**: {{date}} {{time}} - {{end_time}}
- **場所**:
- **参加者**:
  - 先方:
  - 自社:

## 議題

1.

## 議論内容

### 議題1

-

## 合意事項

-

## 懸念事項・課題

-

## アクションアイテム

| 担当 | 内容 | 期限 |
| ---- | ---- | ---- |
|      |      |      |

## 次回予定

- 日時:
- 議題:

---

_この議事録はAIによって自動生成されました_
""",
}


class TemplateManager:
    """テンプレートの管理を行うクラス."""

    def __init__(self, templates_dir: Path) -> None:
        self.templates_dir = templates_dir

    def install_builtin_templates(self) -> None:
        """ビルトインテンプレートをインストールする."""
        self.templates_dir.mkdir(parents=True, exist_ok=True)

        for name, content in BUILTIN_TEMPLATES.items():
            template_path = self.templates_dir / f'{name}.md'
            if not template_path.exists():
                template_path.write_text(content, encoding='utf-8')
                print(f'テンプレートをインストール: {name}')

    def list_templates(self) -> list[TemplateInfo]:
        """利用可能なテンプレート一覧を取得する."""
        templates = []

        # ビルトインテンプレートを確認
        for name in BUILTIN_TEMPLATES:
            template = self.get_template(name)
            if template:
                templates.append(template.info)

        # カスタムテンプレートを確認
        if self.templates_dir.exists():
            for path in self.templates_dir.glob('*.md'):
                name = path.stem
                if name not in BUILTIN_TEMPLATES:
                    template = self.get_template(name)
                    if template:
                        templates.append(template.info)

        return templates

    def get_template(self, name: str) -> Template | None:
        """テンプレートを取得する."""
        # ファイルから読み込み
        template_path = self.templates_dir / f'{name}.md'
        if template_path.exists():
            content = template_path.read_text(encoding='utf-8')
        elif name in BUILTIN_TEMPLATES:
            content = BUILTIN_TEMPLATES[name]
        else:
            return None

        # フロントマターをパース
        info, template_content = self._parse_template(name, content)
        return Template(info=info, content=template_content)

    def _parse_template(self, name: str, content: str) -> tuple[TemplateInfo, str]:
        """テンプレートのフロントマターをパースする."""
        # YAMLフロントマターを抽出
        pattern = r'^---\s*\n(.*?)\n---\s*\n(.*)$'
        match = re.match(pattern, content, re.DOTALL)

        if match:
            frontmatter = yaml.safe_load(match.group(1)) or {}
            template_content = match.group(2)
        else:
            frontmatter = {}
            template_content = content

        info = TemplateInfo(
            name=name,
            display_name=frontmatter.get('name', name),
            description=frontmatter.get('description', ''),
            tags=frontmatter.get('tags', []),
        )

        return info, template_content

    def render(self, template: Template, context: dict) -> str:
        """テンプレートをレンダリングする."""
        content = template.content

        # プレースホルダーを置換
        for key, value in context.items():
            placeholder = '{{' + key + '}}'
            content = content.replace(placeholder, str(value))

        return content

    @staticmethod
    def get_default_context(
        start_time: datetime,
        end_time: datetime | None = None,
        update_count: int = 0,
    ) -> dict:
        """デフォルトのコンテキストを取得する."""
        if end_time is None:
            end_time = datetime.now()

        duration = end_time - start_time
        hours, remainder = divmod(int(duration.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)

        return {
            'date': start_time.strftime('%Y-%m-%d'),
            'time': start_time.strftime('%H:%M'),
            'end_time': end_time.strftime('%H:%M'),
            'datetime': start_time.strftime('%Y-%m-%d %H:%M:%S'),
            'duration': f'{hours:02d}:{minutes:02d}:{seconds:02d}',
            'update_count': update_count,
        }
