"""Text-to-speech.

Priority (config voice.tts_engine = auto):
  1. pyttsx3 — offline, cross-platform, no network.
  2. edge-tts — natural Microsoft voices, free, needs internet
     (writes an mp3, played with ffplay/mpv/afplay, or the system player).
  3. espeak (Linux) via subprocess.
  4. Nothing — prints the text instead of speaking.

`speak()` never raises for a missing engine: it logs and falls back.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile


class TTS:
    def __init__(
        self, engine: str = "auto", rate: int = 175, voice: str = "",
        logger=None,
    ):
        self.logger = logger or logging.getLogger("jarvis.voice.tts")
        self.rate = rate
        self.voice_hint = voice
        self.engine = self._resolve(engine)
        self._pyttsx3 = None
        if self.engine == "pyttsx3":
            self._init_pyttsx3()

    def _resolve(self, engine: str) -> str:
        if engine in ("pyttsx3", "edge-tts", "espeak", "none"):
            return engine
        for cand in ("pyttsx3", "edge-tts", "espeak"):
            if cand == "pyttsx3":
                try:
                    import pyttsx3  # noqa: F401

                    return "pyttsx3"
                except ImportError:
                    continue
            if cand == "edge-tts" and shutil.which("edge-tts"):
                return "edge-tts"
            if cand == "espeak" and shutil.which("espeak"):
                return "espeak"
        return "none"

    def _init_pyttsx3(self) -> None:
        try:
            import pyttsx3  # type: ignore

            self._pyttsx3 = pyttsx3.init()
            self._pyttsx3.setProperty("rate", self.rate)
            if self.voice_hint:
                for v in self._pyttsx3.getProperty("voices"):
                    if self.voice_hint.lower() in v.name.lower():
                        self._pyttsx3.setProperty("voice", v.id)
                        break
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("pyttsx3 failed to start: %s", exc)
            self._pyttsx3 = None
            self.engine = "edge-tts" if shutil.which("edge-tts") else "none"

    def speak(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        if self.engine == "pyttsx3" and self._pyttsx3 is not None:
            try:
                self._pyttsx3.say(text)
                self._pyttsx3.runAndWait()
                return
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("pyttsx3 speak failed: %s", exc)
        if self.engine == "edge-tts":
            if self._speak_edge_tts(text):
                return
        if self.engine == "espeak":
            subprocess.run(["espeak", text], capture_output=True, timeout=60)
            return
        print(f"[Jarvis speaks] {text}")

    def _speak_edge_tts(self, text: str) -> bool:
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                mp3 = f.name
            subprocess.run(
                ["edge-tts", "--text", text, "--write-media", mp3],
                capture_output=True, timeout=60, check=True,
            )
            return self._play_audio(mp3)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("edge-tts failed: %s", exc)
            return False
        finally:
            try:
                os.unlink(mp3)
            except OSError:
                pass

    @staticmethod
    def _play_audio(path: str) -> bool:
        for player in ("ffplay", "mpv", "afplay", "mpg123"):
            if shutil.which(player):
                args = [player, path]
                if player == "ffplay":
                    args = [player, "-nodisp", "-autoexit", "-loglevel", "quiet", path]
                subprocess.run(args, capture_output=True, timeout=120)
                return True
        if sys.platform.startswith("win"):
            os.startfile(path)  # noqa: S606 - user-initiated playback
            return True
        return False

    def stop(self) -> None:
        if self.engine == "pyttsx3" and self._pyttsx3 is not None:
            try:
                self._pyttsx3.stop()
            except Exception:
                pass
