"""Filename suggestion helpers based on analysis reason text."""

from __future__ import annotations

DEFAULT_RULES: list[tuple[str, str]] = [
    ("Extracted text successfully", "OK_"),
    ("No text extracted", "NO_TEXT_"),
    ("Read timeout", "TIMEOUT_"),
    ("Analyze failed", "FAIL_"),
]


def suggest_name(reason: str, current_name: str, rules: list[tuple[str, str]]) -> str:
    """Suggest a filename by matching reason text to keyword->prefix rules."""
    reason = reason or ""
    for keyword, prefix in rules:
        key = keyword.strip()
        if key and key in reason:
            base = current_name if current_name.lower().endswith(".pdf") else f"{current_name}.pdf"
            return f"{prefix.strip()}{base}"
    return current_name if current_name.lower().endswith(".pdf") else f"{current_name}.pdf"


def resolve_conflicts(suggested_names: list[str]) -> list[str]:
    """Resolve duplicate names in one folder by adding _1, _2, ... suffixes."""
    seen: dict[str, int] = {}
    result: list[str] = []
    for name in suggested_names:
        if name not in seen:
            seen[name] = 0
        k = seen[name]
        seen[name] += 1
        if k == 0:
            result.append(name)
            continue
        stem = name[:-4] if name.lower().endswith(".pdf") else name
        ext = name[-4:] if name.lower().endswith(".pdf") else ""
        result.append(f"{stem}_{k}{ext}")
    return result
