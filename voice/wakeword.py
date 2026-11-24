"""Wake word detection — local, offline.

Tries, in order:
  1. openWakeWord — open source; the "hey_jarvis" model ships with it.
  2. Porcupine — Picovoice; "jarvis" is a built-in keyword, needs a free
     access key in PICOVOICE_ACCESS_KEY.
  3. Nothing — returns None; the caller falls back to push-to-talk or
     continuous listen.
"""

from __future__ import annotations

import logging
import os


class WakeWord:
    def __init__(self, keyword: str = "hey_jarvis", logger=None):
        self.keyword = keyword
        self.logger = logger or logging.getLogger("jarvis.voice.wake")
        self.backend: str | None = None
        self._model = None
        self._porcupine = None
        self._detect()

    def _detect(self) -> None:
        try:
            from openwakeword.model import Model  # type: ignore

            self._model = Model(wakeword_models=[self.keyword])
            self.backend = "openwakeword"
            return
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("openWakeWord unavailable: %s", exc)
        try:
            import pvporcupine  # type: ignore

            key = os.environ.get("PICOVOICE_ACCESS_KEY", "")
            if key:
                self._porcupine = pvporcupine.create(
                    access_key=key, keywords=["jarvis"]
                )
                self.backend = "porcupine"
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("Porcupine unavailable: %s", exc)

    @property
    def available(self) -> bool:
        return self.backend is not None

    def wait_for_wake(self, timeout: float | None = None) -> bool:
        """Block until the wake word is heard. Returns False on timeout."""
        if not self.available:
            return False
        import pyaudio  # type: ignore

        pa = pyaudio.PyAudio()
        try:
            if self.backend == "openwakeword":
                return self._wait_openwakeword(pa, timeout)
            return self._wait_porcupine(pa, timeout)
        finally:
            pa.terminate()

    def _wait_openwakeword(self, pa, timeout) -> bool:
        import time

        stream = pa.open(
            format=pa.get_format_from_width(2), channels=1,
            rate=16000, input=True, frames_per_buffer=1280,
        )
        start = time.time()
        try:
            while timeout is None or time.time() - start < timeout:
                data = stream.read(1280, exception_on_overflow=False)
                prediction = self._model.predict(data)
                if prediction.get(self.keyword, 0) > 0.5:
                    return True
            return False
        finally:
            stream.stop_stream()
            stream.close()

    def _wait_porcupine(self, pa, timeout) -> bool:
        import struct
        import time

        stream = pa.open(
            format=pa.get_format_from_width(2), channels=1,
            rate=self._porcupine.sample_rate, input=True,
            frames_per_buffer=self._porcupine.frame_length,
        )
        start = time.time()
        try:
            while timeout is None or time.time() - start < timeout:
                data = stream.read(self._porcupine.frame_length, exception_on_overflow=False)
                pcm = struct.unpack_from("h" * self._porcupine.frame_length, data)
                if self._porcupine.process(pcm) >= 0:
                    return True
            return False
        finally:
            stream.stop_stream()
            stream.close()
