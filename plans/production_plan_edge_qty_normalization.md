# Plan: Production plan edge-qty UoM normalizasyonu

Tarih: 2026-10-07 | Durum: onay bekliyor | Deploy: Python var -> Git Deploy +
Upgrade/restart (mesai disi + backup); mevcut planlar Recalculate edilmeden
duzelmez; sonrasi Ctrl+F5. Commit/push YOK (istenmedi).

## Sorun

Production plan patlatmasi BOM satir miktarini (`bl.product_qty`) satir UoM'una
cevirmeden saklar; satir `uom_id` her zaman urun stok UoM'idir, `_compute_rollup`
ise qty x satir-UoM basina fiyat carpar. UoM uyumsuz 10 BOM satirinda plan hem
maliyeti hem miktari (gross/net/order, RFQ/MO) yanlis uretir.

Kanıt (staging, salt-okunur): E2CBAN03 plan rolled 972.66 vs Product Cost 130.34;
972.66 - 842.76 + 0.44 = 130.34 kurusuna uyar. Fiziksel teyit: BOM satirlari
dogru (E1CBRN03 370 mm = 0.37 m; E1CBRW01 1.76 m = 1760 mm), hata patlatmada.
Tam tarama: 511 aktif BOM / 1551 satir -> 10 uyumsuz (rapor:
`scratch/audit_bom_uom_report.json`):
E1CBRN03/E2CBAN03 (~843 USD sisme), E1CBRW01/E2CBAN03 (~0.44 eksik),
T1HLRB51 x3 (~101-185 USD), T1HSRB50 x4 (~20-96 USD), N1PGRN02 (fiyatsiz, 0).

## Degisiklik (`models/matia_procurement_plan.py`)

1. Yeni helper `_mpp_norm_edge_qty(bl, child_stock_uom)`: ayni kategori ise
   `bl.product_qty`'yi stok UoM'una cevirir (`_compute_quantity` deseni,
   `_mpc_explode` ile ayni); farkli kategori/cevrilemez ise ham deger + warning
   log (fail-safe, patlatma durmaz).
2. Patlatma 2 nokta: phantom kolda L869-875 + normal kolda L883-891 — hem
   `edges` hem `stack`'e normalize qty girer. Tek hamle tum zinciri duzeltir:
   net cascade (L951-970), pool/branch (L979-1003), exact allocation (L1017+),
   edge_json (L1201), satir gross/net/order_qty, RFQ/MO uretimi (L3417).
3. `_mpp_sub_items` (L2533+): satirli dalda `bqty` satir UoM'una cevrilip oyle
   gosterilir (JS `ext = bom_qty x rolled_usd` ile tutarli olur); satirsiz dal
   aynen (kendi icinde tutarli). Etiket: cevrim varsa usage'da kisa not.
4. `_mpp_need_per_top` yuruyusu (L2475-2484): tooltip qty'si normalize edilir.
5. Overview kit-top satirlari (L2247): satir varsa `bom_qty` satir UoM'una
   cevrilir (display-only, para matematigi etkilenmez).

DokunulMAyanlar: fiyat snapshot mantigi, `_compute_rollup`, route siniflama,
capacity sayfasi, Prices/Product Cost sayfasi.

## Dogrulama

- `py_compile` + `node --check` (JS degisirse) + TR-karakter taramasi.
- Simulasyon: normalize helper icin saf-fonksiyon testi (`scratch/` altinda,
  Odoo importsuz, 10 satirlik audit vektoru: 370 mm->0.37, 1.76 m->1760 vb.).
- Staging: yeni plan kur, E2CBAN03 rolled ~130.3x + Product Cost ile karsilastir;
  `_mpp_need_per_top` tooltip + sub-BOM usage degerleri gozle kontrol.
- `@odoo-reviewer` salt-okunur denetim (Odoo 15 kurallari).
- `plans/` + discovery guncel; hata hafizasi (`/log-error`) fix deploy sonrasi.

## Acik sorular (kullaniciya)

- BOM verisi degisecek mi? Oneri: HAYIR (satirlar fiziksel dogru, kod duzelir).
- 10 satirin 8'i minder/velcro uretiminde; duzeltme sonrasi bu ebeveynlerin
  rolled + siparis miktarlari degisir — uretim ekibi bilgilendirilsin mi?
