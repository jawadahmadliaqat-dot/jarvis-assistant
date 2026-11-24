"""Provider factory — builds the fallback chain from config."""

from __future__ import annotations

from core.config import Config
from providers.base import BaseProvider
from providers.gemini import GeminiProvider
from providers.ollama import OllamaProvider
from providers.openai_compat import OpenAICompatProvider

_BUILDERS = {
    "gemini": lambda cfg: GeminiProvider(
        model=cfg.provider_settings("gemini").get("model", "gemini-2.5-flash"),
        api_key=cfg.api_key(
            cfg.provider_settings("gemini").get("api_key_env", "GEMINI_API_KEY")
        ),
    ),
    "openai": lambda cfg: OpenAICompatProvider(
        model=cfg.provider_settings("openai").get("model", "gpt-4o-mini"),
        api_key=cfg.api_key(
            cfg.provider_settings("openai").get("api_key_env", "OPENAI_API_KEY")
        ),
        base_url=cfg.provider_settings("openai").get(
            "base_url", "https://api.openai.com/v1"
        ),
    ),
    "ollama": lambda cfg: OllamaProvider(
        model=cfg.provider_settings("ollama").get("model", "llama3.2:3b"),
        base_url=cfg.provider_settings("ollama").get(
            "base_url", "http://localhost:11434"
        ),
    ),
}


def build_provider_chain(config: Config) -> list[BaseProvider]:
    chain: list[BaseProvider] = []
    for name in config.provider_order:
        builder = _BUILDERS.get(name)
        if builder is None:
            continue
        try:
            chain.append(builder(config))
        except Exception:
            continue
    return chain
