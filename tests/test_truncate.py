from __future__ import annotations

from app.utils.truncate import (
    json_char_size,
    limit_jsonable_items_by_chars,
    truncate_json_string,
    truncate_text,
    truncate_value,
)


def test_truncate_text_respects_max_chars() -> None:
    value = truncate_text("abcdef", max_chars=5)

    assert value == "ab..."
    assert len(value) == 5


def test_truncate_value_limits_nested_strings_and_lists() -> None:
    value = {
        "text": "x" * 50,
        "items": [{"name": "y" * 50} for _ in range(5)],
    }

    result = truncate_value(value, max_string_chars=10, max_list_items=2)

    assert result["text"] == "xxxxxxx..."
    assert len(result["items"]) == 3
    assert result["items"][-1] == {"truncated_items": 3}


def test_truncate_json_string_respects_max_chars() -> None:
    result = truncate_json_string({"value": "x" * 100}, max_chars=25)

    assert len(result) <= 25


def test_limit_jsonable_items_by_chars_keeps_payload_under_limit() -> None:
    items = [{"value": "x" * 20} for _ in range(10)]

    result = limit_jsonable_items_by_chars(items, max_chars=80)

    assert len(result) < len(items)
    assert json_char_size(result) <= 80
