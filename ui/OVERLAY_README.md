# Merlin Avatar Overlay (demo)

Jawad's 3D character — the Mandalorian & Grogu GLB he supplied — as an
**always-on-top desktop overlay**: a small transparent window pinned to the
bottom-right corner of the screen, visible over every other window. This is
not a separate app window to open and close; it floats on the desktop.

The GLB is a static posed model (no animations, no skins), so presence is
**procedural**: the model slowly rotates and bobs, and a glow halo under it
changes with the avatar's state —

| State       | Halo                                   |
|-------------|----------------------------------------|
| `idle`      | dim cyan, slow breathing pulse         |
| `listening` | brighter cyan, stronger pulse          |
| `speaking`  | warm green, lively pulse               |

## Files

- `ui/avatar_overlay.py` — PyQt6 frameless, transparent, always-on-top
  window hosting a `QWebEngineView`. Draggable with the mouse.
- `ui/avatar_viewer.html` — three.js scene that renders the GLB
  (transparent background, halo, rotation/bob).
- `overlay_demo.py` (repo root) — standalone launcher for this demo.

## Run it (Windows)

One extra package is required — plain `PyQt6` does **not** include the
web engine:

```
.venv\Scripts\python.exe -m pip install PyQt6-WebEngine
```

Then, from the repo root:

```
.venv\Scripts\python.exe overlay_demo.py "C:\Users\hp\Downloads\mandalorian_-_grogu__the_force_0_k4we.glb"
```

(With no argument it defaults to that same path in `~/Downloads`.)

Demo keys — click the avatar first so its window is active:
**L** listening · **S** speaking · **I** idle · **Esc** quit.
Drag the avatar with the mouse to reposition it.

## State API

```python
from ui.avatar_overlay import AvatarOverlay

overlay = AvatarOverlay(r"C:\path\to\model.glb")   # size=320 by default
overlay.show()
overlay.set_state("listening")   # 'idle' | 'listening' | 'speaking'
```

`set_state()` forwards to `window.merlinSetState(state)` in the viewer
page and is safe to call before the page has loaded.

## Honest limits (v1)

- **three.js comes from a CDN** (jsdelivr, pinned `three@0.160.0`), so the
  demo needs internet. A production build should vendor the JS locally.
- **No click-through**: the overlay window catches clicks in its square
  (that's also how dragging works). Pass-through outside the model
  silhouette is a later refinement.
- **Not wired into the app yet**: this demo is standalone. Feeding the
  states from the real voice loop (listening while the mic is hot,
  speaking while TTS plays) inside `main.py` is the next step.
- The GLB itself is **not in git** (`*.glb` is gitignored) — it stays on
  Jawad's PC / in his files, and the overlay loads it from a local path.
