"""Project-independent configuration for the AI auto-healer.

Settings are resolved with this precedence (highest first):

    1. Environment variables (ideal for CI secrets / overrides)
    2. ``healer.yml`` in the target project (committed, framework-specific)
    3. Built-in defaults

A ``healer.yml`` lets the tool run inside *any* test repository without
hardcoding paths or commands. Generate one with ``auto-healer init``.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

CONFIG_FILENAMES = ("healer.yml", "healer.yaml")


@dataclass(frozen=True)
class Settings:
    # --- Project / framework (the decoupling fields) ---
    project_root: Path = field(default_factory=Path.cwd)
    framework: str = "playwright"
    language: str = "typescript"
    test_command: str = "npx playwright test --trace on"
    results_dir_name: str = "test-results"
    workers: int | None = None

    # --- AI provider ---
    ai_mode: str = "rule"
    ollama_model: str = "qwen3:8b"
    ollama_url: str = "http://localhost:11434/api/generate"
    azure_openai_api_key: str | None = None
    azure_openai_endpoint: str | None = None
    azure_openai_deployment: str | None = None
    azure_openai_api_version: str = "2025-04-01-preview"
    kilo_api_key: str | None = None
    kilo_api_url: str = "https://api.kilo.ai/v1/messages"
    kilo_model: str = "claude-sonnet"

    # --- Working directories ---
    reports_dir: Path = field(default_factory=lambda: Path("reports").resolve())
    temp_dir: Path = field(default_factory=lambda: Path("trace-output").resolve())

    @property
    def results_dir(self) -> Path:
        """Where the test framework writes results / traces."""
        return (self.project_root / self.results_dir_name).resolve()

    @property
    def playwright_project_root(self) -> Path:
        """Backward-compatible alias for ``project_root``."""
        return self.project_root


# ── Loading ──────────────────────────────────────────────────────────────────


def find_config_file(start_dir: Path | None = None) -> Path | None:
    """Walk up from ``start_dir`` (or cwd) looking for a healer config file."""
    start = (start_dir or Path.cwd()).resolve()
    for directory in (start, *start.parents):
        for name in CONFIG_FILENAMES:
            candidate = directory / name
            if candidate.exists():
                return candidate
    return None


def _load_yaml(path: Path) -> dict:
    try:
        import yaml  # imported lazily so YAML is optional when no config file
    except ModuleNotFoundError as exc:  # pragma: no cover - defensive
        raise RuntimeError(
            "healer.yml found but PyYAML is not installed. Run: pip install pyyaml"
        ) from exc
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise RuntimeError(f"{path} must contain a YAML mapping")
    return data


def _first(*values: object) -> object | None:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def load_settings(start_dir: Path | None = None) -> Settings:
    """Resolve Settings from env vars, an optional ``healer.yml``, then defaults."""
    config_path = find_config_file(start_dir)
    data: dict = {}
    base_dir = (start_dir or Path.cwd()).resolve()
    if config_path is not None:
        data = _load_yaml(config_path)
        base_dir = config_path.parent

    ai_section = data.get("ai") if isinstance(data.get("ai"), dict) else {}

    # project_root: env > yaml > config-file dir.
    # Relative values resolve against the config file's directory.
    project_value = _first(
        os.getenv("PROJECT_ROOT"),
        os.getenv("PLAYWRIGHT_PROJECT_ROOT"),  # legacy
        data.get("project_root"),
    )
    if project_value:
        candidate = Path(str(project_value))
        project_root = (
            candidate.resolve()
            if candidate.is_absolute()
            else (base_dir / candidate).resolve()
        )
    else:
        project_root = base_dir

    workers_value = _first(os.getenv("WORKERS"), data.get("workers"))
    workers = int(workers_value) if workers_value is not None else None

    reports_value = _first(os.getenv("REPORTS_DIR"), data.get("reports_dir"), "reports")
    temp_value = _first(os.getenv("HEALER_TEMP_DIR"), data.get("temp_dir"), "trace-output")

    return Settings(
        project_root=project_root,
        framework=str(_first(os.getenv("FRAMEWORK"), data.get("framework"), "playwright")),
        language=str(_first(os.getenv("LANGUAGE"), data.get("language"), "typescript")),
        test_command=str(
            _first(
                os.getenv("TEST_COMMAND"),
                data.get("test_command"),
                "npx playwright test --trace on",
            )
        ),
        results_dir_name=str(
            _first(os.getenv("RESULTS_DIR"), data.get("results_dir"), "test-results")
        ),
        workers=workers,
        ai_mode=str(_first(os.getenv("AI_MODE"), ai_section.get("mode"), data.get("ai_mode"), "rule")),
        ollama_model=str(_first(os.getenv("OLLAMA_MODEL"), ai_section.get("ollama_model"), "qwen3:8b")),
        ollama_url=str(
            _first(
                os.getenv("OLLAMA_URL"),
                ai_section.get("ollama_url"),
                "http://localhost:11434/api/generate",
            )
        ),
        azure_openai_api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        azure_openai_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        azure_openai_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
        azure_openai_api_version=str(
            _first(os.getenv("AZURE_OPENAI_API_VERSION"), "2025-04-01-preview")
        ),
        kilo_api_key=os.getenv("KILO_API_KEY"),
        kilo_api_url=str(_first(os.getenv("KILO_API_URL"), "https://api.kilo.ai/v1/messages")),
        kilo_model=str(_first(os.getenv("KILO_MODEL"), ai_section.get("kilo_model"), "claude-sonnet")),
        reports_dir=Path(str(reports_value)).resolve(),
        temp_dir=Path(str(temp_value)).resolve(),
    )


# Module-level default, resolved from the current working directory.
settings = load_settings()