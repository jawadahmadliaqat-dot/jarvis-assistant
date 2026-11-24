# JARVIS — a local, cross-platform personal AI assistant

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/Platform-Windows%20%7C%20Linux-lightgrey?logo=windows&logoColor=white" alt="Windows and Linux">
  <img src="https://img.shields.io/badge/License-MIT-green" alt="MIT License">
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
python main.py --briefing               # morning briefing and exit
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
gui/               PyQt6 animated HUD
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

MIT — see [LICENSE](LICENSE). Not affiliated with Marvel, Google, or
FatihMakes. Use responsibly: Jarvis can open apps and change system settings
only when you ask it to, and dangerous actions ask for confirmation first.
