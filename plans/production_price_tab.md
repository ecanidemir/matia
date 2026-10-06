# Production Plan Tab 3 — Prices (manual price/location overrides)

Date: 2026-10-06. Status: planned (user answers: global / purchase-location / override / auto-type).

## Goal

New "3. Prices" tab on the Production Plan dashboard (`matia.procurement.plan`
client action). Quantity-independent list of EVERY product down to the lowest
level inside the 4 kit BOMs (Base 1766 / Outdoor 1737 / Seat 1738 / Screws 1736),
same `msp-table` visual language as Tabs 1-2.

Columns: Part (code + name) | Type | Seller | Last Price | USD | Last Buy |
Corrected Price | Location.

## Design decisions (confirmed by user)

1. **Global scope**: one override per product, valid in ALL plans. Stored in DB,
   survives recalculations.
2. **Location = purchase location**: TR/US on the override routes the draft RFQ
   to company 1/2 (receipt WHTR vs WHUS). Empty = old rule (last-buy company).
3. **Override wins**: corrected USD replaces last-buy USD everywhere in
   calculations (rolled cost, supplier totals, RFQ unit price in USD).
4. **Type is automatic**: from product routes — Buy / Subcontract /
   Manufacture (= `make`), read-only badge. Same classifier as line creation
   (Subcontract > Manufacture > Buy > purchase_ok?Buy:Unknown).

## New model `matia.procurement.price.override`

- `product_id` M2O product.product, required, ondelete cascade, UNIQUE
  (`_sql_constraints product_uniq`). Docstrings + `@param/@return` (repo rule).
- `corrected_price_usd` Float(16,4), default 0.0. Meaning: manual USD unit
  price **per plan-line UoM** (UoM factor 1.0 — no conversion applied).
- `location` Selection `[('tr','TR'),('us','US')]` (empty = no choice yet).
- ACL: `base.group_system` full (same as other procurement models, admin-only
  page). 2 rows appended to `security/ir.model.access.csv`.
- New file `models/matia_procurement_price_override.py` + import in
  `models/__init__.py`. No form/tree views (managed only via dashboard JS).

## Server methods (`matia.procurement.plan`, model-style, no ensure_one)

- `_mpp_price_overrides(env_sudo, pids=None)` -> `{pid: {'price': f,
  'location': 'tr'/'us'/False}}`, single search_read. Empty table -> {} fast.
- `get_price_overview(plan_id)`:
  - BFS walk of the 4 kit BOMs (bom cache per product_id/template, depth<=10,
    cycle guard via path set — same guards as `search_tree`). Collects ALL
    descendant pids, deduped. Top products included.
  - Bulk route classify (same `route_ids` name logic), bulk last-buy via
    `_mpp_last_buys`, seller = plan line seller if plan has lines else
    last-buy partner name (no pricelist fallback — keeps it quantity-free).
  - Join overrides. Item: `{product_id, code, name, route, route_label,
    seller, last_price, last_currency, last_usd, last_date('Mon YYYY'),
    corrected, location, effective_usd, has_override}`. Sorted by code.
- `save_price_override(product_id, corrected_price_usd, location)`:
  validate price>=0, location in (tr/us/False/''), upsert by product_id.
- `bulk_set_location(product_ids, location)`: upsert location only, keep price.
  `location` must be tr/us (bulk always sets a value).
- `clear_price_overrides(product_ids)`: unlink rows.
- All-English + ASCII strings (repo rule, `_t()` only for long phrases, never
  for Apply/Show/Save words).

## Calculation integration (override = effective USD)

- `_compute_rollup._own_usd`: override price>0 -> return it (factor 1.0).
  Preload overrides once per call (no per-line query).
- `_compute_rollup._own_try` + `_mpp_line_try`: override USD -> plan currency
  at TODAY rate (no historical date exists for a manual price).
- `get_supplier_summary` PO-value `_own`: override first (same basis as RFQ).
  `no_price` flag respects override (corrected>0 = priced).
- `_rfq_groups` (rfq file): override -> currency USD, unit = corrected x 1.0,
  company = override location (tr->1, us->2) else old rule. `get_rfq_preview`
  lines show corrected price + 'USD'.
- Tree rows (`get_tree_with_cost` items + `_mpp_sub_items`): add
  `corrected_usd` + `eff_usd` so Tab 1 can badge overridden lines (small
  follow-up in JS; server fields first).
- Existing plans pick overrides up after Recalculate + supplier preview
  re-run (lines are rebuilt/snapshotted).

## Client Tab 3 (JS/XML/SCSS, static-only pattern)

- `procurement_plan.xml`: nav tab `3. Prices` + pane: toolbar (selected count,
  `Set TR` / `Set US` bulk buttons, `Clear` button) + `msp-table-card` with
  `mpp-price-body` container.
- `procurement_plan.js`: `_fetchPrices` (RPC get_price_overview), `_renderPrices`
  full client table: header checkbox (select all visible), per-column filter
  row (text inputs for Part/Seller/Last Price/USD/Last Buy/Corrected, SELECT
  for Type and Location), click-to-sort headers (reuse `msp-th-sortable`
  pattern), row checkbox, corrected=number input + location=select + per-row
  Save (RPC save_price_override), bulk buttons apply to checked ids.
  Overridden rows get a badge/highlight class.
- `procurement_plan.scss`: reuse `msp-table` classes; small additions only
  (filter-row inputs, corrected input width, override badge).

## Verification

- `py_compile` all touched py, `node --check` JS, XML parse, case-sensitive
  TR-character scan (`Select-String -CaseSensitive`, plain `i/I` folds).
- TDD scratch sim for override-precedence logic where separable.
- Deploy: Python involved -> Git Deploy + Upgrade/restart (off-hours +
  backup); JS needs Ctrl+F5. No commit/push without user approval.
