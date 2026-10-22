import pytest

from catalog.products import list_products


def test_list_products_rejects_an_unknown_sort():
    with pytest.raises(ValueError):
        list_products([], sort="colour")
