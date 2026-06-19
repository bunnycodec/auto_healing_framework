from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    ai_mode: str = os.getenv("AI_MODE", "rule")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "qwen3:8b")
    ollama_url: str = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
    azure_openai_api_key: str | None = os.getenv("AZURE_OPENAI_API_KEY")
    azure_openai_endpoint: str | None = os.getenv("AZURE_OPENAI_ENDPOINT")
    azure_openai_deployment: str | None = os.getenv("AZURE_OPENAI_DEPLOYMENT")
    azure_openai_api_version: str = os.getenv("AZURE_OPENAI_API_VERSION", "2025-04-01-preview")
    kilo_api_key: str | None = os.getenv("KILO_API_KEY")
    kilo_api_url: str = os.getenv("KILO_API_URL", "https://api.kilo.ai/v1/messages")
    kilo_model: str = os.getenv("KILO_MODEL", "claude-sonnet")
    playwright_project_root: Path = Path(
        os.getenv("PLAYWRIGHT_PROJECT_ROOT", "playwright-tests")
    ).resolve()
    test_command: str = os.getenv(
        "TEST_COMMAND", "npx playwright test --grep @smoke --trace on"
    )
    reports_dir: Path = Path(os.getenv("REPORTS_DIR", "reports")).resolve()
    temp_dir: Path = Path(os.getenv("HEALER_TEMP_DIR", "trace-output")).resolve()


settings = Settings()