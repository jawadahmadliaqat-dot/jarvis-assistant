"""Speech-to-text.

Priority (config voice.stt_engine = auto):
  1. faster-whisper (local, offline, CPU-friendly "tiny" model) — audio is
     captured with SpeechRecognition's microphone handling, then transcribed
     locally, so nothing leaves the machine.
  2. Google web speech via SpeechRecognition (free, needs internet).
  3. Nothing — raises VoiceUnavailable; the caller falls back to text.

No microphone on this machine? Every function raises VoiceUnavailable
with a clear message instead of crashing.
"""

from __future__ import annotations

import io
import logging
import wave
from typing import Any


class VoiceUnavailable(Exception):
    pass


def available_engines() -> list[str]:
    engines = []
    try:
        import faster_whisper  # noqa: F401

        engines.append("whisper")
    except ImportError:
        pass
    try:
        import speech_recognition  # noqa: F401

        engines.append("google")
    except ImportError:
        pass
    return engines


class STT:
    def __init__(self, engine: str = "auto", language: str = "en", logger=None):
        self.language = language
        self.logger = logger or logging.getLogger("jarvis.voice.stt")
        self.engine = self._resolve(engine)

    def _resolve(self, engine: str) -> str:
        available = available_engines()
        if engine == "whisper" and "whisper" in available:
            return "whisper"
        if engine == "google" and "google" in available:
            return "google"
        if engine == "auto":
            if "whisper" in available:
                return "whisper"
            if "google" in available:
                return "google"
        raise VoiceUnavailable(
            "No speech-recognition engine installed. "
            "Install faster-whisper (offline) or SpeechRecognition "
            "(Google web speech), or use text mode."
        )

    def listen_once(self, timeout: int = 5, phrase_time_limit: int = 15) -> str | None:
        """Record one utterance from the mic and return its transcript."""
        import speech_recognition as sr

        recognizer = sr.Recognizer()
        try:
            mic = sr.Microphone()
        except Exception as exc:
            raise VoiceUnavailable(f"No microphone available: {exc}")
        with mic as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            try:
                audio = recognizer.listen(
                    source, timeout=timeout, phrase_time_limit=phrase_time_limit
                )
            except sr.WaitTimeoutError:
                return None
        if self.engine == "whisper":
            return self._transcribe_whisper(audio)
        return self._transcribe_google(recognizer, audio)

    def _transcribe_google(self, recognizer, audio) -> str | None:
        import speech_recognition as sr

        try:
            return recognizer.recognize_google(audio, language=self.language)
        except sr.UnknownValueError:
            return None
        except sr.RequestError as exc:
            self.logger.warning("Google STT request failed: %s", exc)
            return None

    def _transcribe_whisper(self, audio) -> str | None:
        from faster_whisper import WhisperModel  # type: ignore

        if not hasattr(self, "_whisper_model"):
            self._whisper_model = WhisperModel("tiny", device="cpu", compute_type="int8")
        wav = io.BytesIO()
        with wave.open(wav, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(audio.get_raw_data(convert_rate=16000, convert_width=2))
        wav.seek(0)
        segments, _ = self._whisper_model.transcribe(wav, language=self.language)
        text = " ".join(seg.text for seg in segments).strip()
        return text or None
