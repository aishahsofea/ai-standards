import math
from collections.abc import Sequence
from typing import TypeVar

T = TypeVar("T")


def page_count(total: int, size: int) -> int:
    return max(1, math.ceil(total / size))


def paginate(items: Sequence[T], page: int, size: int) -> list[T]:
    if page < 1 or size < 1:
        raise ValueError("page and size must be at least 1")
    start = page * size
    return list(items[start:start + size])
