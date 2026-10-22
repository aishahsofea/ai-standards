from dataclasses import dataclass


@dataclass(frozen=True)
class Product:
    sku: str
    name: str
    price_cents: int


def list_products(products: list[Product]) -> list[Product]:
    return sorted(products, key=lambda p: p.name)
