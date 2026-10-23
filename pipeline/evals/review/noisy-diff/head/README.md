# Catalog

Product catalog helpers.

- `list_products(products, page=1, sort="name")` returns one page of 20 products, sorted by `name` or `price`. Pages start at 1.
- `page_count(total, size)` returns how many pages a list needs (at least 1).
- `format_price(cents)` formats a price as `$12.34`.
- `products_csv(products)` exports products as CSV with `sku`, `name` and `price` columns.
