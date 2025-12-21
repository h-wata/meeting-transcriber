"""バックエンドの基底クラス."""

from __future__ import annotations

from abc import ABC
from abc import abstractmethod


class Backend(ABC):
    """LLMバックエンドの抽象基底クラス."""

    @abstractmethod
    def generate(self, prompt: str) -> str:
        """プロンプトからテキストを生成する."""

    @staticmethod
    @abstractmethod
    def check_available() -> bool:
        """このバックエンドが利用可能かどうかを確認する."""
