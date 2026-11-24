#!/usr/bin/env python3
"""Jarvis — a local, cross-platform personal AI assistant.

Usage:
    python main.py                  interactive text chat
    python main.py --once "..."     one command, print the reply, exit
    python main.py --voice          microphone loop (needs STT/TTS)
    python main.py --gui            animated HUD (needs PyQt6)
    python main.py --briefing       morning briefing and exit
    python main.py --routine NAME   run a named routine and exit
    python main.py --routines       list configured routines
    python main.py --check          check for proactive alerts and exit
    python main.py --fix FILE       fix an error in a file (needs an LLM)
    python main.py --research "..." deep research report
    python main.py --task "..."     start a background task
    python main.py --tasks          list background tasks
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import __version__  # noqa: E402
from core.brain import Brain  # noqa: E402
from core.config import ensure_first_run, load_config  # noqa: E402
from core.logging_setup import setup_logging  # noqa: E402
from core.memory import Memory  # noqa: E402
from core.tasks import TaskManager  # noqa: E402
from tools.registry import ToolRegistry, load_all_tools  # noqa: E402


def bootstrap(config_path: str | None = None):
    """Load config, memory, tools, brain and task manager."""
    config = load_config(config_path)
    ensure_first_run(config)
    logger = setup_logging(config.data_dir)
    memory = Memory(config.data_dir)
    registry = ToolRegistry(logger)
    context = {
        "config": config,
        "memory": memory,
        "data_dir": config.data_dir,
        "logger": logger,
    }
    load_all_tools(registry, context)
    brain = Brain(config, memory, registry, logger)
    tasks = TaskManager(config.data_dir, logger)
    brain.task_manager = tasks  # type: ignore[attr-defined]
    context["brain"] = brain
    context["tasks"] = tasks
    logger.info(
        "Jarvis %s started. Tools: %d. Providers: %s.",
        __version__, len(registry.all_tools()), config.provider_order,
    )
    return config, logger, memory, registry, brain, tasks, context


def make_task_runner(context):
    def runner(task, progress, stop_event):
        kind, desc = task["kind"], task["description"]
        if kind == "research":
            from tools.research import deep_research

            progress("searching sources…")
            return deep_research(context, desc)
        if kind == "briefing":
            from tools.briefing import morning_briefing

            return morning_briefing(context)
        return context["brain"].respond(desc)

    return runner


def repl(brain, config, speak: bool = False):
    tts = None
    if speak:
        from voice.tts import TTS

        tts = TTS(engine=config.get("voice", "tts_engine", default="auto"))
    print(
        f"{config.assistant_name} online. Type /help for commands, /exit to quit. "
        f"(Provider: {brain.active_provider_name} — offline mode works with no keys.)"
    )
    while True:
        try:
            text = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye, sir.")
            break
        if not text:
            continue
        low = text.lower()
        if low in ("/exit", "/quit", "exit", "quit"):
            print("Goodbye, sir.")
            break
        if low == "/help":
            print(
                "/help — this list\n"
                "/briefing — morning briefing\n"
                "/tasks — background tasks\n"
                "/provider — which LLM provider is active\n"
                "/exit — quit"
            )
            continue
        if low == "/briefing":
            print(brain.tool_result_text("morning_briefing", {}))
            continue
        if low == "/tasks":
            tasks = brain.task_manager.list_tasks()
            print("No background tasks." if not tasks else "\n".join(
                f"{t['id']} [{t['status']}] {t['description']} — {t.get('progress', '')}"
                for t in tasks
            ))
            continue
        if low == "/provider":
            print(f"Active provider: {brain.active_provider_name}")
            continue
        reply = brain.respond(text)
        print(f"{config.assistant_name}: {reply}")
        if tts:
            tts.speak(reply)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="jarvis", description="Jarvis — local personal AI assistant"
    )
    parser.add_argument("--config", help="path to config.yaml")
    parser.add_argument("--gui", action="store_true", help="animated HUD (needs PyQt6)")
    parser.add_argument("--voice", action="store_true", help="microphone loop")
    parser.add_argument("--once", metavar="TEXT", help="one command, print reply, exit")
    parser.add_argument("--speak", action="store_true", help="speak replies (text/once mode)")
    parser.add_argument("--briefing", action="store_true", help="morning briefing and exit")
    parser.add_argument("--routine", metavar="NAME", help="run a named routine and exit")
    parser.add_argument("--routines", action="store_true", help="list configured routines and exit")
    parser.add_argument("--check", action="store_true", help="check for proactive alerts and exit")
    parser.add_argument("--fix", metavar="FILE", help="fix an error in a file (needs an LLM; offline says so)")
    parser.add_argument("--error", metavar="TEXT", help="error traceback text for --fix")
    parser.add_argument("--verify", metavar="CMD", help="verification command for --fix")
    parser.add_argument("--confirm", action="store_true", help="confirm applying a risky fix with --fix")
    parser.add_argument("--research", metavar="TOPIC", help="deep research report and exit")
    parser.add_argument("--task", metavar="DESC", help="start a background task")
    parser.add_argument("--tasks", action="store_true", help="list background tasks")
    parser.add_argument("--version", action="store_true", help="print version and exit")
    args = parser.parse_args(argv)

    if args.version:
        print(f"Jarvis {__version__}")
        return 0

    config, _logger, _memory, _registry, brain, tasks, context = bootstrap(args.config)

    if args.briefing:
        print(brain.tool_result_text("morning_briefing", {}))
        return 0
    if args.routines:
        from core.routines import RoutineRunner

        print(RoutineRunner(config, _registry, context).list_routines())
        return 0
    if args.routine:
        from core.routines import RoutineRunner

        print(RoutineRunner(config, _registry, context).run(args.routine))
        return 0
    if args.check:
        from core.proactive import ProactiveChecker

        alerts = ProactiveChecker(
            config, _memory, tasks=tasks
        ).check(respect_quiet_hours=False)
        if alerts:
            print("\n".join(alerts))
        else:
            print("Nothing needs your attention right now.")
        return 0
    if args.fix:
        import subprocess

        from tools.doctor import fix_error

        error = (args.error or "").strip()
        if not error:
            # No traceback given: compile the file and use its error.
            result = subprocess.run(
                [sys.executable, "-m", "py_compile", args.fix],
                capture_output=True, text=True,
            )
            error = (result.stdout + result.stderr).strip()
            if result.returncode == 0:
                print(f"{args.fix} compiles cleanly — nothing to fix.")
                return 0
        print(fix_error(context, error, args.fix, args.verify, args.confirm))
        return 0
    if args.research:
        from tools.research import deep_research

        print(deep_research(context, args.research))
        return 0
    if args.task:
        import time

        kind = "research" if args.task.lower().startswith("research ") else "custom"
        desc = args.task[len("research "):] if kind == "research" else args.task
        task = tasks.create(kind, desc)
        tasks.start(task["id"], make_task_runner(context))
        print(f"Background task {task['id']} started: {desc}")
        # A one-shot CLI process would exit and kill its own worker thread,
        # so --task waits for completion (in the REPL/GUI the task runs
        # beside the conversation instead).
        last_progress = ""
        for _ in range(300):  # up to ~10 minutes
            current = tasks.get(task["id"])
            if current is None:
                break
            if current.get("progress") and current["progress"] != last_progress:
                last_progress = current["progress"]
                print(f"  ... {last_progress}")
            if current["status"] in ("done", "failed", "cancelled"):
                print(f"Task {task['id']} {current['status']}.")
                if current.get("result"):
                    print(current["result"])
                return 0
            time.sleep(2)
        print(f"Task {task['id']} is still running — check with: python main.py --tasks")
        return 0
    if args.tasks:
        items = tasks.list_tasks()
        if not items:
            print("No background tasks.")
        else:
            for t in items:
                print(f"{t['id']} [{t['status']}] {t['description']} — {t.get('progress', '')}")
                if t.get("result"):
                    print(f"    -> {t['result'][:300]}")
        return 0
    if args.once is not None:
        reply = brain.respond(args.once)
        print(f"{config.assistant_name}: {reply}")
        if args.speak:
            from voice.tts import TTS

            TTS(engine=config.get("voice", "tts_engine", default="auto")).speak(reply)
        return 0
    if args.gui:
        from gui.hud import gui_available, run_hud

        if not gui_available():
            print("The HUD needs PyQt6: pip install PyQt6 (and a display).")
            print("Text mode still works: python main.py")
            return 2
        tts = None
        if config.get("voice", "speak_replies", default=True):
            from voice.tts import TTS

            tts = TTS(engine=config.get("voice", "tts_engine", default="auto"))
        return run_hud(brain, config, tts=tts)
    if args.voice:
        from voice.listener import VoiceLoop

        VoiceLoop(brain, config).run()
        return 0

    repl(brain, config, speak=args.speak)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
