from __future__ import annotations

import os
from pathlib import Path

import pytest

from config import find_config_file, load_settings


# Keys that could leak from a real .env and skew config resolution.
_HEALER_ENV_KEYS = (
    "AI_MODE",
    "FRAMEWORK",
    "LANGUAGE",
    "TEST_COMMAND",
    "RESULTS_DIR",
    "WORKERS",
    "PROJECT_ROOT",
    "PLAYWRIGHT_PROJECT_ROOT",
    "REPORTS_DIR",
    "HEALER_TEMP_DIR",
)


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _HEALER_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _write_yaml(directory: Path, text: str) -> Path:
    path = directory / "healer.yml"
    path.write_text(text, encoding="utf-8")
    return path


def test_load_settings_from_healer_yml(tmp_path: Path) -> None:
    _write_yaml(
        tmp_path,
        "framework: cypress\n"
        "language: javascript\n"
        "project_root: .\n"
        'test_command: "npx cypress run"\n'
        "results_dir: cypress/results\n"
        "workers: 8\n"
        "ai:\n"
        "  mode: ollama\n",
    )

    settings = load_settings(tmp_path)

    assert settings.framework == "cypress"
    assert settings.language == "javascript"
    assert settings.project_root == tmp_path.resolve()
    assert settings.test_command == "npx cypress run"
    assert settings.results_dir_name == "cypress/results"
    assert settings.workers == 8
    assert settings.ai_mode == "ollama"
    assert settings.results_dir == (tmp_path / "cypress/results").resolve()


def test_env_overrides_yaml(tmp_path: Path, monkeypatch) -> None:
    _write_yaml(tmp_path, "framework: cypress\nai:\n  mode: ollama\n")
    monkeypatch.setenv("AI_MODE", "azure-openai")
    monkeypatch.setenv("TEST_COMMAND", "custom test cmd")

    settings = load_settings(tmp_path)

    assert settings.ai_mode == "azure-openai"      # env wins over yaml
    assert settings.test_command == "custom test cmd"
    assert settings.framework == "cypress"         # yaml still used where no env


def test_find_config_walks_up(tmp_path: Path) -> None:
    _write_yaml(tmp_path, "framework: playwright\n")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)

    found = find_config_file(nested)

    assert found == (tmp_path / "healer.yml")


def test_defaults_without_config(tmp_path: Path) -> None:
    settings = load_settings(tmp_path)

    assert settings.framework == "playwright"
    assert settings.ai_mode == "rule"
    assert settings.results_dir_name == "test-results"
