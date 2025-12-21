"""キーボード入力ハンドラ."""

from __future__ import annotations

from contextlib import contextmanager
import select
import sys
import termios
import tty
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator


class KeyboardHandler:
    """非ブロッキングキー入力を処理するクラス."""

    def __init__(self) -> None:
        self._old_settings = None

    @contextmanager
    def raw_mode(self) -> Generator[None, None, None]:
        """ターミナルをrawモードに設定するコンテキストマネージャ."""
        fd = sys.stdin.fileno()
        self._old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            yield
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, self._old_settings)

    def get_key(self, timeout: float = 0.1) -> str | None:
        """非ブロッキングでキー入力を取得する."""
        if select.select([sys.stdin], [], [], timeout)[0]:
            char = sys.stdin.read(1)
            # Ctrl+C
            if char == '\x03':
                return 'ctrl+c'
            # Enter
            if char in ('\r', '\n'):
                return 'enter'
            return char
        return None

    @staticmethod
    def print_help() -> None:
        """ヘルプを表示する."""
        help_text = """
操作方法:
  u / Enter  : 議事録を更新（差分反映）
  f          : 議事録を全体再生成（フル更新）
  s          : 現在の文字起こしを保存（議事録更新なし）
  p          : 一時停止 / 再開
  q / Ctrl+C : 終了（最終議事録生成）
  ?          : このヘルプを表示
"""
        print(help_text)
