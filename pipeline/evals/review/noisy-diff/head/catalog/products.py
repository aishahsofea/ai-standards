from dataclasses import dataclass

from catalog.pagination import paginate

PAGE_SIZE = 20
SORT_KEYS = {"name": lambda p: p.name, "price": lambda p: p.price_cents}


@dataclass(frozen=True)
class Product:
    sku: str
    name: str
    price_cents: int


def list_products(products: list[Product], page: int = 1, sort: str = "name") -> list[Product]:
    if sort not in SORT_KEYS:
        raise ValueError(f"unknown sort: {sort}")
    return paginate(sorted(products, key=SORT_KEYS[sort]), page, PAGE_SIZE)
