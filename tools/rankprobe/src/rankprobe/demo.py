"""Small deterministic examples bundled with the installed package."""

from .model import Row


def demo_rows() -> list[Row]:
    return [
        Row("query-tie", "relevant", 0.5, 1.0),
        Row("query-tie", "irrelevant", 0.5, 0.0),
        Row("query-duplicate", "item-a", 0.9, 1.0),
        Row("query-duplicate", "item-a", 0.7, 1.0),
        Row("query-duplicate", "item-b", 0.6, 0.0),
        Row("query-incomplete", "known", 0.8, 1.0),
        Row("query-incomplete", "unknown", 0.95, None),
        Row("query-no-positive", "negative-a", 0.7, 0.0),
        Row("query-no-positive", "negative-b", 0.2, 0.0),
    ]
