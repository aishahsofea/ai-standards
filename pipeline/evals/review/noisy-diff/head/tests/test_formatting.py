import pytest

from catalog.formatting import format_price


def test_format_price_pads_cents():
    assert format_price(1205) == "$12.05"


def test_format_price_of_zero():
    assert format_price(0) == "$0.00"


def test_format_price_rejects_negative():
    with pytest.raises(ValueError):
        format_price(-1)
