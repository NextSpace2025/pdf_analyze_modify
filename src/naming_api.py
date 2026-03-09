"""분석 결과(사유) 기반 파일명 규칙 API. 사유 문자열에 매칭되는 규칙으로 접두사를 붙여 새 이름 제안."""

# 기본 규칙: (사유에 포함될 문구, 접두사) — 위에서부터 먼저 매칭
DEFAULT_RULES: list[tuple[str, str]] = [
    ("정상 추출", "OK_"),
    ("텍스트를 추출할 수 없음", "NO_TEXT_"),
    ("읽기 시간 초과", "TIMEOUT_"),
    ("분석 실패", "FAIL_"),
]


def suggest_name(reason: str, current_name: str, rules: list[tuple[str, str]]) -> str:
    """
    사유(reason)에 맞는 규칙으로 새 파일명 제안.
    매칭되는 규칙이 없으면 현재 이름 그대로 반환.
    """
    reason = reason or ""
    for keyword, prefix in rules:
        if keyword.strip() and keyword in reason:
            base = current_name if current_name.lower().endswith(".pdf") else current_name + ".pdf"
            return prefix.strip() + base
    return current_name if current_name.lower().endswith(".pdf") else current_name + ".pdf"


def resolve_conflicts(suggested_names: list[str]) -> list[str]:
    """동일 폴더 내 이름 충돌 시 _1, _2 접미사로 구분."""
    seen: dict[str, int] = {}
    result: list[str] = []
    for name in suggested_names:
        if name not in seen:
            seen[name] = 0
        k = seen[name]
        seen[name] += 1
        if k == 0:
            result.append(name)
        else:
            stem = name[:-4] if name.lower().endswith(".pdf") else name
            ext = name[-4:] if name.lower().endswith(".pdf") else ""
            result.append(f"{stem}_{k}{ext}")
    return result
