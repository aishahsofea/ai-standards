from catalog.export import products_csv
from catalog.products import Product


def test_products_csv_has_a_header_and_one_row_per_product():
    csv_text = products_csv([Product("A1", "Lamp", 1999), Product("B2", "Desk", 15000)])
    assert csv_text.splitlines() == ["sku,name,price", "A1,Lamp,$19.99", "B2,Desk,$150.00"]
