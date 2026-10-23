import csv
import io

from catalog.formatting import format_price
from catalog.products import Product


def products_csv(products: list[Product]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["sku", "name", "price"])
    for product in products:
        writer.writerow([product.sku, product.name, format_price(product.price_cents)])
    return out.getvalue()
