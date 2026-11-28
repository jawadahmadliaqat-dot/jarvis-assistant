"""MERLIN avatar overlay — always-on-top 3D character for the desktop.

A frameless, transparent PyQt6 window that sits in a corner of the screen
(default: bottom-right) and renders a static GLB character via three.js
inside a QWebEngineView (see ``avatar_viewer.html`` next to this file).

The GLB Jawad supplied (Mandalorian & Grogu) has no animations and no
skins, so all "presence" is procedural: the page slowly rotates and bobs
the model, and a glow halo under it changes colour/intensity per state.

State API (used by the demo now, by the voice loop later)::

    overlay = AvatarOverlay(r"C:/Users/hp/Downloads/model.glb")
    overlay.show()
    overlay.set_state("listening")   # 'idle' | 'listening' | 'speaking'

Demo keys (handled while the overlay window is active):
    L = listening, S = speaking, I = idle, Esc = quit.

Requirements beyond plain PyQt6:
    pip install PyQt6-WebEngine
(PyQt6 on its own does NOT bundle QtWebEngineWidgets.)

Run the standalone demo from the repo root:  ``python overlay_demo.py``
"""

from __future__ import annotations

import os

# Qt WebEngine loads the GLB from a file:// URL via fetch(); Chromium
# blocks that unless file access is explicitly allowed. Set the flag
# before any QApplication is created (setdefault: never override the user).
os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS", "--allow-file-access-from-files"
)

from PyQt6.QtCore import QEvent, QPoint, Qt, QUrl, QUrlQuery  # noqa: E402
from PyQt6.QtGui import QColor, QMouseEvent  # noqa: E402
from PyQt6.QtWidgets import QApplication, QVBoxLayout, QWidget  # noqa: E402

try:
    from PyQt6.QtWebEngineCore import QWebEngineSettings
    from PyQt6.QtWebEngineWidgets import QWebEngineView
except ImportError as exc:  # pragma: no cover - depends on local install
    raise ImportError(
        "QtWebEngine is not installed. The base PyQt6 package does not "
        "include it — run:  pip install PyQt6-WebEngine"
    ) from exc

__all__ = ["AvatarOverlay", "STATES"]

STATES = ("idle", "listening", "speaking")

_VIEWER_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "avatar_viewer.html")


class AvatarOverlay(QWidget):
    """Frameless, transparent, always-on-top GLB avatar window.

    Parameters
    ----------
    glb_path:
        Path to the .glb model to render.
    size:
        Window width/height in pixels (square overlay). Default 320.
    parent:
        Optional Qt parent widget.
    """

    def __init__(self, glb_path: str, size: int = 320,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._glb_path = os.path.abspath(glb_path)
        self._state = "idle"
        self._page_ready = False
        self._drag_offset: QPoint | None = None

        self.setWindowTitle("Merlin Avatar")
        self.setFixedSize(size, size)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool  # keep out of the taskbar
        )
        # Let the desktop show through everywhere the model/glow isn't.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self._view = QWebEngineView(self)
        self._view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground,
                                True)
        self._view.page().setBackgroundColor(QColor(Qt.GlobalColor.transparent))

        settings = self._view.settings()
        # The viewer page is a local file that must (a) pull three.js from a
        # CDN and (b) fetch the GLB from another file:// URL.
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls,
            True)
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
            True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._view)

        self._view.loadFinished.connect(self._on_load_finished)
        self._view.setUrl(self._viewer_url())

        self._move_to_corner()

        # Dragging + demo keys: the WebEngine view swallows mouse/keyboard
        # events before this widget ever sees them, so watch events at the
        # application level and react only to ones aimed at this window.
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @property
    def state(self) -> str:
        return self._state

    def set_state(self, state: str) -> None:
        """Set the avatar's presence state: 'idle'|'listening'|'speaking'.

        Forwards to ``window.merlinSetState`` in the viewer page. Safe to
        call before the page has finished loading — the state is stored
        and applied as soon as the page is ready.
        """
        if state not in STATES:
            raise ValueError(
                f"unknown avatar state {state!r}; expected one of {STATES}")
        self._state = state
        if self._page_ready:
            self._push_state()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _viewer_url(self) -> QUrl:
        url = QUrl.fromLocalFile(_VIEWER_HTML)
        query = QUrlQuery()
        query.addQueryItem(
            "model", QUrl.fromLocalFile(self._glb_path).toString())
        query.addQueryItem("state", self._state)
        url.setQuery(query)
        return url

    def _push_state(self) -> None:
        self._view.page().runJavaScript(
            f"window.merlinSetState && window.merlinSetState('{self._state}');"
        )

    def _on_load_finished(self, ok: bool) -> None:
        self._page_ready = bool(ok)
        if ok:
            self._push_state()

    def _move_to_corner(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        margin = 16
        self.move(geo.right() - self.width() - margin,
                  geo.bottom() - self.height() - margin)

    # ------------------------------------------------------------------
    # Dragging + demo keys (application-level event filter)
    # ------------------------------------------------------------------
    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt naming)
        etype = event.type()

        if etype == QEvent.Type.MouseButtonPress and isinstance(
                event, QMouseEvent):
            if (event.button() == Qt.MouseButton.LeftButton
                    and self.isVisible()
                    and self.frameGeometry().contains(
                        event.globalPosition().toPoint())):
                self._drag_offset = (
                    event.globalPosition().toPoint() - self.pos())
                self.activateWindow()
        elif etype == QEvent.Type.MouseMove and self._drag_offset is not None:
            if event.buttons() & Qt.MouseButton.LeftButton:
                self.move(event.globalPosition().toPoint() - self._drag_offset)
        elif etype == QEvent.Type.MouseButtonRelease:
            self._drag_offset = None
        elif etype == QEvent.Type.KeyPress and self.isActiveWindow():
            key = event.key()
            if key == Qt.Key.Key_L:
                self.set_state("listening")
                return True
            if key == Qt.Key.Key_S:
                self.set_state("speaking")
                return True
            if key == Qt.Key.Key_I:
                self.set_state("idle")
                return True
            if key == Qt.Key.Key_Escape:
                self.close()
                app = QApplication.instance()
                if app is not None:
                    app.quit()
                return True

        return super().eventFilter(obj, event)
