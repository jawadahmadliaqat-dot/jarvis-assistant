@echo off
REM Jarvis setup — Windows (run from the jarvis folder)
REM Creates a venv, installs core deps, copies example config files.
cd /d "%~dp0"

py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt

if not exist config.yaml copy config.yaml.example config.yaml
if not exist .env copy .env.example .env

echo.
echo Jarvis is set up.
echo   1. Edit .env and add a GEMINI_API_KEY (free: https://aistudio.google.com/apikey)
echo      or run Ollama locally - or run with no key at all (offline mode).
echo   2. Text mode:   .venv\Scripts\python.exe main.py
echo   3. One command: .venv\Scripts\python.exe main.py --once "what time is it"
echo   4. Voice mode:  .venv\Scripts\python.exe main.py --voice   (needs mic + STT/TTS deps)
echo   5. HUD:         .venv\Scripts\python.exe main.py --gui     (needs PyQt6: pip install PyQt6)
echo   6. Briefing:    .venv\Scripts\python.exe main.py --briefing
