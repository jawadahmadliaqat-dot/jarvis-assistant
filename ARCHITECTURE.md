# Jarvis — Architecture

A local, cross-platform (Windows + Linux) personal AI assistant with a real
tool-use loop, swappable LLM providers, voice, an animated HUD, persistent
memory, background tasks, and a drop-in plugin system. No paid service is
required to run it: with no API key it works in offline mode (local tools
still answer).

## What it is not

This is an **original implementation** written from scratch. It is inspired
by the *idea* of Jarvis-style assistants (including FatihMakes' Mark 57
series, which the user asked us to beat) but shares no code with them. It is
not affiliated with Marvel, Google, or FatihMakes.

## Layout

```
main.py                 CLI/GUI entry point (argparse)
core/
  config.py             config.yaml + .env loading, provider chain resolution
  logging_setup.py      rotating file log + console
  memory.py             SQLite memory: facts, conversation history, reminders
  brain.py              the tool-use loop (provider -> tool -> provider ...)
  tasks.py              persistent background tasks (JSON, resumable)
providers/
  base.py               Provider interface + ProviderResponse
  gemini.py             Google Gemini via REST (function calling)
  openai_compat.py      OpenAI / Groq / DeepSeek / OpenRouter via /chat/completions
  ollama.py             local Ollama via /api/chat (+ /v1 fallback)
  offline.py            no-LLM keyword router -> local tools (works with no keys)
voice/
  stt.py                speech-to-text (faster-whisper local, else Google web)
  tts.py                text-to-speech (pyttsx3 offline, else edge-tts, else print)
  wakeword.py           wake word (openWakeWord "hey_jarvis", else Porcupine)
  listener.py           voice loop: wake word / push-to-talk / continuous
tools/
  registry.py           tool registry + schema validation + dispatch
  search.py             DuckDuckGo web search + news (no key)
  weather.py            Open-Meteo geocoding + forecast (no key)
  system.py             system info, open apps/sites, volume, brightness, screenshot
  files.py              file search / read / list
  notes.py              persistent notes (JSON)
  reminders.py          reminders (SQLite, due checks)
  timecalc.py           time/date, safe calculator
  briefing.py           morning briefing (time, weather, reminders, news)
  research.py           deep research: multi-search, fetch, quote-check, report
gui/
  hud.py                PyQt6 command-center HUD (reactor, waveform, gauges, log)
plugins/
  hello.py              example plugin (greeting tool)
  timer.py              example plugin (countdown timer tool)
tests/
  test_smoke.py         unittest smoke tests (no network needed)
```

## Request flow (text)

```
user text ──> Brain.respond()
   ├─ build messages: system prompt (identity, tools, memory facts, date/time)
   │   + recent conversation history (SQLite, capped by config)
   ├─ for step in 1..MAX_STEPS:
   │    ├─ provider = first available in chain (gemini → openai → ollama)
   │    ├─ provider.chat(messages, tool_schemas) → text and/or tool_calls
   │    ├─ if no tool_calls: break, reply = text
   │    └─ for each tool_call: registry.execute(name, args) → result
   │         append {"role": "tool", ...} and continue
   └─ save turn to memory, speak (if voice on), return reply
```

If every provider fails (no key, no network, Ollama down) the **offline
provider** answers instead: it routes the text to local tools by keyword
(time, calculator, weather, search, notes, reminders, briefing, files) and
says plainly that it is offline. The assistant never crashes for lack of a
key.

## Provider chain

Configured in `config.yaml` (`providers.order`) and resolved at runtime:

1. **Gemini** — REST `generateContent` with `functionDeclarations`.
   Key from `GEMINI_API_KEY` (env or `.env`). Free tier is enough for daily use.
2. **OpenAI-compatible** — `POST {base_url}/chat/completions` with `tools`.
   Works with OpenAI, Groq, DeepSeek, OpenRouter, LM Studio, vLLM…
3. **Ollama** — local, free, CPU-friendly small models
   (`llama3.2:3b` default). `POST /api/chat` with tools; falls back to the
   OpenAI-compatible `/v1/chat/completions` endpoint Ollama also serves.
4. **Offline** — built-in, always available, no network, no model.

Each provider implements `available() -> (bool, reason)` and
`chat(messages, tools) -> ProviderResponse`. Adding a provider means adding
one file that implements those two methods and one line in
`providers/__init__.py`.

## Tool system

A tool is a plain Python function plus an OpenAI-style JSON schema:

```python
Tool(
    name="web_search",
    description="Search the web and return titles, URLs and snippets.",
    parameters={"type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"]},
    func=web_search,
)
```

`tools/registry.py` validates required arguments, catches exceptions, and
returns a string result to the LLM. Tool modules register themselves on
import; `plugins/` files are auto-loaded the same way (see below). The LLM
never runs arbitrary code — it can only call registered tools, and the
dangerous ones (open app, lock screen, shutdown) confirm via a `confirm`
argument or are refused in GUI text mode without confirmation.

## Memory

SQLite at `<data_dir>/memory.db`:

- `facts(key, value, updated_at)` — user facts/preferences
  (`remember that ...` / the `remember_fact` tool).
- `conversations(id, role, content, ts)` — full history; the brain injects
  the last N turns into the prompt (sliding window, `memory.max_history`).
- `reminders(id, text, due_ts, done, created_ts)` — due reminders are
  checked on every turn and announced.

Notes live in `<data_dir>/notes.json` (human-readable, easy to back up).
Background tasks live in `<data_dir>/tasks.json`.

## Voice pipeline

```
mic ──> STT (faster-whisper local, else Google web speech)
      ──> Brain.respond() ──> TTS (pyttsx3 offline, else edge-tts)
wake word: openWakeWord "hey_jarvis" (or Porcupine "jarvis") — optional
fallback: push-to-talk (Ctrl+Space in GUI) or continuous listen
```

Every stage is optional and degrades: no mic → text box still works; no TTS
→ replies print; no wake word → press-to-talk. The GUI shows the current
state (idle / listening / thinking / speaking) in the reactor colour.

## Background tasks

`core/tasks.py` persists tasks in `tasks.json`. A task is a description +
kind (`research`, `briefing`, …) run in a worker thread. Status is queryable
(`jarvis --tasks`, or the `task_status` tool). On restart, tasks that were
`running` are marked `interrupted` and can be resumed — long work survives
a crash, like Mark 57's background tasks, but with an explicit resume step
instead of silent auto-resume (safer: nothing re-runs without the user
knowing).

## Deep research

`tools/research.py` (`deep_research` tool, also `jarvis --research "topic"`):

1. 3–5 search queries (topic + angles) via `web_search`.
2. Fetch the top pages, strip HTML to text.
3. Extract candidate quotes; **verify each quote appears verbatim** in the
   fetched page text — unverified quotes are dropped, never invented.
4. Write a cited Markdown report to `data/research/<slug>.md` and return
   its path + a short summary.

## GUI (HUD)

`gui/hud.py` (PyQt6, optional). One window:

- **Reactor** — QPainter-drawn rotating rings + pulsing core; colour =
  state (cyan idle, amber listening, green thinking, orange speaking).
- **Waveform** — live audio-level bars while speaking/listening.
- **Systems panel** — CPU %, RAM %, disk, uptime (psutil), provider in use.
- **Log** — timestamped transcript of everything Jarvis does.
- **Command input** — type, or hold the mic button for push-to-talk.
- **Controls** — Briefing, Tasks, Mute, Wake-word on/off.

The brain runs in a `QThread` so the UI never freezes. If PyQt6 is absent,
`--gui` prints a clear install hint and exits; CLI still works.

## Plugins

Drop a `.py` file into `plugins/`. It must define either:

```python
TOOLS = [Tool(...), ...]          # simplest
# or
def register(registry): ...       # full control
```

Plugins load on startup, appear in the LLM's tool list, and are listed in
the HUD log. Example plugins ship in `plugins/hello.py` and
`plugins/timer.py`.

## Security / honesty rules built in

- No secrets in code or config: keys only via env/`.env`, both git-ignored.
- Dangerous actions (shutdown, lock, delete) need explicit confirmation.
- Tool results are reported as observed (`done` only when verified).
- The assistant says when it is offline, when a provider failed, and when
  a result is unverified — it never invents a success.
- No telemetry, no cloud account, no data leaves the machine except to the
  provider / free APIs the user configured.
