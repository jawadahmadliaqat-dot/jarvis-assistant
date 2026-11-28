"""Standalone demo for the MERLIN avatar overlay (app-build step 3).

Shows Jawad's Mandalorian & Grogu GLB as an always-on-top, transparent
overlay in the bottom-right corner of the desktop — visible over every
other window, no separate app window to keep open. Presence is procedural
(the model is static): slow rotation, gentle bob, and a glow halo whose
colour follows the avatar state.

Usage (from the repo root, using the repo .venv):

    .venv\\Scripts\\python.exe overlay_demo.py [path-to.glb]

Default GLB path:  ~/Downloads/mandalorian_-_grogu__the_force_0_k4we.glb

Keys (click the avatar first so its window is active):
    L = listening   S = speaking   I = idle   Esc = quit
Drag the avatar with the mouse to move it.

Requires: PyQt6 and PyQt6-WebEngine  (pip install PyQt6 PyQt6-WebEngine)
three.js is loaded from a CDN at runtime, so the demo needs internet.
"""

from __future__ import annotations

import os
import sys

# Must be set before Qt WebEngine initialises (avatar_overlay sets it too,
# but the demo sets it first so the flag is in place no matter what).
os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS", "--allow-file-access-from-files"
)

DEFAULT_GLB = os.path.expanduser(
    "~/Downloads/mandalorian_-_grogu__the_force_0_k4we.glb")


def main(argv: list[str]) -> int:
    glb_path = os.path.abspath(argv[1]) if len(argv) > 1 else DEFAULT_GLB
    if not os.path.isfile(glb_path):
        print(f"GLB not found: {glb_path}")
        print("Pass the path explicitly:  overlay_demo.py <path-to.glb>")
        return 2

    try:
        from PyQt6.QtWidgets import QApplication
    except ImportError:
        print("PyQt6 is not installed in this Python environment.")
        print("Install with:  pip install PyQt6 PyQt6-WebEngine")
        return 2

    from ui.avatar_overlay import AvatarOverlay

    app = QApplication(sys.argv[:1])
    overlay = AvatarOverlay(glb_path)
    overlay.show()
    overlay.raise_()
    overlay.activateWindow()

    print(f"Merlin avatar overlay running — model: {glb_path}")
    print("Keys: L = listening, S = speaking, I = idle, Esc = quit. "
          "Drag to move.")
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
