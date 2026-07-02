from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

from bs4 import BeautifulSoup

from .classifier import FailureClassifier
from .models import FailureContext


ERROR_CONTEXT_NAME = "error-context.md"
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


class FailureDetector:
    def __init__(self) -> None:
        self.classifier = FailureClassifier()

    def from_trace(self, trace_zip: Path, temp_dir: Path) -> FailureContext:
        temp_dir.mkdir(parents=True, exist_ok=True)
        extract_dir = temp_dir / trace_zip.stem
        if extract_dir.exists():
            for child in extract_dir.rglob("*"):
                if child.is_file():
                    child.unlink()
        extract_dir.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(trace_zip, "r") as archive:
            archive.extractall(extract_dir)

        # Primary source: error-context.md (clean, human readable).
        error_message = self._read_error_context(trace_zip, extract_dir)

        # Robust fallback: when error-context.md is missing or corrupted
        # (e.g. ENOENT under high parallelism), reconstruct the failure from
        # the trace action log, which always records the real error + stack.
        if not self._has_locator_info(error_message):
            trace_message = self._read_from_trace_actions(extract_dir)
            if self._has_locator_info(trace_message):
                error_message = trace_message
            elif not error_message:
                error_message = trace_message

        test_file, line_number = self._extract_location(error_message)
        failed_locator = self._extract_locator(error_message)
        dom_chunk = self._build_dom_context(error_message, extract_dir, failed_locator)
        test_name = self._derive_test_name(trace_zip)
        classification = self.classifier.classify(error_message, failed_locator)
        feature, scenario, step, step_keyword = self._extract_bdd_context(extract_dir)

        return FailureContext(
            trace_zip=trace_zip,
            test_file=test_file,
            line_number=line_number,
            failed_locator=failed_locator,
            error_message=error_message,
            dom_chunk=dom_chunk,
            test_name=test_name,
            classification=classification,
            feature=feature,
            scenario=scenario or test_name,
            step=step,
            step_keyword=step_keyword,
        )

    def _read_error_context(self, trace_zip: Path, extract_dir: Path) -> str:
        # Prefer the sibling error-context.md generated next to the trace.
        sibling = trace_zip.parent / ERROR_CONTEXT_NAME
        if sibling.exists():
            return self._clean(sibling.read_text(encoding="utf-8", errors="ignore"))

        # Fall back to any error-context.md packed inside the trace zip.
        for candidate in extract_dir.rglob(ERROR_CONTEXT_NAME):
            return self._clean(candidate.read_text(encoding="utf-8", errors="ignore"))
        return ""

    def _read_from_trace_actions(self, extract_dir: Path) -> str:
        """Reconstruct the failure error from the trace's action log.

        Every Playwright `*.trace` file is newline-delimited JSON. A failed
        action is recorded as an `after` event carrying the real error
        message (including "waiting for <locator>") and a stack string with
        the source file and line. This is available even when the sidecar
        error-context.md is missing or corrupted.
        """
        candidates: list[tuple[str, str]] = []  # (message, stack)
        for trace_file in sorted(extract_dir.rglob("*.trace")):
            try:
                content = trace_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for line in content.splitlines():
                line = line.strip()
                if not line or '"after"' not in line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") != "after":
                    continue
                error = event.get("error")
                if not isinstance(error, dict):
                    continue
                message = self._clean(str(error.get("message", "")))
                stack = self._clean(str(error.get("stack", "")))
                if message or stack:
                    candidates.append((message, stack))

        if not candidates:
            return ""

        # Prefer the error that names the locator ("waiting for ...") and
        # whose stack references a user TypeScript source (not node_modules).
        def score(item: tuple[str, str]) -> int:
            message, stack = item
            value = 0
            if "waiting for" in message:
                value += 4
            if re.search(r"\.ts:\d+", stack):
                value += 2
            elif re.search(r"\.(?:js|mts|mjs):\d+", stack):
                value += 1
            return value

        message, stack = max(candidates, key=score)
        return f"{message}\n{stack}".strip()

    @staticmethod
    def _has_locator_info(text: str) -> bool:
        if not text:
            return False
        lowered = text.lower()
        return (
            "waiting for" in text
            or "locator(" in text
            or "selector" in lowered
            or bool(re.search(r"getby[a-z]+\(", lowered))
        )

    def _derive_test_name(self, trace_zip: Path) -> str:
        folder = trace_zip.parent.name
        if not folder or folder == ".":
            return trace_zip.stem
        return (
            re.sub(r"-(chromium|firefox|webkit)$", "", folder)
            .replace("-", " ")
            .strip()
        )

    def _extract_location(self, error_message: str) -> tuple[Path | None, int | None]:
        # Prefer a user source frame (skip node_modules / playwright internals).
        for frame in re.finditer(
            r"at\s+\S+\s+\((.*?\.(?:ts|js|mts|mjs)):(\d+):\d+\)", error_message
        ):
            path = frame.group(1)
            if "node_modules" in path:
                continue
            return Path(path), int(frame.group(2))

        match = re.search(r"(\S*?\.(?:ts|js|mts|mjs)):(\d+):\d+", error_message)
        if match:
            return Path(match.group(1)), int(match.group(2))
        return None, None

    def _extract_locator(self, error_message: str) -> str | None:
        match = re.search(r"waiting for (.+?)(?:\n|$)", error_message)
        if match:
            return match.group(1).strip()
        match = re.search(r"locator\(([^)]+)\)", error_message)
        if match:
            return f"locator({match.group(1)})"
        match = re.search(r"selector[:\s]+[`\"']?([^`\"'\n]+)", error_message, re.I)
        return match.group(1).strip() if match else None

    def _extract_dom_chunk(self, extract_dir: Path, failed_locator: str | None) -> str:
        html_files = sorted(extract_dir.rglob("*.html"))
        if not html_files:
            return ""
        html = html_files[-1].read_text(encoding="utf-8", errors="ignore")
        return prune_dom(html, failed_locator)

    def _build_dom_context(
        self, error_message: str, extract_dir: Path, failed_locator: str | None
    ) -> str:
        """Build the richest available DOM hint for the AI.

        Playwright does not store the live DOM as plain HTML in the trace; the
        most useful representation is the accessibility (aria) snapshot, which
        lists each element's role and accessible name — exactly what locators
        target. Prefer that, then fall back to any pruned HTML snapshot.
        """
        aria = self._extract_aria_snapshot(error_message)
        if not aria:
            aria = self._extract_aria_from_trace(extract_dir)
        if aria:
            return aria[:4000]
        return self._extract_dom_chunk(extract_dir, failed_locator)

    @staticmethod
    def _extract_aria_snapshot(error_message: str) -> str:
        """Pull the YAML aria tree from error-context.md's 'Page snapshot'."""
        match = re.search(
            r"#\s*Page snapshot\s*```ya?ml\s*(.*?)```",
            error_message,
            re.S | re.I,
        )
        if match:
            return match.group(1).strip()
        # Some versions omit the fenced block; grab everything after the header.
        match = re.search(r"#\s*Page snapshot\s*(.*)", error_message, re.S | re.I)
        return match.group(1).strip() if match else ""

    def _extract_aria_from_trace(self, extract_dir: Path) -> str:
        """Collect the largest aria snapshot recorded in the trace events."""
        best = ""
        for trace_file in sorted(extract_dir.rglob("*.trace")):
            try:
                content = trace_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for line in content.splitlines():
                if '"ariaSnapshot"' not in line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                snapshot = self._find_aria(event)
                if snapshot and len(snapshot) > len(best):
                    best = snapshot
        return self._clean(best)

    def _find_aria(self, obj: object) -> str:
        """Recursively locate an 'ariaSnapshot' string in a trace event."""
        if isinstance(obj, dict):
            value = obj.get("ariaSnapshot")
            if isinstance(value, str) and value.strip():
                return value
            for nested in obj.values():
                found = self._find_aria(nested)
                if found:
                    return found
        elif isinstance(obj, list):
            for item in obj:
                found = self._find_aria(item)
                if found:
                    return found
        return ""

    @staticmethod
    def _clean(text: str) -> str:
        return ANSI_RE.sub("", text)

    # ── BDD / Gherkin context ────────────────────────────────────────────────

    def _extract_bdd_context(self, extract_dir: Path) -> tuple[str, str, str, str]:
        """Recover (feature, scenario, step text, step keyword) from the trace.

        Playwright-BDD records the scenario as the context-options ``title``
        (``spec:line \u203a Feature \u203a Scenario``) and wraps each Gherkin step in a
        ``test.step`` action. The failing step is the nearest ``test.step``
        ancestor of the action that errored. Returns empty strings for
        non-BDD suites so plain Playwright tests are unaffected.
        """
        scenario_title = ""
        before_map: dict[str, tuple[str | None, str | None, str]] = {}
        failing_callids: list[str] = []

        for trace_file in sorted(extract_dir.rglob("*.trace")):
            try:
                content = trace_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for line in content.splitlines():
                if (
                    '"context-options"' not in line
                    and '"before"' not in line
                    and '"after"' not in line
                ):
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                etype = event.get("type")
                if etype == "context-options":
                    scenario_title = scenario_title or str(event.get("title", ""))
                elif etype == "before":
                    call_id = event.get("callId")
                    if call_id:
                        before_map[call_id] = (
                            event.get("parentId"),
                            event.get("method"),
                            str(event.get("title", "")),
                        )
                elif etype == "after" and isinstance(event.get("error"), dict):
                    call_id = event.get("callId")
                    if call_id:
                        failing_callids.append(call_id)

        feature, scenario = self._split_scenario_title(self._clean(scenario_title))
        step = self._resolve_failing_step(before_map, failing_callids)
        keyword, step_text = self._split_step(self._clean(step))
        return feature, scenario, step_text, keyword

    @staticmethod
    def _split_scenario_title(title: str) -> tuple[str, str]:
        """Split ``spec:line \u203a Feature \u203a Scenario`` into (feature, scenario)."""
        if not title:
            return "", ""
        parts = [part.strip() for part in title.split("\u203a") if part.strip()]
        # Drop the leading "file:line" location segment when present.
        if parts and re.search(r"\.(spec|test|feature)\b", parts[0], re.I):
            parts = parts[1:]
        if len(parts) >= 2:
            return parts[0], parts[-1]
        return ("", parts[0]) if parts else ("", "")

    @staticmethod
    def _resolve_failing_step(
        before_map: dict[str, tuple[str | None, str | None, str]],
        failing_callids: list[str],
    ) -> str:
        """Walk up from each failed action to its enclosing ``test.step`` title."""
        for call_id in failing_callids:
            node: str | None = call_id
            seen: set[str] = set()
            while node and node not in seen:
                seen.add(node)
                parent, method, title = before_map.get(node, (None, None, ""))
                if method == "test.step" and title:
                    return title
                node = parent
        return ""

    @staticmethod
    def _split_step(step: str) -> tuple[str, str]:
        """Separate a Gherkin keyword (Given/When/Then/And/But) from its text."""
        if not step:
            return "", ""
        match = re.match(r"\s*(Given|When|Then|And|But)\b\s*(.*)", step, re.I)
        if match:
            return match.group(1).title(), match.group(2).strip()
        return "", step.strip()



def prune_dom(html: str, failed_locator: str | None, depth: int = 3) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "svg", "img", "meta", "link"]):
        tag.decompose()

    allowed = {"id", "class", "name", "type", "aria-label", "placeholder", "href", "role", "data-testid"}
    for tag in soup.find_all(True):
        tag.attrs = {key: value for key, value in tag.attrs.items() if key in allowed}

    text_hint = extract_text_hint(failed_locator or "")
    candidate = soup.find(string=re.compile(re.escape(text_hint), re.I)) if text_hint else None
    node = candidate.parent if candidate else soup.body or soup
    for _ in range(depth):
        if getattr(node, "parent", None):
            node = node.parent
    return str(node)[:4000]


def extract_text_hint(locator: str) -> str:
    match = re.search(r"name:\s*/([^/]+)/", locator)
    if match:
        return match.group(1)
    match = re.search(r"['\"]([^'\"]{3,})['\"]", locator)
    return match.group(1) if match else ""