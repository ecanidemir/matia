# Matia TekRMD Stock & Capacity Planning Module (`matia_stock_planning`)

This module is designed for **Odoo 15** and provides an interactive dashboard under the Inventory menu to analyze TekRMD BOMs and on-hand stock for production capacity planning.

## Key Features

1. **BOM Grouping:**
   - **Base (Blue):** `TekRMD Common Parts v2` (84 components)
   - **Outdoor (Green):** `TekRMD Outdoor Parts` (9 components)
   - **Seat (Purple):** `TekRMD Seat Parts` (7 components)

2. **Advanced Location & Multi-Company Filtering:**
   - **TR Locations:** All internal stock locations under `WHTR/Stock/*` (149 locations).
   - **USA Locations:** Internal stock locations under `WHUS/Stock/*`.
   - **NCR Exclusion:** `WHTR/NCR Alanı` and `WHUS/NCR Storage` are excluded from net usable stock calculations; displayed separately as informational badges.
   - One-click filtering for TR only, USA only, or TR + USA combined. At least one location must be selected.

3. **Calculations and Columns:**
   - **Usage Qty:** Required quantity per BOM. Can be hidden or shown at any time with a single toggle.
   - **Producible Devices:** `floor(stock_qty / bom_qty)`. Bottlenecks are visually highlighted with color-coded badges (<20 Red, 20-50 Yellow, >50 Green).
   - **20 Devices Needed:** `(20 * bom_qty) - stock_qty`. Displays green `OK` if stock is sufficient, or the exact missing quantity in red.
   - **Dynamic Target Columns:** Users can add up to 3 custom target columns (e.g. 10, 50, 100, 200) via `+ Add Target Column` and remove them anytime with the `[x]` button.

4. **WYSWIG Excel (.xlsx) Export:**
   - Exports the exact visible table (excluding hidden columns, including dynamic targets) with formatted headers, group styling, and status colors.

5. **Performance & Speed:**
   - Uses optimized `read_group` RPC queries to fetch stock across all 103 unique products in milliseconds.
   - Real-time client-side table search and column updates.

## Installation

1. Deploy the repository to your Odoo server using Cloudpepper or copy `matia_stock_planning` into your `addons` directory.
2. Enable Developer Mode in Odoo.
3. Navigate to **Apps > Update Apps List**.
4. Search for `matia_stock_planning` and click **Install**.
5. Access the dashboard from **Inventory > Device Capacity Plan** or **Inventory > Reporting > TekRMD Device Capacity**.
