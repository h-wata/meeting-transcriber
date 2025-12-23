"""音声入力モジュール."""

from __future__ import annotations

import queue
import threading
from typing import TYPE_CHECKING

import numpy as np
import sounddevice as sd

if TYPE_CHECKING:
    from collections.abc import Callable


class AudioRecorder:
    """音声入力を管理するクラス."""

    def __init__(
        self,
        device_id: int | None = None,
        sample_rate: int = 16000,
        step_duration: float = 5.0,  # ステップ間隔（秒）
        window_duration: float = 15.0,  # ウィンドウ長（秒）
    ) -> None:
        self.device_id = device_id
        self.sample_rate = sample_rate
        self.step_duration = step_duration
        self.window_duration = window_duration
        self.step_samples = int(sample_rate * step_duration)
        self.window_samples = int(sample_rate * window_duration)

        # maxsize=10 で約50秒分（5秒ステップ × 10）を保持、それ以上は古いチャンクを破棄
        self._audio_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=10)
        self._buffer: list[np.ndarray] = []
        self._buffer_samples = 0
        self._keep_buffer: np.ndarray | None = None  # 前のウィンドウの末尾を保持
        self._stream: sd.InputStream | None = None
        self._is_recording = False
        self._is_paused = False
        self._lock = threading.Lock()
        self._on_chunk_callback: Callable[[np.ndarray], None] | None = None

    def _audio_callback(
        self,
        indata: np.ndarray,
        frames: int,  # noqa: ARG002
        time_info,  # noqa: ARG002, ANN001
        status: sd.CallbackFlags,  # noqa: ARG002
    ) -> None:
        """音声入力コールバック."""
        if self._is_paused:
            return

        with self._lock:
            self._buffer.append(indata.copy().flatten())
            self._buffer_samples += len(indata)

            # ステップ間隔ごとにチャンクを出力
            if self._buffer_samples >= self.step_samples:
                new_audio = np.concatenate(self._buffer)

                # 前のウィンドウの末尾 + 新しい音声 でウィンドウを構成
                if self._keep_buffer is not None:
                    chunk = np.concatenate([self._keep_buffer, new_audio])
                else:
                    chunk = new_audio

                # ウィンドウ長を超えた場合は切り詰め
                if len(chunk) > self.window_samples:
                    chunk = chunk[-self.window_samples :]

                # 次回のために末尾を保持（window - step = 10秒分）
                keep_samples = self.window_samples - self.step_samples
                if len(chunk) > keep_samples:
                    self._keep_buffer = chunk[-keep_samples:]
                else:
                    self._keep_buffer = chunk.copy()

                self._buffer = []
                self._buffer_samples = 0

                # キューが満杯の場合は古いチャンクを破棄して新しいものを追加
                try:
                    self._audio_queue.put_nowait(chunk)
                except queue.Full:
                    try:
                        self._audio_queue.get_nowait()  # 古いチャンクを破棄
                        self._audio_queue.put_nowait(chunk)
                    except queue.Empty:
                        pass

                if self._on_chunk_callback:
                    self._on_chunk_callback(chunk)

    def start(self, on_chunk: Callable[[np.ndarray], None] | None = None) -> None:
        """録音を開始する."""
        self._on_chunk_callback = on_chunk
        self._is_recording = True
        self._is_paused = False

        self._stream = sd.InputStream(
            device=self.device_id,
            samplerate=self.sample_rate,
            channels=1,
            dtype=np.float32,
            callback=self._audio_callback,
        )
        self._stream.start()

    def stop(self) -> None:
        """録音を停止する."""
        self._is_recording = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        # 残りのバッファをフラッシュ
        with self._lock:
            if self._buffer:
                chunk = np.concatenate(self._buffer)
                self._audio_queue.put(chunk)
                self._buffer = []
                self._buffer_samples = 0

    def pause(self) -> None:
        """録音を一時停止する."""
        self._is_paused = True

    def resume(self) -> None:
        """録音を再開する."""
        self._is_paused = False

    def is_paused(self) -> bool:
        """一時停止中かどうかを返す."""
        return self._is_paused

    def get_audio_chunk(self, timeout: float = 0.1) -> np.ndarray | None:
        """キューから音声チャンクを取得する."""
        try:
            return self._audio_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    @staticmethod
    def list_devices() -> list[dict]:
        """利用可能な音声デバイスの一覧を取得する."""
        devices = sd.query_devices()
        input_devices = []
        for i, device in enumerate(devices):
            if device['max_input_channels'] > 0:
                input_devices.append(
                    {
                        'id': i,
                        'name': device['name'],
                        'channels': device['max_input_channels'],
                        'sample_rate': device['default_samplerate'],
                    }
                )
        return input_devices
