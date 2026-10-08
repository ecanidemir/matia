# Plan vs Supplier Total Equality (production plan)

## Problem

Plan tab Full Set 94,928.94 vs Suppliers tab 94,886.64 (staging MPP-0003/plan 26,
125 x 50). Diff 42.30 USD (0.045%). Both numbers are correct in their own basis;
the user wants ONE number everywhere, with no new columns and no column renames.

## Root cause (verified read-only on staging)

- Plan KPI = SUM over level-0 lines of stored `rolled_total_usd` (net gap cost:
  own order value + contrib-weighted child net shares). Confirmed by aggregate:
  buy 12,817.90 + make 76,032.92 + subcontract 6,078.12 = 94,928.94.
- Supplier grand = SUM over ordered buy/subcontract lines of
  `round(own_last_buy_usd x UoM_factor x order_qty, 2)` (flat PO value).
- Two systematic divergences, not a data bug:
  1. Share weights normalize by `demand` instead of total parent contribution,
     so entry tops that are also someone's child (and ceil-vs-float cascade
     drift over ~960 lines) leak/double a few dozen USD.
  2. Rounding happens at different stages (per-top stored 2-dec vs per-line
     round + 4-dec `rolled_usd` truncation reused in the supplier rolled column).
- Decisive live proof from `edge_json` (plan 26): entered targets 1840, 1845,
  1887, 1871, ... are ALSO components of other assemblies. Their net is
  counted once on their own top row AND pushed upward -> structural double
  count. Scope is otherwise aligned: no `unknown` lines on this plan,
  make own = 0 on both sides, zero-order lines are 0 on both sides, phantoms
  create no lines.

## Fix (Python only, no JS/XML, no response-shape change)

1. `_mpp_line_own_usd(line, ovr_map)` — single own-price rule (manual override
   wins except on make; else last-buy USD x line-UoM factor; else 0).
   Used by `_compute_rollup` (replaces identical `_own_usd` closure),
   `get_supplier_summary` (replaces identical inline block) and the net-cost
   phase. Same inputs, same outputs — behavior-preserving unification.
2. `_mpp_po_cents(own_per_unit, qty)` — single rounding rule:
   `round(own x qty, 2)` then exact integer cents. Supplier line totals and
   every net-cost addend use it, so both displayed totals sum identical cents.
3. `_mpp_net_costs` phase 2 in integer cents with largest-remainder split per
   child (weights = parent contributions normalized by their own sum, so shares
   always add up EXACTLY to the child net). Return signature unchanged
   ({pid: dollars}), scratch path untouched, TRY follows the same cents path.
4. Telescoping guarantee: every non-top net is fully distributed to parents,
   so SUM(tops rolled) == SUM(lines PO cents) == supplier grand, by
   construction, to the cent. Residual exception by design: `unknown`-route
   lines are listed separately and stay out of the supplier cash total
   (not RFQ-eligible); the plan cost still carries their material value. When
   `unknown_total_usd` is 0 (as now), the two tabs agree exactly.

## Verification

- `scratch/test_po_cents.py`: pure-stdlib replica of the new cents math on
  adversarial graphs (shared child, want-bearing child, phantom, zero-net
  parent, ceil orders) asserting SUM(tops) == SUM(lines) exactly. Must be GREEN.
- `py_compile` on the model file; case-sensitive TR-char scan (0 hits);
  `git status` shows only the model file + this plan + scratch test.
- Live proof needs a rebuild: staging Git Deploy + Upgrade/restart (off-hours +
  backup), then Recalculate plan 26 and compare the two tabs. Existing plans
  show new numbers only after rebuild.

## Deploy

- Python change: Git Deploy + Upgrade/restart required (button upgrade is not
  enough), off-hours + backup first. No commit/push without user approval.
