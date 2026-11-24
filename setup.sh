#!/usr/bin/env bash
# Jarvis setup — Linux / macOS
# Creates a venv, installs core deps, copies example config files.
set -e
cd "$(dirname "$0")"

python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

[ -f config.yaml ] || cp config.yaml.example config.yaml
[ -f .env ] || cp .env.example .env

echo ""
echo "Jarvis is set up."
echo "  1. Edit .env and add a GEMINI_API_KEY (free: https://aistudio.google.com/apikey)"
echo "     or run Ollama locally — or run with no key at all (offline mode)."
echo "  2. Text mode:   .venv/bin/python main.py"
echo "  3. One command: .venv/bin/python main.py --once \"what time is it\""
echo "  4. Voice mode:  .venv/bin/python main.py --voice   (needs mic + STT/TTS deps)"
echo "  5. HUD:         .venv/bin/python main.py --gui     (needs PyQt6: pip install PyQt6)"
echo "  6. Briefing:    .venv/bin/python main.py --briefing"
