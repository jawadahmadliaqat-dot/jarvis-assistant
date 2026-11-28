"""Speech-to-text.

Audio capture is done directly with PyAudio (16 kHz, mono, 16-bit PCM).
SpeechRecognition's microphone layer is NOT used for capture: it proved
incompatible with some PyAudio builds — push-to-talk died with
"open() got an unexpected keyword argument 'metadata_errors'".

Recognition priority (config voice.stt_engine = auto):
  1. faster-whisper (local, offline, CPU-friendly "tiny" model) — the
     recorded PCM is transcribed locally, so nothing leaves the machine.
  2. Google web speech via SpeechRecognition (free, needs internet) —
     SpeechRecognition is only a recognition backend here, never capture.
  3. Nothing — raises VoiceUnavailable; the caller falls back to text.

No microphone on this machine? Every function raises VoiceUnavailable
with a clear message instead of crashing.
"""

from __future__ import annotations

import io
import logging
import math
import sys
import time
import wave
from array import array
from collections import deque

# Capture format: 16 kHz mono 16-bit PCM — what both recognisers want.
SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2  # bytes per sample (16-bit)
CHANNELS = 1
CHUNK_FRAMES = 1024  # ~64 ms per chunk at 16 kHz
CHUNK_SECONDS = CHUNK_FRAMES / SAMPLE_RATE
# RMS level (16-bit scale) above which a chunk counts as speech. Quiet-room
# noise on a laptop mic usually sits well below this; normal speech peaks
# in the thousands.
SPEECH_RMS_THRESHOLD = 500
# Stop recording after this much trailing silence.
TRAILING_SILENCE_SECONDS = 0.8
# Chunks kept from just before speech starts, so the first syllable of the
# utterance is not clipped.
PRE_ROLL_CHUNKS = 3


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


def _chunk_rms(data: bytes) -> float:
    """Root-mean-square level of a 16-bit PCM chunk (0 if empty)."""
    if not data:
        return 0.0
    samples = array("h")
    samples.frombytes(data[: len(data) - (len(data) % 2)])
    if sys.byteorder == "big":
        samples.byteswap()
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


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
        """Record one utterance from the mic and return its transcript.

        Returns None if no speech starts within `timeout` seconds.
        Raises VoiceUnavailable if the microphone cannot be used at all.
        """
        pcm = self._record_pcm(timeout, phrase_time_limit)
        if pcm is None:
            return None
        if self.engine == "whisper":
            return self._transcribe_whisper(pcm)
        return self._transcribe_google(pcm)

    def _record_pcm(self, timeout: int, phrase_time_limit: int) -> bytes | None:
        """Record one utterance directly with PyAudio.

        Waits up to `timeout` seconds for speech to start (energy
        threshold), then records until ~0.8 s of trailing silence or
        `phrase_time_limit` seconds, whichever comes first. Returns the
        raw 16 kHz mono 16-bit PCM, or None if no speech started.
        """
        try:
            import pyaudio  # type: ignore
        except ImportError as exc:
            raise VoiceUnavailable(f"PyAudio is not installed: {exc}")

        pa = None
        stream = None
        try:
            try:
                pa = pyaudio.PyAudio()
                stream = pa.open(
                    format=pa.get_format_from_width(SAMPLE_WIDTH),
                    channels=CHANNELS,
                    rate=SAMPLE_RATE,
                    input=True,
                    frames_per_buffer=CHUNK_FRAMES,
                )
            except Exception as exc:  # noqa: BLE001 - surface the real error
                raise VoiceUnavailable(f"No microphone available: {exc}")

            # Phase 1: wait for speech to start.
            pre_roll: deque[bytes] = deque(maxlen=PRE_ROLL_CHUNKS)
            frames: list[bytes] = []
            deadline = time.monotonic() + timeout
            started = False
            while time.monotonic() < deadline:
                data = stream.read(CHUNK_FRAMES, exception_on_overflow=False)
                if _chunk_rms(data) >= SPEECH_RMS_THRESHOLD:
                    frames = list(pre_roll) + [data]
                    started = True
                    break
                pre_roll.append(data)
            if not started:
                return None

            # Phase 2: record until trailing silence or the time limit.
            record_deadline = time.monotonic() + phrase_time_limit
            silent_seconds = 0.0
            while time.monotonic() < record_deadline:
                data = stream.read(CHUNK_FRAMES, exception_on_overflow=False)
                frames.append(data)
                if _chunk_rms(data) >= SPEECH_RMS_THRESHOLD:
                    silent_seconds = 0.0
                else:
                    silent_seconds += CHUNK_SECONDS
                    if silent_seconds >= TRAILING_SILENCE_SECONDS:
                        break
            return b"".join(frames)
        except VoiceUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 - surface the real error
            raise VoiceUnavailable(f"Microphone recording failed: {exc}")
        finally:
            if stream is not None:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:  # noqa: BLE001 - cleanup is best-effort
                    pass
            if pa is not None:
                pa.terminate()

    def _transcribe_google(self, pcm: bytes) -> str | None:
        import speech_recognition as sr

        recognizer = sr.Recognizer()
        audio = sr.AudioData(pcm, SAMPLE_RATE, SAMPLE_WIDTH)
        try:
            return recognizer.recognize_google(audio, language=self.language)
        except sr.UnknownValueError:
            return None
        except sr.RequestError as exc:
            self.logger.warning("Google STT request failed: %s", exc)
            return None

    def _transcribe_whisper(self, pcm: bytes) -> str | None:
        from faster_whisper import WhisperModel  # type: ignore

        if not hasattr(self, "_whisper_model"):
            self._whisper_model = WhisperModel("tiny", device="cpu", compute_type="int8")
        wav = io.BytesIO()
        with wave.open(wav, "wb") as w:
            w.setnchannels(CHANNELS)
            w.setsampwidth(SAMPLE_WIDTH)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(pcm)
        wav.seek(0)
        segments, _ = self._whisper_model.transcribe(wav, language=self.language)
        text = " ".join(seg.text for seg in segments).strip()
        return text or None
