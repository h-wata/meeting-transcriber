"""設定とデータクラス."""

from __future__ import annotations

from dataclasses import dataclass, field
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
class LocalLLMConfig:
    """OpenAI互換APIバックエンド設定（ローカル & cloud両対応）.

    ローカル例: LM Studio / Ollama / vLLM (api_key 不要)
    cloud例: Groq / OpenRouter / DeepSeek / Together AI (api_key_env で設定)
    """

    base_url: str = 'http://localhost:1234/v1'  # LM Studioデフォルト
    model: str = ''  # 空の場合は自動検出
    max_tokens: int = 8192
    temperature: float = 0.3
    system_prompt: str = ''  # 追加のシステムプロンプト
    api_key_env: str = ''  # API key を取得する環境変数名（例: 'GROQ_API_KEY'）
    api_key: str = ''  # API key 直接指定（非推奨、api_key_env を優先）

    def resolve_api_key(self) -> str | None:
        """環境変数または直接指定から実際の API key を取得する."""
        import os

        if self.api_key_env:
            value = os.environ.get(self.api_key_env)
            if value:
                return value
        if self.api_key:
            return self.api_key
        return None

    def is_cloud(self) -> bool:
        """Cloud OpenAI 互換エンドポイントか（api_key 設定があれば cloud とみなす）."""
        return bool(self.api_key_env or self.api_key)

    @classmethod
    def from_dict(cls, data: dict) -> LocalLLMConfig:
        """辞書からLocalLLMConfigを作成."""
        return cls(
            base_url=data.get('base_url', 'http://localhost:1234/v1'),
            model=data.get('model', ''),
            max_tokens=data.get('max_tokens', 8192),
            temperature=data.get('temperature', 0.3),
            system_prompt=data.get('system_prompt', ''),
            api_key_env=data.get('api_key_env', ''),
            api_key=data.get('api_key', ''),
        )


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
    backend: str = 'auto'  # auto, api, claude-agent, claude-cli, local
    local_llm: LocalLLMConfig = field(default_factory=LocalLLMConfig)

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
    version_history: bool = True
    transcript_only: bool = False  # 文字起こしのみ（議事録を生成しない）

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

        # ローカルLLM設定の変換
        if 'local_llm' in data and isinstance(data['local_llm'], dict):
            data['local_llm'] = LocalLLMConfig.from_dict(data['local_llm'])

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
            'local_llm': self.local_llm,
            'output_dir': self.output_dir,
            'filename_format': self.filename_format,
            'simple_output_dir': self.simple_output_dir,
            'open_after': self.open_after,
            'template': self.template,
            'templates_dir': self.templates_dir,
            'auto_update': self.auto_update,
            'update_interval': self.update_interval,
            'version_history': self.version_history,
            'transcript_only': self.transcript_only,
        }
        for key, value in kwargs.items():
            if value is not None:
                data[key] = value
        return Config(**data)
