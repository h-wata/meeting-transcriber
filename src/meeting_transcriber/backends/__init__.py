"""LLMバックエンドモジュール."""

from meeting_transcriber.backends.base import Backend
from meeting_transcriber.backends.factory import get_backend

__all__ = ['Backend', 'get_backend']
