# Plan

## Phase 1: Pagination helpers
- Add `catalog/pagination.py` with `paginate` and `page_count`, with tests.
- Verify: `pytest tests/test_pagination.py`

## Phase 2: Paginated, sortable list
- Add `page` and `sort` to `list_products`, with tests.
- Verify: `pytest tests/test_products.py`

## Phase 3: Price formatting and CSV export
- Add `catalog/formatting.py` and `catalog/export.py`, with tests. Update the README.
- Verify: `pytest tests/test_formatting.py tests/test_export.py`

## Acceptance criteria
- Page 1 shows the first 20 products; past the end is empty: Phase 1, `test_paginate_returns_a_full_page`, `test_paginate_past_the_end_is_empty`
- Sort by price; unknown sort rejected: Phase 2, `test_list_products_rejects_an_unknown_sort`
- CSV header and rows: Phase 3, `test_products_csv_has_a_header_and_one_row_per_product`
