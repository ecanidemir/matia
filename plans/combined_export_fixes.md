# Combined Export Duzeltmeleri (popup: Combined Plan - Products / Suppliers)

Tarih: 2026-10-08. Kapsam: `controllers/procurement_export.py` + `static/src/js/procurement_plan.js`.
Python var -> Git Deploy + Upgrade/restart (mesai disi + backup); sonrasi Ctrl+F5.

## Tespitler (kok nedenler)

1. **Grup sirasi**: `_export_slots_from_plans` canon siralamayi slot-0 client sirasindan aliyor; garanti yok.
   Cozum: server-side kanonik sira Base > Outdoor > Seat; Screws -> 'Base' etiketiyle Base blogunun en altinda.
   Client `_collectExportRows` + server `_port_row` satira `gkey` ekler (yoksa basliktan turetilir).
2. **Unit Cost 0**: `_usd0num` = round() -> 0.5 alti $0. Kural: 0/None -> bos hucre;
   0 < |v| < 1 -> 2 ondalik (`$#,##0.00`); 0.005 alti -> 4 ondalik (2 ondalik $0.00 verirdi);
   diger -> whole-USD (combined) / 2-dec (single). Ayni kural tum combined para hucreleri +
   subtotal/total icin. Toplamlar tam hassasiyetle birikir, yazarken formatlanir.
3. **Grup subtotal yok**: Products sheet'e grup blogu sonuna statik SUBTOTAL satiri (slot basina),
   Group etiketiyle (filtrede gorunur, cost sheet deseni). Grand TOTAL filtre disinda kalir.
4. **Location basligi**: deger kaynak/RFQ sirketi (TR/USA). Baslik 'Buy From' olur (screen Tab2 ile ayni dil).
5. **Tedarikci maliyetleri TRY->USD sisik (~40x)**: popup `_plan_summary.suppliers` kullaniyor
   (`subtotal`/`cost` plan para birimi = TRY); ekran Tab2 `get_supplier_summary` (PO-value USD).
   Cozum: `_exportSlotsCollect` slot basina `get_supplier_summary` ceker, v2 payload (USD) gonderir;
   server v2'yi company-bazli satirlar; `cost_slots` (Cost sayfasi) server-side `get_supplier_summary`
   kullanir; single `plan_supplier` + supplier-only ayni v2'ye gecer. Eski JS cache'e karsi `sup_v`
   bayragi: v2 yoksa legacy render (degismeden).

## Degisen dosyalar

- `controllers/procurement_export.py`: `_GROUP_RANK`, `_canon_sort_key`, `_write_usd*` helper'lar,
  `_combined_supplier_table` v2, `_write_supplier_sheet` v2 + legacy, `_server_supplier_v2`,
  CSV fallback'lar, 'Buy From' basligi.
- `static/src/js/procurement_plan.js`: `gkey` (_collectExportRows), `_supPayloadFrom(supSummary)`,
  `_exportSlotsCollect` zincirine `get_supplier_summary`, `_onExportPlanSupplier`/`_onExportExcel`
  icin taze supSummary fetch (`_withSupSummary`).
- `product_cost.js`: degisiklik YOK (cost_slots server-side duzelir).

## Dogrulama

- `py_compile`, `node --check`, TR-karakter taramasi (`Select-String -CaseSensitive`).
- Staging'de: 2 slot sec + supplier + export; grup sirasi, screws Base altinda, subtotal, $0 yok,
  supplier toplamlarinin ekran Tab2 ile eslesmesi, Buy From basligi.
