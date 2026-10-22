# Paginated, sortable product list with CSV export

## Problem
The product list shows every product at once, can only sort by name, and there is no way to export it.

## Proposed design
- Show 20 products per page. Pages are numbered from 1: page 1 is the first 20 products.
- Sort by `name` (default) or `price`. Reject any other sort.
- Export products as CSV with `sku`, `name` and a formatted `price`.

## Acceptance criteria
- Page 1 shows the first 20 products; a page past the end is empty.
- Sorting by price orders products cheapest first; an unknown sort is rejected.
- The CSV has a header row and one row per product, with prices like `$12.05`.
