"""System control — info, apps, websites, volume, brightness, clipboard,
screenshots, media keys. Everything is best-effort and reports what it
actually observed; missing optional libraries produce a clear message,
never a crash. Dangerous actions (lock, shutdown) need confirm=true.
"""

from __future__ import annotations

import datetime
import os
import platform
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Any

from tools.registry import Tool, ToolRegistry

APP_ALIASES = {
    "notepad": {"win32": ["notepad.exe"], "linux": ["gedit", "kate", "mousepad"]},
    "calculator": {"win32": ["calc.exe"], "linux": ["gnome-calculator", "kcalc"]},
    "chrome": {"win32": ["chrome.exe"], "linux": ["google-chrome", "chromium"]},
    "firefox": {"win32": ["firefox.exe"], "linux": ["firefox"]},
    "vscode": {"win32": ["code.exe"], "linux": ["code"]},
    "code": {"win32": ["code.exe"], "linux": ["code"]},
    "terminal": {"win32": ["wt.exe", "cmd.exe"], "linux": ["gnome-terminal", "konsole", "xterm"]},
    "explorer": {"win32": ["explorer.exe"], "linux": ["nautilus", "dolphin", "thunar"]},
    "files": {"win32": ["explorer.exe"], "linux": ["nautilus", "dolphin", "thunar"]},
    "spotify": {"win32": ["spotify.exe"], "linux": ["spotify"]},
}


def _psutil():
    try:
        import psutil  # type: ignore

        return psutil
    except ImportError:
        return None


def system_info() -> str:
    """CPU, RAM, disk, uptime, OS — what the machine looks like now."""
    psutil = _psutil()
    lines = [
        f"OS: {platform.system()} {platform.release()} ({platform.machine()})",
        f"Python: {platform.python_version()}",
    ]
    if psutil is not None:
        boot = datetime.datetime.fromtimestamp(psutil.boot_time())
        up = datetime.datetime.now() - boot
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        lines += [
            f"CPU: {psutil.cpu_percent(interval=0.2):.0f}% "
            f"({psutil.cpu_count()} cores)",
            f"RAM: {mem.percent:.0f}% used "
            f"({mem.used // 1024**2} MB / {mem.total // 1024**2} MB)",
            f"Disk: {disk.percent:.0f}% used "
            f"({disk.used // 1024**3} GB / {disk.total // 1024**3} GB free "
            f"{disk.free // 1024**3} GB)",
            f"Uptime: {str(up).split('.')[0]}",
        ]
        try:
            batt = psutil.sensors_battery()
            if batt is not None:
                lines.append(
                    f"Battery: {batt.percent:.0f}%"
                    f"{' (charging)' if batt.power_plugged else ''}"
                )
        except Exception:
            pass
    else:
        lines.append("psutil is not installed — install it for CPU/RAM details.")
    return "\n".join(lines)


def open_app(app: str) -> str:
    """Launch an application by name (notepad, chrome, vscode, ...)."""
    key = app.strip().lower()
    # Well-known websites: "open youtube" means the site, not an app.
    sites = {
        "youtube": "https://www.youtube.com",
        "google": "https://www.google.com",
        "gmail": "https://mail.google.com",
        "github": "https://github.com",
        "facebook": "https://www.facebook.com",
        "instagram": "https://www.instagram.com",
        "reddit": "https://www.reddit.com",
        "stackoverflow": "https://stackoverflow.com",
        "x": "https://x.com",
        "twitter": "https://x.com",
        "wikipedia": "https://www.wikipedia.org",
    }
    if key in sites:
        return open_website(sites[key])
    plat = "win32" if sys.platform.startswith("win") else "linux"
    candidates = APP_ALIASES.get(key, {}).get(plat, [])
    if not candidates:
        candidates = [app]
    for cand in candidates:
        path = shutil.which(cand)
        if path is None and plat == "win32":
            # Windows apps are often on PATH without extension resolution.
            path = cand
        if path is None:
            continue
        try:
            if plat == "win32":
                subprocess.Popen([path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.Popen(
                    [path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            return f"Opened {app}."
        except Exception as exc:  # noqa: BLE001
            return f"Could not open {app}: {exc}"
    return f"Could not find an app called '{app}' on this system."


def open_website(url: str) -> str:
    """Open a URL in the default browser."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        ok = webbrowser.open(url)
        return f"Opened {url} in the browser." if ok else f"Could not open {url}."
    except Exception as exc:  # noqa: BLE001
        return f"Could not open {url}: {exc}"


def set_volume(level: int) -> str:
    """Set the system volume (0-100)."""
    level = max(0, min(100, int(level)))
    if sys.platform.startswith("win"):
        try:
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume  # type: ignore
            from comtypes import CLSCTX_ALL  # type: ignore

            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(
                IAudioEndpointVolume._iid_, CLSCTX_ALL, None
            )
            volume = interface.QueryInterface(IAudioEndpointVolume)
            volume.SetMasterVolumeLevelScalar(level / 100.0, None)
            return f"Volume set to {level}%."
        except ImportError:
            return "Volume control on Windows needs pycaw: pip install pycaw."
        except Exception as exc:  # noqa: BLE001
            return f"Could not set volume: {exc}"
    for cmd in (
        ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{level}%"],
        ["amixer", "-D", "pulse", "sset", "Master", f"{level}%"],
    ):
        if shutil.which(cmd[0]):
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                return f"Volume set to {level}%."
    return "No volume backend found (pactl or amixer)."


def set_brightness(level: int) -> str:
    """Set screen brightness (0-100)."""
    level = max(0, min(100, int(level)))
    try:
        import screen_brightness_control as sbc  # type: ignore

        sbc.set_brightness(level)
        return f"Brightness set to {level}%."
    except ImportError:
        pass
    except Exception as exc:  # noqa: BLE001
        return f"Could not set brightness: {exc}"
    if shutil.which("brightnessctl"):
        r = subprocess.run(
            ["brightnessctl", "set", f"{level}%"], capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0:
            return f"Brightness set to {level}%."
    return "Brightness control needs screen-brightness-control or brightnessctl."


def lock_screen(confirm: bool = False) -> str:
    """Lock the screen. Requires confirm=true."""
    if not confirm:
        return "Locking the screen needs confirmation — say 'yes, lock it'."
    try:
        if sys.platform.startswith("win"):
            subprocess.run(
                ["rundll32.exe", "user32.dll,LockWorkStation"], timeout=10
            )
        elif shutil.which("loginctl"):
            subprocess.run(["loginctl", "lock-session"], timeout=10)
        elif shutil.which("gnome-screensaver-command"):
            subprocess.run(["gnome-screensaver-command", "-l"], timeout=10)
        else:
            return "No screen-lock command found on this system."
        return "Screen locked."
    except Exception as exc:  # noqa: BLE001
        return f"Could not lock the screen: {exc}"


def take_screenshot(context: dict[str, Any]) -> str:
    """Save a screenshot to the data dir and return its path."""
    data_dir = Path(context["data_dir"])
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / f"screenshot_{time.strftime('%Y%m%d_%H%M%S')}.png"
    try:
        from PIL import ImageGrab  # type: ignore

        ImageGrab.grab().save(path)
        return f"Screenshot saved to {path}."
    except ImportError:
        pass
    except Exception as exc:  # noqa: BLE001
        return f"Screenshot failed: {exc}"
    for cmd in (["scrot", str(path)], ["gnome-screenshot", "-f", str(path)]):
        if shutil.which(cmd[0]):
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if r.returncode == 0 and path.exists():
                return f"Screenshot saved to {path}."
    return "Screenshots need Pillow (pip install Pillow) or scrot."


def clipboard_copy(text: str) -> str:
    """Copy text to the clipboard."""
    try:
        import pyperclip  # type: ignore

        pyperclip.copy(text)
        return "Copied to clipboard."
    except ImportError:
        pass
    try:
        import tkinter  # noqa: F401

        root = tkinter.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        root.destroy()
        return "Copied to clipboard."
    except Exception as exc:  # noqa: BLE001
        return f"Clipboard failed: {exc}"


def clipboard_paste() -> str:
    """Read the clipboard."""
    try:
        import pyperclip  # type: ignore

        return f"Clipboard: {pyperclip.paste()}"
    except ImportError:
        pass
    try:
        import tkinter  # noqa: F401

        root = tkinter.Tk()
        root.withdraw()
        text = root.clipboard_get()
        root.destroy()
        return f"Clipboard: {text}"
    except Exception as exc:  # noqa: BLE001
        return f"Clipboard read failed: {exc}"


def media_control(action: str) -> str:
    """Media keys: play_pause, next, previous."""
    action = action.strip().lower()
    if action not in ("play_pause", "next", "previous"):
        return "Media action must be play_pause, next or previous."
    if shutil.which("playerctl"):
        cmd = {"play_pause": "play-pause", "next": "next", "previous": "previous"}[action]
        r = subprocess.run(["playerctl", cmd], capture_output=True, text=True, timeout=10)
        return f"Media: {action}." if r.returncode == 0 else f"playerctl failed: {r.stderr.strip()}"
    try:
        import pyautogui  # type: ignore

        key = {"play_pause": "playpause", "next": "nexttrack", "previous": "prevtrack"}[action]
        pyautogui.press(key)
        return f"Media: {action}."
    except ImportError:
        return "Media control needs playerctl (Linux) or pyautogui."
    except Exception as exc:  # noqa: BLE001
        return f"Media control failed: {exc}"


def register(registry: ToolRegistry, context: dict[str, Any]) -> None:
    def _tool(name, desc, props, required, func):
        registry.register(
            Tool(name=name, description=desc,
                 parameters={"type": "object", "properties": props, "required": required},
                 func=func)
        )

    _tool("system_info", "CPU, RAM, disk, uptime and OS details.",
          {}, [], system_info)
    _tool("open_app", "Launch an application by name (notepad, chrome, vscode, calculator...).",
          {"app": {"type": "string"}}, ["app"], open_app)
    _tool("open_website", "Open a URL in the default browser.",
          {"url": {"type": "string"}}, ["url"], open_website)
    _tool("set_volume", "Set system volume, 0-100.",
          {"level": {"type": "integer"}}, ["level"], set_volume)
    _tool("set_brightness", "Set screen brightness, 0-100.",
          {"level": {"type": "integer"}}, ["level"], set_brightness)
    _tool("lock_screen", "Lock the screen. Requires confirm=true.",
          {"confirm": {"type": "boolean"}}, [], lambda confirm=False: lock_screen(confirm))
    _tool("take_screenshot", "Save a screenshot to the data dir.",
          {}, [], lambda: take_screenshot(context))
    _tool("clipboard_copy", "Copy text to the clipboard.",
          {"text": {"type": "string"}}, ["text"], clipboard_copy)
    _tool("clipboard_paste", "Read the clipboard.",
          {}, [], clipboard_paste)
    _tool("media_control", "Media keys: play_pause, next, previous.",
          {"action": {"type": "string"}}, ["action"], media_control)
