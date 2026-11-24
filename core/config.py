"""Configuration loading: config.yaml + .env, with sane defaults.

Secrets NEVER live in config.yaml — only in the environment or `.env`
(both git-ignored). The config only names *which* env var holds a key.
"""

from __future__ import annotations

import os
import sys
from copy import deepcopy
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML is a core dep
    yaml = None

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULTS = {
    "assistant": {
        "name": "Jarvis",
        "owner": "Sir",
        "language": "en",
        "timezone": "Asia/Karachi",
        "city": "Lahore",
    },
    "providers": {
        "order": ["gemini", "openai", "ollama"],
        "gemini": {"model": "gemini-2.5-flash", "api_key_env": "GEMINI_API_KEY"},
        "openai": {
            "model": "gpt-4o-mini",
            "base_url": "https://api.openai.com/v1",
            "api_key_env": "OPENAI_API_KEY",
        },
        "ollama": {"model": "llama3.2:3b", "base_url": "http://localhost:11434"},
    },
    "voice": {
        "tts_engine": "auto",
        "tts_rate": 175,
        "tts_voice": "",
        "stt_engine": "auto",
        "wake_word": "off",
        "push_to_talk": False,
        "speak_replies": True,
    },
    "gui": {"theme": "arc", "refresh_ms": 1000},
    "paths": {"data_dir": "~/.jarvis"},
    "memory": {"max_history": 20, "remember_facts": True},
    "routines": {"quiet_hours": ["23:00", "07:00"]},
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_dotenv(path: Path | None = None) -> None:
    """Minimal .env loader (no python-dotenv dependency).

    Sets variables only if they are not already in the environment.
    """
    path = path or (PROJECT_ROOT / ".env")
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def find_config(explicit: str | None = None) -> Path | None:
    if explicit:
        p = Path(explicit).expanduser()
        return p if p.exists() else None
    if os.environ.get("JARVIS_CONFIG"):
        p = Path(os.environ["JARVIS_CONFIG"]).expanduser()
        if p.exists():
            return p
    for cand in (
        PROJECT_ROOT / "config.yaml",
        Path.home() / ".config" / "jarvis" / "config.yaml",
        Path.home() / ".jarvis" / "config.yaml",
    ):
        if cand.exists():
            return cand
    return None


class Config:
    """Loaded configuration. Attribute access mirrors the YAML tree."""

    def __init__(self, data: dict, source: Path | None = None):
        self._data = _deep_merge(DEFAULTS, data or {})
        self.source = source

    # -- generic access -------------------------------------------------
    def get(self, *keys, default=None):
        node = self._data
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    def __getitem__(self, key):
        return self._data[key]

    # -- typed shortcuts ------------------------------------------------
    @property
    def assistant_name(self) -> str:
        return str(self.get("assistant", "name", default="Jarvis"))

    @property
    def owner(self) -> str:
        return str(self.get("assistant", "owner", default="Sir"))

    @property
    def language(self) -> str:
        return str(self.get("assistant", "language", default="en"))

    @property
    def timezone(self) -> str:
        return str(self.get("assistant", "timezone", default="Asia/Karachi"))

    @property
    def city(self) -> str:
        return str(self.get("assistant", "city", default="Lahore"))

    @property
    def data_dir(self) -> Path:
        return Path(
            os.path.expanduser(
                str(self.get("paths", "data_dir", default="~/.jarvis"))
            )
        )

    @property
    def max_history(self) -> int:
        return int(self.get("memory", "max_history", default=20))

    @property
    def provider_order(self) -> list[str]:
        order = self.get("providers", "order", default=["gemini", "openai", "ollama"])
        return [str(x) for x in order]

    def provider_settings(self, name: str) -> dict:
        return dict(self.get("providers", name, default={}) or {})

    def api_key(self, env_var: str) -> str:
        return os.environ.get(env_var, "").strip()


def load_config(explicit: str | None = None) -> Config:
    """Load .env (project root, then data dir) and config.yaml."""
    load_dotenv()
    cfg_path = find_config(explicit)
    data: dict = {}
    if cfg_path is not None:
        text = cfg_path.read_text(encoding="utf-8")
        if yaml is not None:
            data = yaml.safe_load(text) or {}
        else:  # pragma: no cover - fallback if PyYAML missing
            data = _tiny_yaml(text)
    return Config(data, source=cfg_path)


def _tiny_yaml(text: str) -> dict:
    """Very small YAML subset parser (2-level maps, scalars, lists).

    Only used when PyYAML is unavailable. Handles the shape of
    config.yaml.example; anything fancier needs PyYAML installed.
    """
    root: dict = {}
    stack: list[tuple[int, dict]] = [(0, root)]
    current_list_key: tuple[dict, str] | None = None
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        if line.startswith("- "):
            if current_list_key is not None:
                parent, key = current_list_key
                parent.setdefault(key, []).append(_scalar(line[2:].strip()))
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().strip('"').strip("'")
        value = value.strip()
        while stack and indent < stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if value == "":
            child: dict = {}
            parent[key] = child
            stack.append((indent + 2, child))
            current_list_key = None
        else:
            parent[key] = _scalar(value)
            current_list_key = (parent, key) if value.startswith("[") else None
    return root


def _scalar(value: str):
    value = value.strip()
    if value in ("true", "True"):
        return True
    if value in ("false", "False"):
        return False
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        return [_scalar(v) for v in inner.split(",")] if inner else []
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value.strip('"').strip("'")


def ensure_first_run(config: Config) -> None:
    """Create data dir and copy example config if nothing exists yet."""
    config.data_dir.mkdir(parents=True, exist_ok=True)
    if config.source is None:
        example = PROJECT_ROOT / "config.yaml.example"
        if example.exists():
            (PROJECT_ROOT / "config.yaml").write_text(
                example.read_text(encoding="utf-8"), encoding="utf-8"
            )
            print(
                "Created config.yaml from the example — edit it and .env "
                "to add API keys (or run with no keys in offline mode)."
            )
    if not (PROJECT_ROOT / ".env").exists():
        example = PROJECT_ROOT / ".env.example"
        if example.exists():
            (PROJECT_ROOT / ".env").write_text(
                example.read_text(encoding="utf-8"), encoding="utf-8"
            )


if __name__ == "__main__":
    cfg = load_config()
    print("config source:", cfg.source)
    print("assistant:", cfg.assistant_name, "| owner:", cfg.owner)
    print("providers:", cfg.provider_order)
    print("data dir:", cfg.data_dir)
    print("gemini key set:", bool(cfg.api_key("GEMINI_API_KEY")))
    print("openai key set:", bool(cfg.api_key("OPENAI_API_KEY")))
