from __future__ import annotations

from config import settings

from .base import AIEngine
from .azure_openai_engine import AzureOpenAIEngine
from .kilo_engine import KiloEngine
from .ollama_engine import OllamaEngine
from .rule_engine import RuleEngine


def create_ai_engine() -> AIEngine:
    mode = settings.ai_mode.lower().strip()
    if mode == "rule":
        return RuleEngine()
    if mode == "ollama":
        return OllamaEngine(model=settings.ollama_model, url=settings.ollama_url)
    if mode == "azure-openai":
        missing = [
            name
            for name, value in {
                "AZURE_OPENAI_API_KEY": settings.azure_openai_api_key,
                "AZURE_OPENAI_ENDPOINT": settings.azure_openai_endpoint,
                "AZURE_OPENAI_DEPLOYMENT": settings.azure_openai_deployment,
            }.items()
            if not value
        ]
        if missing:
            raise RuntimeError(f"Missing Azure OpenAI settings: {', '.join(missing)}")
        return AzureOpenAIEngine(
            api_key=settings.azure_openai_api_key or "",
            endpoint=settings.azure_openai_endpoint or "",
            deployment=settings.azure_openai_deployment or "",
            api_version=settings.azure_openai_api_version,
        )
    if mode == "kilo":
        if not settings.kilo_api_key:
            raise RuntimeError("KILO_API_KEY must be set when AI_MODE=kilo")
        return KiloEngine(
            api_key=settings.kilo_api_key,
            model=settings.kilo_model,
            url=settings.kilo_api_url,
        )
    raise RuntimeError(f"Unsupported AI_MODE: {settings.ai_mode}")