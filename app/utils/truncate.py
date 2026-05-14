from __future__ import annotations


def truncate_text(value: str, max_chars: int = 2000) -> str:
    if len(value) <= max_chars:
        return value
    return f"{value[:max_chars].rstrip()}..."
