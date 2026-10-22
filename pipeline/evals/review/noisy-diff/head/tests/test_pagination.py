import pytest

from catalog.pagination import page_count, paginate


def test_paginate_returns_a_full_page():
    assert len(paginate(list(range(50)), page=1, size=20)) == 20


def test_paginate_past_the_end_is_empty():
    assert paginate(list(range(50)), page=4, size=20) == []


def test_paginate_rejects_page_zero():
    with pytest.raises(ValueError):
        paginate([1, 2], page=0, size=20)


def test_page_count_rounds_up():
    assert page_count(41, 20) == 3


def test_page_count_of_an_empty_list_is_one():
    assert page_count(0, 20) == 1
