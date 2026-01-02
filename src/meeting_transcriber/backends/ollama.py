"""Ollamaバックエンド."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from meeting_transcriber.backends.base import Backend


@dataclass
class OllamaConfig:
    """Ollama設定."""

    model: str = 'qwen2.5:32b-instruct-q4_K_M'
    base_url: str = 'http://localhost:11434'
    timeout: int = 300  # 5分

    @classmethod
    def from_dict(cls, data: dict) -> OllamaConfig:
        """辞書からOllamaConfigを作成."""
        config = cls()
        if 'model' in data:
            config.model = data['model']
        if 'base_url' in data:
            config.base_url = data['base_url'].rstrip('/')
        if 'timeout' in data:
            config.timeout = data['timeout']
        return config


class OllamaBackend(Backend):
    """Ollamaバックエンド.

    llama.cppベースの高速ローカルLLM推論。
    GGUF量子化モデルを使用し、効率的なメモリ使用を実現。
    """

    def __init__(self, config: OllamaConfig | None = None) -> None:
        self.config = config or OllamaConfig()

    def generate(self, prompt: str) -> str:
        """プロンプトからテキストを生成する."""
        url = f'{self.config.base_url}/api/generate'

        payload = {
            'model': self.config.model,
            'prompt': self._build_prompt(prompt),
            'stream': False,
            'options': {
                'num_predict': 4096,
                'temperature': 0.7,
                'top_p': 0.9,
            },
        }

        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST',
        )

        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout) as response:
                result = json.loads(response.read().decode('utf-8'))
                return result.get('response', '').strip()
        except urllib.error.URLError as e:
            raise RuntimeError(f'Ollama接続エラー: {e}') from e
        except TimeoutError as e:
            raise RuntimeError(f'Ollamaタイムアウト ({self.config.timeout}秒)') from e

    def _build_prompt(self, prompt: str) -> str:
        """システムプロンプトを含むプロンプトを構築."""
        system = 'あなたは優秀な議事録作成アシスタントです。会議の文字起こしから構造化された議事録を作成します。'
        return f'{system}\n\n{prompt}'

    @staticmethod
    def check_available(base_url: str = 'http://localhost:11434') -> bool:
        """Ollamaサーバーが利用可能か確認する."""
        try:
            request = urllib.request.Request(f'{base_url}/api/tags', method='GET')
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status == 200
        except (urllib.error.URLError, TimeoutError):
            return False

    def list_models(self) -> list[str]:
        """利用可能なモデル一覧を取得."""
        try:
            request = urllib.request.Request(
                f'{self.config.base_url}/api/tags',
                method='GET',
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                result = json.loads(response.read().decode('utf-8'))
                return [m['name'] for m in result.get('models', [])]
        except (urllib.error.URLError, TimeoutError):
            return []
