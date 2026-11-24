"""Animated command-center HUD (PyQt6, optional).

One window: a talking cartoon avatar, an animated reactor core, a live
waveform, system gauges (CPU/RAM/disk), a timestamped log, a command
input, and controls. The brain runs in a worker thread so the UI never
freezes.

If PyQt6 is not installed, `gui_available()` is False and main.py prints
an install hint instead of crashing.
"""

from __future__ import annotations

import datetime
import importlib.util
import math
import random

from tools.system import system_info


def avatar_mouth_openness(level: float, t: float) -> float:
    """Mouth openness (0..1) for a speaking avatar at time `t` (seconds).

    Pure function (no Qt) so it is unit-testable: the mouth opens and
    closes in a speech-like rhythm, scaled by the audio level. This is
    amplitude simulation, not phoneme-perfect lip-sync.
    """
    level = max(0.0, min(1.0, level))
    return max(0.0, min(1.0, level * (0.55 + 0.45 * math.sin(t * 7.0))))


AVATAR_STATES = ("idle", "listening", "thinking", "speaking")


def gui_available() -> bool:
    return importlib.util.find_spec("PyQt6") is not None


if gui_available():
    from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
    from PyQt6.QtGui import QColor, QPainter, QPen
    from PyQt6.QtWidgets import (
        QApplication, QCheckBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
        QPushButton, QTextEdit, QVBoxLayout, QWidget,
    )

    STATE_COLORS = {
        "idle": QColor(0, 200, 255),
        "listening": QColor(255, 180, 0),
        "thinking": QColor(120, 255, 120),
        "speaking": QColor(255, 120, 40),
    }

    class AvatarWidget(QWidget):
        """A cute 2D cartoon assistant face, drawn with QPainter.

        No image assets — just shapes. It blinks on its own, and its
        expression follows the HUD state: idle (gentle smile), listening
        (wide eyes, small "o" mouth), thinking (eyes glance up, flat
        mouth), speaking (mouth opens/closes with the speech level).
        The mouth is amplitude simulation, not phoneme-perfect lip-sync.
        """

        def __init__(self, parent=None):
            super().__init__(parent)
            self.state = "idle"
            self.level = 0.0
            self._blink_until = 0.0
            self._next_blink = 0.0
            self.setMinimumSize(220, 200)
            self._timer = QTimer(self)
            self._timer.timeout.connect(self.update)
            self._timer.start(50)

        def set_state(self, state: str):
            self.state = state if state in AVATAR_STATES else "idle"
            self.update()

        def set_level(self, level: float):
            self.level = max(0.0, min(1.0, level))

        def _blinking(self) -> bool:
            now = datetime.datetime.now().timestamp()
            if now >= self._next_blink:
                self._blink_until = now + 0.12
                self._next_blink = now + random.uniform(2.5, 5.0)
            return now < self._blink_until

        def paintEvent(self, event):  # noqa: N802 - Qt naming
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            w, h = self.width(), self.height()
            cx, cy = w / 2, h / 2 - 6
            face_r = min(w, h) / 2 - 14
            painter.fillRect(self.rect(), QColor(8, 16, 28))

            # State-coloured glow ring.
            ring = STATE_COLORS[self.state]
            painter.setPen(QPen(ring, 3))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(
                int(cx - face_r - 6), int(cy - face_r - 6),
                int(2 * face_r + 12), int(2 * face_r + 12),
            )
            # Face.
            painter.setBrush(QColor(255, 217, 179))
            painter.setPen(QPen(QColor(230, 180, 130), 2))
            painter.drawEllipse(
                int(cx - face_r), int(cy - face_r),
                int(2 * face_r), int(2 * face_r),
            )
            # Hair tuft.
            painter.setPen(QPen(QColor(60, 60, 90), 3))
            for dx in (-18, 0, 18):
                painter.drawLine(int(cx + dx), int(cy - face_r + 4),
                                 int(cx + dx), int(cy - face_r - 10))
            eye_y = cy - face_r * 0.25
            eye_dx = face_r * 0.42
            eye_rx, eye_ry = face_r * 0.20, face_r * 0.26
            blinking = self._blinking()
            look_up = self.state == "thinking"
            for sx in (-1, 1):
                ex = cx + sx * eye_dx
                ey = eye_y - (face_r * 0.12 if look_up else 0)
                if blinking:
                    painter.setPen(QPen(QColor(60, 40, 20), 3))
                    painter.drawLine(int(ex - eye_rx), int(ey),
                                     int(ex + eye_rx), int(ey))
                    continue
                painter.setBrush(QColor(255, 255, 255))
                painter.setPen(QPen(QColor(60, 40, 20), 2))
                painter.drawEllipse(int(ex - eye_rx), int(ey - eye_ry),
                                    int(2 * eye_rx), int(2 * eye_ry))
                pupil_r = eye_rx * 0.55
                px = ex + (sx * eye_rx * 0.25 if self.state == "listening" else 0)
                py = ey - (eye_ry * 0.3 if look_up else 0)
                painter.setBrush(QColor(30, 30, 40))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(int(px - pupil_r), int(py - pupil_r),
                                    int(2 * pupil_r), int(2 * pupil_r))
                painter.setBrush(QColor(255, 255, 255))
                painter.drawEllipse(int(px - pupil_r * 0.4), int(py - pupil_r * 0.5),
                                    int(pupil_r * 0.5), int(pupil_r * 0.5))
            # Blush.
            painter.setBrush(QColor(255, 150, 150, 90))
            painter.setPen(Qt.PenStyle.NoPen)
            for sx in (-1, 1):
                painter.drawEllipse(int(cx + sx * face_r * 0.62 - 10),
                                    int(cy + face_r * 0.28 - 7), 20, 14)
            # Mouth by state.
            mouth_y = cy + face_r * 0.42
            painter.setPen(QPen(QColor(120, 60, 40), 3))
            if self.state == "speaking":
                t = datetime.datetime.now().timestamp()
                open_h = 4 + 26 * avatar_mouth_openness(self.level, t)
                painter.setBrush(QColor(120, 40, 40))
                painter.drawEllipse(int(cx - 14), int(mouth_y - open_h / 2),
                                    28, int(open_h))
            elif self.state == "listening":
                painter.setBrush(QColor(120, 40, 40))
                painter.drawEllipse(int(cx - 6), int(mouth_y - 6), 12, 12)
            elif self.state == "thinking":
                painter.drawLine(int(cx - 12), int(mouth_y),
                                 int(cx + 12), int(mouth_y - 4))
            else:  # idle smile
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawArc(int(cx - 16), int(mouth_y - 10), 32, 20, 200 * 16, 140 * 16)
            painter.setPen(QPen(QColor(255, 255, 255), 2))
            painter.drawText(int(cx - 30), int(cy + face_r + 22),
                             f"{self.state.upper()}")

    class ReactorWidget(QWidget):
        """Rotating rings + pulsing core, coloured by state."""

        def __init__(self, parent=None):
            super().__init__(parent)
            self.state = "idle"
            self.angle = 0.0
            self.pulse = 0.0
            self.setMinimumSize(280, 280)
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._tick)
            self._timer.start(40)

        def _tick(self):
            self.angle = (self.angle + 1.5) % 360
            self.pulse = (self.pulse + 0.08) % (2 * math.pi)
            self.update()

        def set_state(self, state: str):
            self.state = state if state in STATE_COLORS else "idle"
            self.update()

        def paintEvent(self, event):  # noqa: N802 - Qt naming
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            cx, cy = self.width() / 2, self.height() / 2
            radius = min(cx, cy) - 12
            color = STATE_COLORS[self.state]
            painter.fillRect(self.rect(), QColor(8, 16, 28))

            # Outer tick ring.
            pen = QPen(color, 2)
            painter.setPen(pen)
            for i in range(60):
                a = math.radians(i * 6 + self.angle * 0.4)
                r1 = radius
                r2 = radius - (10 if i % 5 == 0 else 5)
                painter.drawLine(
                    int(cx + r1 * math.cos(a)), int(cy + r1 * math.sin(a)),
                    int(cx + r2 * math.cos(a)), int(cy + r2 * math.sin(a)),
                )
            # Two rotating arc rings.
            for ring, width, span in ((0.78, 3, 120), (0.62, 2, 200)):
                pen = QPen(color, width)
                painter.setPen(pen)
                painter.drawArc(
                    int(cx - radius * ring), int(cy - radius * ring),
                    int(2 * radius * ring), int(2 * radius * ring),
                    int((self.angle if ring > 0.7 else -self.angle) * 16),
                    span * 16,
                )
            # Pulsing core.
            core_r = radius * 0.34 * (1 + 0.08 * math.sin(self.pulse))
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(
                int(cx - core_r), int(cy - core_r),
                int(2 * core_r), int(2 * core_r),
            )
            painter.setPen(QPen(QColor(255, 255, 255), 2))
            painter.drawText(
                int(cx - 40), int(cy + radius * 0.55),
                f"JARVIS — {self.state.upper()}",
            )

    class WaveformWidget(QWidget):
        """Live audio-level bars (real level when speaking, idle shimmer)."""

        def __init__(self, parent=None):
            super().__init__(parent)
            self.level = 0.0
            self.setMinimumHeight(48)
            self._timer = QTimer(self)
            self._timer.timeout.connect(self.update)
            self._timer.start(60)

        def set_level(self, level: float):
            self.level = max(0.0, min(1.0, level))

        def paintEvent(self, event):  # noqa: N802 - Qt naming
            painter = QPainter(self)
            painter.fillRect(self.rect(), QColor(8, 16, 28))
            bars = 48
            w = self.width() / bars
            for i in range(bars):
                h = (self.height() * 0.15
                     + self.height() * 0.8 * self.level
                     * abs(math.sin(i * 0.6 + datetime.datetime.now().timestamp() * 6)))
                painter.fillRect(
                    int(i * w + 1), int((self.height() - h) / 2),
                    int(w - 2), int(h), QColor(0, 200, 255),
                )

    class _BrainWorker(QThread):
        answered = pyqtSignal(str)

        def __init__(self, brain, text):
            super().__init__()
            self.brain = brain
            self.text = text

        def run(self):  # noqa: N802 - Qt naming
            try:
                self.answered.emit(self.brain.respond(self.text))
            except Exception as exc:  # noqa: BLE001
                self.answered.emit(f"Error: {exc}")

    class JarvisHUD(QMainWindow):
        def __init__(self, brain, config, tts=None):
            super().__init__()
            self.brain = brain
            self.config = config
            self.tts = tts
            self.setWindowTitle(f"{config.assistant_name} — Personal AI System")
            self.resize(1100, 700)
            self._worker = None
            self._build_ui()
            self._sys_timer = QTimer(self)
            self._sys_timer.timeout.connect(self._refresh_systems)
            self._sys_timer.start(config.get("gui", "refresh_ms", default=1000))
            self._refresh_systems()
            self.log(f"{config.assistant_name} online. Provider: {brain.active_provider_name}.")

        # -- UI construction -------------------------------------------
        def _build_ui(self):
            central = QWidget()
            self.setCentralWidget(central)
            root = QHBoxLayout(central)

            left = QVBoxLayout()
            self.avatar = AvatarWidget()
            left.addWidget(self.avatar)
            self.reactor = ReactorWidget()
            left.addWidget(self.reactor)
            self.wave = WaveformWidget()
            left.addWidget(self.wave)
            self.systems_label = QLabel("Systems: …")
            self.systems_label.setStyleSheet("color: #9fd8ff; font-family: monospace;")
            left.addWidget(self.systems_label)
            left.addStretch()
            root.addLayout(left, 1)

            middle = QVBoxLayout()
            self.log_view = QTextEdit()
            self.log_view.setReadOnly(True)
            self.log_view.setStyleSheet(
                "background: #08101c; color: #cfefff; font-family: monospace;"
            )
            middle.addWidget(self.log_view, 1)
            row = QHBoxLayout()
            self.input = QLineEdit()
            self.input.setPlaceholderText("Type a command or question…")
            self.input.returnPressed.connect(self._send)
            row.addWidget(self.input, 1)
            self.send_btn = QPushButton("Send")
            self.send_btn.clicked.connect(self._send)
            row.addWidget(self.send_btn)
            middle.addLayout(row)
            root.addLayout(middle, 2)

            right = QVBoxLayout()
            self.state_label = QLabel("STATE: IDLE")
            right.addWidget(self.state_label)
            self.mic_btn = QPushButton("🎙 Hold to talk")
            self.mic_btn.pressed.connect(self._push_to_talk)
            right.addWidget(self.mic_btn)
            self.brief_btn = QPushButton("🌅 Morning briefing")
            self.brief_btn.clicked.connect(lambda: self._run_tool("morning_briefing", {}))
            right.addWidget(self.brief_btn)
            self.tasks_btn = QPushButton("🧵 Background tasks")
            self.tasks_btn.clicked.connect(self._show_tasks)
            right.addWidget(self.tasks_btn)
            self.mute = QCheckBox("Mute voice")
            right.addWidget(self.mute)
            self.provider_label = QLabel("Provider: …")
            right.addWidget(self.provider_label)
            right.addStretch()
            root.addLayout(right, 1)

            self.setStyleSheet("background: #0a1420; color: #cfefff;")

        # -- behaviour --------------------------------------------------
        def log(self, text: str):
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            self.log_view.append(f"[{ts}] {text}")

        def set_state(self, state: str):
            self.reactor.set_state(state)
            self.avatar.set_state(state)
            self.state_label.setText(f"STATE: {state.upper()}")

        def _refresh_systems(self):
            info = system_info().replace("\n", "  |  ")
            self.systems_label.setText(info)
            self.provider_label.setText(f"Provider: {self.brain.active_provider_name}")

        def _send(self):
            text = self.input.text().strip()
            if not text:
                return
            self.input.clear()
            self.log(f"You: {text}")
            self._ask(text)

        def _ask(self, text: str):
            self.set_state("thinking")
            self._worker = _BrainWorker(self.brain, text)
            self._worker.answered.connect(self._on_answer)
            self._worker.start()

        def _on_answer(self, reply: str):
            self.set_state("speaking")
            self.log(f"{self.config.assistant_name}: {reply}")
            self.wave.set_level(0.7)
            self.avatar.set_level(0.7)
            if self.tts and not self.mute.isChecked():
                self.tts.speak(reply)
            self.wave.set_level(0.1)
            self.avatar.set_level(0.1)
            self.set_state("idle")

        def _run_tool(self, name: str, args: dict):
            result = self.brain.tool_result_text(name, args)
            self.log(f"{name}: {result}")

        def _show_tasks(self):
            tasks = self.brain.task_manager.list_tasks() if hasattr(self.brain, "task_manager") else []
            if not tasks:
                self.log("No background tasks yet.")
                return
            for t in tasks:
                self.log(f"Task {t['id']} [{t['status']}] {t['description']} — {t.get('progress', '')}")

        def _push_to_talk(self):
            self.set_state("listening")
            self.log("Listening… (push-to-talk)")
            try:
                from voice.stt import STT

                stt = STT(engine=self.config.get("voice", "stt_engine", default="auto"),
                          language=self.config.language)
                heard = stt.listen_once()
                if heard:
                    self.log(f"You (voice): {heard}")
                    self._ask(heard)
                else:
                    self.set_state("idle")
            except Exception as exc:  # noqa: BLE001
                self.log(f"Microphone unavailable: {exc}")
                self.set_state("idle")

    def run_hud(brain, config, tts=None):
        import sys

        app = QApplication(sys.argv)
        hud = JarvisHUD(brain, config, tts=tts)
        hud.show()
        return app.exec()

else:  # PyQt6 missing — importable module, clear error at runtime.
    def run_hud(brain, config, tts=None):  # type: ignore
        raise RuntimeError(
            "The HUD needs PyQt6: pip install PyQt6 (and a display). "
            "Text mode still works: python main.py"
        )
