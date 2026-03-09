"""블랙리스트 키워드로 스팸 여부 판별."""


def is_spam(text: str, keywords: list[str], case_sensitive: bool = False) -> bool:
    """추출된 텍스트에 블랙리스트 키워드가 하나라도 포함되면 True."""
    if not text or not keywords:
        return False
    if not case_sensitive:
        text = text.lower()
        keywords = [k.lower() for k in keywords]
    return any(kw in text for kw in keywords)
