"""Voice loop — ties STT + brain + TTS together.

Modes:
  - wake word (if configured and available): wait for "hey_jarvis", then
    listen once and answer.
  - continuous: listen, answer, repeat.
  - push-to-talk is handled by the GUI (it calls listen_once directly).

Quiet hours (config routines.quiet_hours) suppress unprompted speech
(greetings, proactive check-ins) but never block a direct answer.
"""

from __future__ import annotations

import datetime
import logging
import threading
import time

from core.context import in_quiet_hours
from voice.stt import STT, VoiceUnavailable
from voice.tts import TTS
from voice.wakeword import WakeWord


class VoiceLoop:
    def __init__(self, brain, config, logger=None):
        self.brain = brain
        self.config = config
        self.logger = logger or logging.getLogger("jarvis.voice")
        self.tts = TTS(
            engine=config.get("voice", "tts_engine", default="auto"),
            rate=int(config.get("voice", "tts_rate", default=175)),
            voice=str(config.get("voice", "tts_voice", default="")),
            logger=self.logger,
        )
        self.stt = None
        try:
            self.stt = STT(
                engine=config.get("voice", "stt_engine", default="auto"),
                language=config.language,
                logger=self.logger,
            )
        except VoiceUnavailable as exc:
            self.logger.warning("STT unavailable: %s", exc)
        self.wake = None
        wake_word = str(config.get("voice", "wake_word", default="off"))
        if wake_word != "off":
            candidate = WakeWord(keyword=wake_word, logger=self.logger)
            if candidate.available:
                self.wake = candidate
            else:
                self.logger.warning(
                    "wake word '%s' requested but no wake-word engine "
                    "is installed; falling back to continuous listen",
                    wake_word,
                )
        self._stop = threading.Event()
        self.on_state = None  # optional callback(state: str)
        self._checker = None
        try:
            from core.proactive import ProactiveChecker

            tasks = getattr(brain, "task_manager", None)
            self._checker = ProactiveChecker(
                config, brain.memory, tasks=tasks, logger=self.logger
            )
        except Exception as exc:  # noqa: BLE001 - proactive is optional
            self.logger.warning("proactive checker unavailable: %s", exc)
        self._last_check = 0.0
        self._check_interval = float(
            config.get("routines", "proactive", "check_interval_seconds", default=300)
        )

    def stop(self) -> None:
        self._stop.set()
        self.tts.stop()

    def _set_state(self, state: str) -> None:
        self.logger.info("voice state: %s", state)
        if self.on_state:
            self.on_state(state)

    def _in_quiet_hours(self) -> bool:
        return in_quiet_hours(self.config)

    def _check_proactive(self) -> None:
        """Surface new alerts (once each, never in quiet hours)."""
        if self._checker is None:
            return
        try:
            alerts = self._checker.check(respect_quiet_hours=True)
        except Exception as exc:  # noqa: BLE001 - alerts must never kill the loop
            self.logger.warning("proactive check failed: %s", exc)
            return
        for alert in alerts:
            print(f"{self.config.assistant_name} (alert): {alert}")
            if self.config.get("voice", "speak_replies", default=True):
                self.tts.speak(alert)

    def run(self) -> None:
        if self.stt is None:
            print(
                "Voice mode needs a speech-recognition engine.\n"
                "Install faster-whisper (offline) or SpeechRecognition, "
                "or use text mode: python main.py"
            )
            return
        print(f"{self.config.assistant_name} is listening. Say 'hey {self.config.assistant_name.lower()}'" if self.wake else f"{self.config.assistant_name} is listening (continuous). Ctrl+C to stop.")
        try:
            while not self._stop.is_set():
                if time.time() - self._last_check >= self._check_interval:
                    self._last_check = time.time()
                    self._check_proactive()
                if self.wake is not None:
                    self._set_state("idle")
                    if not self.wake.wait_for_wake():
                        continue
                    print("Yes, sir?")
                self._set_state("listening")
                heard = self.stt.listen_once()
                if not heard:
                    continue
                print(f"You: {heard}")
                self._set_state("thinking")
                reply = self.brain.respond(heard)
                print(f"{self.config.assistant_name}: {reply}")
                if self.config.get("voice", "speak_replies", default=True):
                    self._set_state("speaking")
                    self.tts.speak(reply)
        except KeyboardInterrupt:
            print("\nVoice loop stopped.")
        finally:
            self._set_state("idle")
