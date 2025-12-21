"""設定とデータクラス."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from pathlib import Path

import yaml


@dataclass
class TranscriptEntry:
    """文字起こしエントリ."""

    timestamp: datetime
    text: str
    index: int

    def __str__(self) -> str:
        return f'[{self.timestamp.strftime("%H:%M:%S")}] {self.text}'


@dataclass
class TemplateInfo:
    """テンプレートのメタ情報."""

    name: str
    display_name: str
    description: str
    tags: list[str] = field(default_factory=list)


@dataclass
class Template:
    """テンプレート本体."""

    info: TemplateInfo
    content: str
    prompt_hint: str = ''


@dataclass
class UpdateResult:
    """更新結果."""

    success: bool
    minutes: str
    new_entries_count: int
    total_entries_count: int
    update_number: int
    error: str | None = None


@dataclass
class Config:
    """アプリケーション設定."""

    # Whisper設定
    model_size: str = 'small'
    language: str = 'ja'
    compute_device: str = 'auto'  # auto, cuda, cpu
    step_duration: float = 5.0  # ステップ間隔（秒）whisper.cpp: --step 5000
    window_duration: float = 15.0  # ウィンドウ長（秒）whisper.cpp: --length 15000
    sample_rate: int = 16000
    device_id: int | None = None
    realtime_display: bool = True

    # LLMバックエンド設定
    backend: str = 'auto'

    # 出力設定
    output_dir: Path = field(default_factory=lambda: Path('./output'))
    filename_format: str = 'meeting_%Y%m%d_%H%M%S'
    simple_output_dir: Path | None = None
    open_after: bool = False

    # テンプレート設定
    template: str = 'default'
    templates_dir: Path = field(default_factory=lambda: Path('~/.config/meeting-transcriber/templates').expanduser())

    # 議事録更新設定
    auto_update: bool = False
    update_interval: int = 120
    version_history: bool = False

    def get_output_path(self) -> Path:
        """実際の出力先パスを取得."""
        if self.simple_output_dir:
            return self.simple_output_dir
        return self.output_dir

    def get_template_path(self) -> Path:
        """テンプレートファイルのパスを取得."""
        return self.templates_dir / f'{self.template}.md'

    @classmethod
    def from_file(cls, path: Path) -> Config:
        """設定ファイルからConfigを読み込む."""
        if not path.exists():
            return cls()

        with open(path, encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}

        # パスの展開
        if 'output_dir' in data:
            data['output_dir'] = Path(data['output_dir']).expanduser()
        if 'simple_output_dir' in data and data['simple_output_dir']:
            data['simple_output_dir'] = Path(data['simple_output_dir']).expanduser()
        if 'templates_dir' in data:
            data['templates_dir'] = Path(data['templates_dir']).expanduser()

        return cls(**data)

    @classmethod
    def get_default_config_path(cls) -> Path:
        """デフォルトの設定ファイルパスを取得."""
        return Path('~/.config/meeting-transcriber/config.yaml').expanduser()

    @classmethod
    def load_default(cls) -> Config:
        """デフォルトパスから設定を読み込む."""
        config_path = cls.get_default_config_path()
        return cls.from_file(config_path)

    def merge_args(self, **kwargs) -> Config:
        """コマンドライン引数をマージした新しいConfigを返す."""
        data = {
            'model_size': self.model_size,
            'language': self.language,
            'compute_device': self.compute_device,
            'step_duration': self.step_duration,
            'window_duration': self.window_duration,
            'sample_rate': self.sample_rate,
            'device_id': self.device_id,
            'realtime_display': self.realtime_display,
            'backend': self.backend,
            'output_dir': self.output_dir,
            'filename_format': self.filename_format,
            'simple_output_dir': self.simple_output_dir,
            'open_after': self.open_after,
            'template': self.template,
            'templates_dir': self.templates_dir,
            'auto_update': self.auto_update,
            'update_interval': self.update_interval,
            'version_history': self.version_history,
        }
        for key, value in kwargs.items():
            if value is not None:
                data[key] = value
        return Config(**data)
