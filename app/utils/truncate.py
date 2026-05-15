from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any


def truncate_text(value: str, max_chars: int = 2000) -> str:
    if max_chars < 1:
        return ""
    if len(value) <= max_chars:
        return value
    if max_chars <= 3:
        return "." * max_chars
    return f"{value[: max_chars - 3].rstrip()}..."


def json_char_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str))


def truncate_json_string(value: Any, max_chars: int) -> str:
    return truncate_text(
        json.dumps(value, ensure_ascii=False, default=str),
        max_chars=max_chars,
    )


def truncate_value(
    value: Any,
    *,
    max_string_chars: int = 500,
    max_list_items: int = 20,
    max_depth: int = 4,
) -> Any:
    if max_depth <= 0:
        return truncate_text(str(value), max_string_chars)
    if isinstance(value, str):
        return truncate_text(value, max_string_chars)
    if isinstance(value, Mapping):
        return {
            str(key): truncate_value(
                item,
                max_string_chars=max_string_chars,
                max_list_items=max_list_items,
                max_depth=max_depth - 1,
            )
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray | str):
        items = list(value)
        truncated_items = [
            truncate_value(
                item,
                max_string_chars=max_string_chars,
                max_list_items=max_list_items,
                max_depth=max_depth - 1,
            )
            for item in items[:max_list_items]
        ]
        if len(items) > max_list_items:
            truncated_items.append(
                {
                    "truncated_items": len(items) - max_list_items,
                }
            )
        return truncated_items
    return value


def limit_jsonable_items_by_chars(
    items: Sequence[Any],
    *,
    max_chars: int,
    min_items: int = 0,
) -> list[Any]:
    kept: list[Any] = []
    for item in items:
        tentative = [*kept, item]
        if len(kept) >= min_items and json_char_size(tentative) > max_chars:
            break
        kept.append(item)
    return kept
