"""Whisperによる文字起こしモジュール."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

import numpy as np
from faster_whisper import WhisperModel

# Whisper が無音や雑音に対して頻繁に幻覚として吐く定型句を弾くための正規表現群。
# 完全一致ではなく「セグメントの全体がほぼこの文だけ」のときだけ弾きたいので
# 前後の句読点・空白・絵文字を許容する形にしている。
# パターン構築用パーツ
_LEAD_JP = r'^[\s。、・！!？?☆★♪♫　]*'  # 行頭の空白・句読点・装飾
_TAIL_JP = r'[\s。、！!？?]*$'  # 行末の空白・句読点
_LEAD_EN = r'^[\s.,!?]*'
_TAIL_EN = r'[\s.,!?]*$'
_THANKS = r'ありがとう(?:ございました|ございます)'
_PROMO_NOUN = r'(?:高評価|いいね|チャンネル登録|フォロー)'
_PROMO_TAIL = r'\s*(?:を)?(?:よろしく)?(?:お願いします|お願い致します|お願いいたします)?'

_HALLUCINATION_PATTERNS = [
    re.compile(p)
    for p in (
        # 日本語: 動画系の定型お礼（ご視聴 / ご清聴）
        _LEAD_JP + r'ご視聴(?:いただき)?' + _THANKS + _TAIL_JP,
        _LEAD_JP + r'ご清聴(?:いただき)?' + _THANKS + _TAIL_JP,
        # 「最後まで(ご)?視聴…ありがとうございました」系
        _LEAD_JP
        + r'最後まで(?:ご)?(?:視聴|見て|お聞き)(?:して)?(?:いただき|くださり|くださって)?'
        + _THANKS
        + _TAIL_JP,
        # 「チャンネル登録（と高評価）（よろしく）お願いします」のバリエーション
        _LEAD_JP + _PROMO_NOUN + rf'(?:[、と・や]+{_PROMO_NOUN})*' + _PROMO_TAIL + _TAIL_JP,
        # 字幕クレジット / ノイズ表示
        _LEAD_JP + r'字幕(?:制作|作成)(?:[:：])?\s*\S+$',
        _LEAD_JP + r'Subtitles? by\s.+$',
        _LEAD_JP + r'\[?(?:音楽|拍手|笑い声|BGM)\]?' + _TAIL_JP,
        # 英語 YouTube 系定型
        _LEAD_EN + r'Thanks? (?:for|to) watching' + _TAIL_EN,
        _LEAD_EN + r'Please (?:subscribe|like and subscribe)' + _TAIL_EN,
        _LEAD_EN + r"Don'?t forget to (?:subscribe|like)" + _TAIL_EN,
    )
]


def _looks_like_hallucination(text: str) -> bool:
    """Whisper の定型ハルシネーションに合致するか判定."""
    if not text:
        return False
    stripped = text.strip()
    return any(p.match(stripped) for p in _HALLUCINATION_PATTERNS)


def _detect_cuda_available() -> bool:
    """CUDAが利用可能かどうかを検出する."""
    # ctranslate2のCUDA対応を確認
    try:
        import ctranslate2

        return 'cuda' in ctranslate2.get_supported_compute_types('cuda')
    except Exception:
        pass

    # torchで確認（インストールされている場合）
    try:
        import torch

        return torch.cuda.is_available()
    except ImportError:
        pass

    return False


class Transcriber:
    """Whisperによる文字起こしを行うクラス."""

    def __init__(
        self,
        model_size: str = 'small',
        language: str = 'ja',
        device: str = 'auto',
    ) -> None:
        self.model_size = model_size
        self.language = language

        # デバイスの自動選択
        if device == 'auto':
            device = 'cuda' if _detect_cuda_available() else 'cpu'

        compute_type = 'float16' if device == 'cuda' else 'int8'

        print(f'Whisperモデルを読み込み中... (model={model_size}, device={device}, compute_type={compute_type})')
        self.model = WhisperModel(model_size, device=device, compute_type=compute_type)
        print('Whisperモデルの読み込み完了')

    def transcribe(self, audio: np.ndarray) -> str:
        """音声データを文字起こしする."""
        # whisper.cppと同等の設定
        # language: None = auto, "ja" = 日本語固定
        lang = None if self.language == 'auto' else self.language

        segments, _ = self.model.transcribe(
            audio,
            language=lang,
            beam_size=5,  # デフォルト5、増やすと精度向上するが遅くなる
            vad_filter=True,
            vad_parameters={
                'threshold': 0.55,  # whisper.cpp: -vth 0.55
                'min_silence_duration_ms': 300,
                'speech_pad_ms': 100,
            },
            # 前のセグメントを context として渡すと「ご視聴ありがとうございました」等のループが
            # 後続セグメントに伝染しやすい。リアルタイム短窓ではオフが安全
            condition_on_previous_text=False,
        )

        texts = []
        for segment in segments:
            text = segment.text.strip()
            if not text:
                continue
            if _looks_like_hallucination(text):
                # 既知の定型ハルシネーション（無音/雑音時に出る「ご視聴ありがとうございました」等）は破棄
                continue
            texts.append(text)

        return ' '.join(texts)

    def transcribe_file(
        self,
        path: Path,
        progress_callback=None,  # noqa: ANN001
    ) -> Iterable[tuple[float, float, str]]:
        """音声/動画ファイル全体を文字起こしする.

        faster-whisper が内部で ffmpeg を呼んでデコードするため、
        WAV/MP3/FLAC/M4A/OGG/MP4/MOV/MKV など ffmpeg がサポートする形式すべてに対応。

        Yields (start_sec, end_sec, text) のタプルを順次返す（長尺ファイルでも省メモリ）。
        progress_callback(start_sec, duration_sec) が指定されていれば各 segment で呼ばれる。
        """
        lang = None if self.language == 'auto' else self.language

        segments, info = self.model.transcribe(
            str(path),
            language=lang,
            beam_size=5,
            vad_filter=True,
            vad_parameters={
                'threshold': 0.55,
                'min_silence_duration_ms': 300,
                'speech_pad_ms': 100,
            },
            condition_on_previous_text=False,
        )

        duration = info.duration

        for segment in segments:
            text = segment.text.strip()
            if not text:
                continue
            if _looks_like_hallucination(text):
                continue
            if progress_callback is not None:
                progress_callback(segment.start, duration)
            yield (segment.start, segment.end, text)
