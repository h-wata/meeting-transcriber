"""バックエンドの基底クラス."""

from __future__ import annotations

from abc import ABC, abstractmethod


class Backend(ABC):
    """LLMバックエンドの抽象基底クラス."""

    @abstractmethod
    def generate(self, prompt: str) -> str:
        """プロンプトからテキストを生成する."""

    @staticmethod
    @abstractmethod
    def check_available() -> bool:
        """このバックエンドが利用可能かどうかを確認する."""

    @property
    def has_persistent_context(self) -> bool:
        """このバックエンドが会話履歴を保持するか.

        Trueの場合、generator側は議事録履歴を再送せず差分のみ送る短いプロンプトを使える。
        """
        return False

    def reset_context(self) -> None:
        """会話履歴をリセットする（セッション枯渇・破損からの復旧用）.

        デフォルト実装は何もしない。
        """
