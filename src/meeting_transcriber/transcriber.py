"""Whisperによる文字起こしモジュール."""

from __future__ import annotations

from faster_whisper import WhisperModel
import numpy as np


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
        )

        texts = []
        for segment in segments:
            text = segment.text.strip()
            if text:
                texts.append(text)

        return ' '.join(texts)
