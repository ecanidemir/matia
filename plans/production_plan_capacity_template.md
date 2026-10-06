# Production Plan — Capacity Template Uygulamasi

Tarih: 2026-10-06. Kapsam: sadece static (JS/XML/SCSS) + SCSS scope.
Python/model degisikligi YOK -> deploy icin modul Upgrade yeterli, servis restart gerekmez.
Sonrasi tam sayfa reload sart (stale DOM/asset bundle).

## Sorun

Production Plan (procurement) JS'i capacity'nin CSS siniflarini
(`msp-table`, `group-row`, `item-row`, `msp-kpi-card`, `badge-req-ok` ...)
uretiyordu ama bu stiller `stock_planning.scss` icinde yalnizca
`.o_matia_stock_planning` altina scoped idi. Procurement koku
`.o_matia_procurement_plan` oldugu icin stiller HIC uygulanmiyordu:
ham bootstrap tablo, ikonsuz kahve header, sekmesiz gorunum.

## Degisiklikler

1. `static/src/scss/stock_planning.scss` (1 satir):
   kok selector `.o_matia_stock_planning, .o_matia_procurement_plan` oldu.
   Capacity'ye eklenen her stil artik production'a otomatik gecer.
   Capacity-only bloklar (`.msp-header`, `.msp-controls-card`,
   `.msp-dynamic-chips-bar`) procurement altinda eslesmez, etkisiz.
2. `static/src/xml/procurement_plan.xml` (yeniden yazim):
   ikonlu header (`fa-industry`, title-area, ikonlu butonlar),
   ikonlu step sekmeler, Tab 1/2/3 `msp-table-card` + `msp-table-search`
   (legend + tool butonlar), Tab 2 ikonlu Expand/Collapse + capacity legend
   notu, Tab 3 kart sarmalayicili KPI + tablo kartlari.
   Hook class'lari korundu (`mpp-*`, `msp-btn-*`); Tab 1 thead 4 sutun.
3. `static/src/js/procurement_plan.js`:
   - Tab 1: `colspan 5->4`, satirlar `td-product` (dot + `[kod]` + ad),
     `td-stock`, qty `td-req` icinde.
   - `_theadHtml`: capacity thead deseni (sortable + ikon + title +
     "On Hand (incl. reserved)" notu). Sutun SAYISI ayni (15).
   - `_renderTree`: ice ice `table-responsive` kaldirildi (XML sarmalar).
   - KPI kartlarina `kpi-base/outdoor/seat/screws` accent + `kpi-sub`.
   - `_renderSuppliers`: sirket basina `group-row` baslikli tek `msp-table`
     (TR mavi / USA yesil / diger gri), satirlar `item-row`.
   - `_supplierRowHtml` / `_renderProduction`: `item-row`, `td-product`,
     `td-stock`, ikonlu RFQ/MO butonlari, `badge-req-need` uyari rozeti.
4. `static/src/scss/procurement_plan.scss` (yeniden yazim):
   capacity duzenli header (kahve marka rengi korunur), kart sekmeler,
   mobil stack. Tablo/KPI stilleri paylasilan scope'tan gelir.

## Dogrulama

- `node --check procurement_plan.js` OK
- Her iki XML `xml.dom.minidom` parse OK
- Her iki SCSS suslu-parantez dengesi 0
- Yeni stringlerde TR-karakter 0 (ekran %100 Ingilizce kurali korunur)

## Insan adimi

Git Deploy (static dosya) + modul Upgrade (mesai disi + oncesi backup),
sonra Ctrl+F5 ile dogrula: Tab 2 koyu sticky thead + renkli grup satirlari,
Tab 3 dort renkli KPI + kart tablolar.
