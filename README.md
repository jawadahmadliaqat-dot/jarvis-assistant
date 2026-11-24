# JARVIS — a local, cross-platform personal AI assistant

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/Platform-Windows%20%7C%20Linux-lightgrey?logo=windows&logoColor=white" alt="Windows and Linux">
  <img src="https://img.shields.io/badge/License-Source--Available-blue" alt="Source-Available Licence">
  <img src="https://img.shields.io/badge/API%20key-optional-brightgreen" alt="No API key required">
  <img src="https://img.shields.io/badge/Voice-STT%20%2B%20TTS-orange" alt="Voice support">
</p>

> **"Yes, sir."** — a real, runnable Jarvis that lives on *your* machine: voice
> and text, swappable LLM providers (Gemini / OpenAI-compatible / local
> Ollama / fully offline), a real tool-use loop, persistent memory,
> background tasks, deep research with quote verification, an animated HUD,
> and a drop-in plugin system. **Windows-first, Linux too. No paid service
> required to run it.**

This is an **original implementation** written from scratch. It takes
inspiration from the *idea* of Jarvis-style assistants — including
FatihMakes' Mark 57 series, which this project aims to surpass — but shares
no code with them and is not affiliated with Marvel, Google, or FatihMakes.

---

## Contents

- [How it beats Mark 57](#how-it-beats-mark-57)
- [Features](#features)
- [Quick start](#quick-start)
- [Usage](#usage)
- [Web HUD](#web-hud)
- [Configuration](#configuration)
- [Voice](#voice)
- [Plugins](#plugins)
- [Project structure](#project-structure)
- [Tests](#tests)
- [Roadmap](#roadmap)
- [License](#license)

---

## How it beats Mark 57

| | Mark 57 (FatihMakes) | Jarvis (this repo) |
|---|---|---|
| Providers | Gemini Live + local engines | **Fallback chain**: Gemini → OpenAI-compatible → Ollama → **offline** (works with zero keys) |
| Voice | Gemini Live native audio | STT (local Whisper / Google) + TTS (offline pyttsx3 / edge-tts) + wake word + push-to-talk |
| Background tasks | Survive crash, auto-resume | Persistent + **explicit resume** (nothing re-runs silently) |
| Deep research | Quote-checked reports | Same, plus quotes are **verified verbatim** or dropped |
| Memory | Session + persistent | SQLite facts + full conversation history + reminders |
| Plugins | Drop-in `.py` files | Same, plus tools auto-appear in the LLM's tool list |
| HUD | 3D reactor core | Animated reactor + waveform + live gauges + log |
| Offline | Local engines only | **Offline provider**: time, calc, notes, reminders, files, search, weather — all work with no key and no model |
| Tests | — | `tests/test_smoke.py` — run before every release |

---

## Features

- **Coding doctor** — paste a traceback or point at a file and Jarvis
  diagnoses it, backs the file up (`.bak`), applies a minimal patch and
  verifies it (`py_compile` or your command). Needs an LLM (Gemini/Ollama);
  offline it says so and applies nothing.
- **Routines** — named schedules in config (`morning` 07:00 briefing,
  `evening` 21:30 day-summary); run with `python main.py --routine morning`.
- **Proactive alerts** — Jarvis notices due reminders, low disk, and
  finished background tasks without being asked (once each, never in
  quiet hours); check any time with `python main.py --check`.
- **Context-aware replies** — the brain knows the time of day, system
  load, active window (when detectable) and pending reminders, so it can
  say "it's 2am, time to sleep" naturally. Only detected facts are used.
- **Talk or type** — microphone (wake word `hey_jarvis`, push-to-talk, or
  continuous listen) and a text command box, in the CLI and the HUD.
- **Real tool use** — the LLM decides which tool to call, Jarvis executes
  it, and reports what it *observed*, not what it attempted.
- **Web search** (DuckDuckGo, no key), **news**, **weather** (Open-Meteo,
  no key), **time/date**, **calculator**, **file search/read**, **notes**,
  **reminders**, **open apps & websites**, **system info/control** (volume,
  brightness, screenshot, clipboard), **morning briefing**.
- **Deep research** — multi-angle search, full-page fetch, quote
  verification, cited Markdown report.
- **Persistent memory** — facts, preferences, conversation history, and
  reminders survive restarts (SQLite + JSON in `~/.jarvis`).
- **Background tasks** — long work runs beside the conversation; check,
  steer, or stop it.
- **Plugins** — drop a `.py` file in `plugins/` and Jarvis learns a new
  skill on next launch. Two examples included.
- **Animated HUD** — reactor core, waveform, CPU/RAM gauges, live log
  (PyQt6, optional — CLI works without it).
- **Talking cartoon avatar** — a cute 2D face in the HUD: it blinks,
  its mouth moves while it speaks, and its expression follows the state
  (idle, listening, thinking, speaking). Drawn in code, no image files.

---

## Quick start

### Windows

```bat
git clone https://github.com/jawadahmadliaqat-dot/jarvis-assistant.git
cd jarvis-assistant
setup.bat
REM edit .env — add GEMINI_API_KEY (free: https://aistudio.google.com/apikey)
REM or install Ollama and run: ollama pull llama3.2:3b
.venv\Scripts\python.exe main.py --gui
```

### Linux

```bash
git clone https://github.com/jawadahmadliaqat-dot/jarvis-assistant.git
cd jarvis-assistant
bash setup.sh
# edit .env — add GEMINI_API_KEY, or run Ollama, or use no key (offline mode)
.venv/bin/python main.py --gui        # needs PyQt6: pip install PyQt6
.venv/bin/python main.py              # text mode (always works)
```

No key at all? Jarvis still runs — offline mode answers with local tools,
and says so honestly.

---

## Usage

```bash
python main.py                          # interactive text chat
python main.py --once "what time is it"  # one command, print reply, exit
python main.py --voice                  # microphone loop (needs STT/TTS)
python main.py --gui                    # animated HUD
python main.py --web                    # Mark 57-style web HUD on localhost
python main.py --briefing               # morning briefing and exit
python main.py --routine morning          # run a named routine and exit
python main.py --routines                 # list configured routines
python main.py --check                    # proactive alerts and exit
python main.py --fix broken.py            # fix an error in a file (needs LLM)
python main.py --fix broken.py --error "Traceback..." --verify "pytest -q"
python main.py --research "fusion power"  # deep research report
python main.py --tasks                  # list background tasks
python main.py --task "research quantum batteries"  # start background task
```

In chat, try: *"search the web for Mars rovers"*, *"weather in Karachi"*,
*"remind me to call Ali in 30 minutes"*, *"remember that my birthday is
March 2"*, *"open YouTube"*, *"what's my CPU usage"*, *"give me the morning
briefing"*.

---

## Configuration

Copy the examples and edit:

```bash
cp config.yaml.example config.yaml
cp .env.example .env
```

- `config.yaml` — assistant name, provider order/models, voice, GUI, data dir.
- `.env` — API keys only. **Never commit it** (it's git-ignored).

Provider order is a fallback chain: Gemini → OpenAI-compatible → Ollama →
offline. Set `providers.order` to change it, or leave a provider out.

## Routines & proactive alerts

Routines live in `config.yaml` under `routines.definitions` — a name, a time
of day, and actions (tool calls or spoken lines). Defaults: `morning` at
07:00 (briefing) and `evening` at 21:30 (day-summary). A routine is due
once its time has passed and it has not run yet today.

```bash
python main.py --routine morning    # run now
python main.py --routines           # list them
python main.py --check              # anything needing attention?
```

Jarvis also checks proactively (voice loop, every 5 minutes by default):
due reminders, disk below 5 GB free, and background tasks that finished
in the last 24 hours. Each alert fires once per trigger and never during
quiet hours (`routines.quiet_hours`, default 23:00–07:00).

## Coding doctor

```bash
python main.py --fix broken.py                          # finds the error itself
python main.py --fix broken.py --error "Traceback..."    # with a pasted traceback
python main.py --fix broken.py --verify "pytest -q"      # custom verification
```

In chat, just say "fix the error in main.py" (or paste the traceback).
How it works: the traceback's file/line is parsed, the file is read, the
LLM returns a minimal JSON patch, Jarvis writes a `.bak` backup first,
applies the patch, then verifies (`py_compile` for Python, or your command)
and reports PASS/FAIL.

Honest limits: small errors (typos, missing colons, bad imports) are
auto-fixed; patches that delete code or touch more than 50 lines need your
confirmation (`--confirm` / "yes, apply it"); if the model is unsure it
suggests a fix instead of applying one. Smart fixing needs an LLM — a
Gemini key or local Ollama. Offline, the doctor says so and touches nothing.

## Talking cartoon avatar

The HUD (`python main.py --gui`, needs PyQt6) now has a small cartoon
assistant face above the reactor: round face, blinking eyes, a mouth
that opens and closes while Jarvis speaks, and expressions for idle,
listening, thinking, and speaking. It is drawn entirely in code
(`gui/hud.py`, `AvatarWidget`) — no image files, no new dependencies.

Honest limits: it is a 2D cartoon, not a 3D character. The mouth moves
with speech amplitude (simulated rhythm scaled by the audio level),
not phoneme-perfect lip-sync. While the offline voice engine
(pyttsx3) speaks, the mouth holds its open pose; with edge-tts it
animates freely.

---

## Web HUD

A Mark 57-style command center that runs in the browser — no PyQt6,
no new dependencies, no build tools. The PyQt6 HUD still exists; this
is an additional mode.

```bash
python main.py --web                # http://127.0.0.1:8765
python main.py --web --web-port 8080
```

Three columns, like the video: **Systems** (live CPU / memory / disk /
GPU gauges) + **Status** (uptime, processes, platform, engine, voice)
+ **Tasks** on the left; an animated geometric wireframe face with a
waveform in the center; **Communications** log + **Controls** (morning
briefing, hold to talk, background tasks, mute voice) on the right; a
command box along the bottom. Commands go through the real Brain —
the same tool-use loop as text mode — so `calculate 12 * 8` answers
`96`, and the morning briefing button runs the real briefing.

Honest limits: the face is an animated SVG drawing (CSS/JS), not a
3D render — it pulses, rotates, blinks, and its mouth moves while
Jarvis speaks, but it is 2D art. The page polls the server once a
second (no websockets), so gauges and the log lag up to a second.
Hold-to-talk uses the browser SpeechRecognition API (Chrome/Edge);
if your browser has none, the button says so and you type instead —
voice input is never faked. The server binds 127.0.0.1 only, so the
page is reachable from your machine alone. Works with zero API keys
(offline mode), like the CLI.

---

## Voice

| Piece | Default | Alternatives |
|---|---|---|
| STT | `auto` (faster-whisper local if installed, else Google web) | `whisper`, `google`, `none` |
| TTS | `auto` (pyttsx3 offline if installed, else edge-tts) | `pyttsx3`, `edge-tts`, `none` |
| Wake word | `off` | `hey_jarvis` (openWakeWord / Porcupine) |

Install the extras you want:

```bash
pip install pyttsx3 SpeechRecognition PyQt6 edge-tts faster-whisper openwakeword
```

---

## Plugins

Drop a file in `plugins/`, e.g. `plugins/my_skill.py`:

```python
from tools.registry import Tool

def _my_tool(arg: str) -> str:
    return f"Hello from my skill: {arg}"

TOOLS = [Tool(name="my_skill",
              description="Say hello from my skill.",
              parameters={"type": "object",
                          "properties": {"arg": {"type": "string"}},
                          "required": ["arg"]},
              func=_my_tool)]
```

Restart Jarvis — the tool appears in the LLM's tool list automatically.

---

## Project structure

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full design (provider chain,
tool loop, memory schema, voice pipeline, background tasks, GUI).

```
main.py            CLI / GUI entry point
core/              config, brain (tool-use loop), memory, background tasks
providers/         gemini, openai-compatible, ollama, offline
voice/             stt, tts, wake word, listener
tools/             search, weather, system, files, notes, reminders, research
gui/               PyQt6 animated HUD + web HUD (HTML/CSS/JS, stdlib server)
plugins/           drop-in skills (two examples included)
tests/             smoke tests
```

---

## Tests

```bash
python -m unittest discover -s tests -v
python main.py --once "calculate 12 * 8"   # offline smoke test
```

---

## Roadmap

- [ ] Screen/webcam vision into the conversation (Gemini vision)
- [ ] Calendar + email plugins (local files first, then OAuth)
- [ ] Phone dashboard (small web UI on localhost)
- [ ] Streaming replies in the HUD
- [ ] `llama.cpp` provider (GGUF, no server needed)

---

## License

AmbientOS Source-Available Licence v1.0 — see [LICENSE](LICENSE). Not affiliated with Marvel, Google, or
FatihMakes. Use responsibly: Jarvis can open apps and change system settings
only when you ask it to, and dangerous actions ask for confirmation first.

## AmbientOS trust gate (Layer 1 wiring)

Jarvis is Layer 1 (the face) of **AmbientOS**. Every tool execution now
passes through `core/trustgate.py` before it runs:

**Decide → Policy → Verify → Act.** The model proposes a tool call;
the gate maps it to a policy intent (the Layer-1-owned M1 mapping,
`TOOL_INTENTS`), asks **context-fabric** (Layer 2) for a signed
`policy_decision`, verifies the token's signature + expiry and the
capability membership (Layer 3 style), checks the device manifest
(`ambient/manifest.json` — sensitive tools such as `lock_screen` and
`fix_error` need `confirm=true`), and only then lets the tool run.
Every verdict is appended to `~/.jarvis/ambient_kyun.jsonl` — the
"Kyun?" reason log.

Config (`config.yaml`):

```yaml
ambient:
  trust_gate: audit   # off | audit (default, log-only) | enforce (block on DENY)
  user_role: OWNER    # OWNER | GUEST | UNKNOWN
  user_present: true
  state: HOME         # HOME | SLEEP | AWAY
```

Policies live in `ambient/policies.json` (context-fabric's schema,
evaluated by context-fabric's own `PolicyEvaluator` — Jarvis does not
evaluate policies itself). The fabric is found via
`$CONTEXT_FABRIC_PATH`, or automatically in the
[ambience-os](https://github.com/jawadahmadliaqat-dot/ambience-os)
layout (`layers/jarvis-assistant` next to `layers/context-fabric`).
Signing uses context-fabric's documented dev HMAC scheme unless
`CONTEXT_FABRIC_SIGNING_KEY` is set.
