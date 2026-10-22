Status: pass

**Commands**
- `pytest`: pass, 10 passed.

**Acceptance criteria**
- Page 1 shows the first 20 products; past the end is empty: `test_paginate_returns_a_full_page`, `test_paginate_past_the_end_is_empty`.
- Sort by price; unknown sort rejected: `test_list_products_rejects_an_unknown_sort`.
- CSV header and rows: `test_products_csv_has_a_header_and_one_row_per_product`.

**Manual checks**
None.

**Definition of done**
All met.

**Failures**
None.

**Fixes made**
None.
