# Production Plan Tek Sayfa (Tab 1 kaldirma + TR+US + Needed)

Tarih: 2026-10-06. Kaynak: kullanici 8 maddelik istek + 4 netlestirme cevabi
(Tab adi "Plan", giris "ikisi birden" = grup N + satir Needed, netting "her sey
TR+US", acilis "son plani yukle").

## Hedef

- Enter Quantities sekmeleri tamamen kalkar (nav + pane + entry JS).
- Kalan agac sekmesi tek giris sayfasi olur, adi "Plan" (kisa, genel).
- Baslik "Production Plan (TR)" -> "Production Plan".
- Her grup basliginda N kutusu + Apply (gruptaki tum ust urunlere
  `Needed = max(0, ceil(N - (TR on-hand + US on-hand)))`, rezervler yok sayilir
  - eski Fill-to-N kurali aynen).
- Her ust-urun satirinda Needed duzenlenebilir input; degisiklik Recalculate
  ile sunucuya yazilir (`set_targets_and_rebuild`).
- Stok sutunlari: TR + US (ikisi de unreserved = on-hand - reserved, NCR haric).
  Netting (Planned/Order), Producible havuzlari ve satinalma hesabi TR+US
  toplami uzerinden. Tedarikci/USA ayrimi (seller, Source, TR RFQ / US RFQ) aynen.
- Yeni sutun sirasi (14 sutun): Part | Usage | TR | US | Producible | Needed |
  Planned | Seller | Source | Last Price | USD | Last Buy | Rolled USD | Est USD.
  Alt satirlarda Needed = bagimli brut ihtiyac (salt-okunur metin).
- Legend'taki "Deeper BOM levels have their own colors" yazisi yerine ayni
  konumda: "TR/US = Unreserved (on-hand minus reserved, NCR excluded)" + L2
  rozet ornegi korunur.
- Acilis: `get_startup_tree()` son plani yukler (yoksa bos draft acar), tum
  ust urunler Needed hedefleriyle listelenir (hedefsiz urun Needed=0 ile
  gorunur - eski "sadece hedefliler" filtresi kalkar).

## Server degisiklikleri (`models/matia_procurement_plan.py`)

- `_mpp_us_stock_locs(env_sudo)` yeni (WHUS/Stock%, NCR haric) + ortak
  `_mpp_stock_split(env_sudo, pids)` ->
  `{pid: (oh_tr, rs_tr, oh_us, rs_us)}` (tek read_group TR + tek read_group US).
  `get_entry_products`, `action_explode_and_net`, `get_sub_bom_cost` bunu kullanir.
- Line modeli: `stock_us`, `reserved_us`, `avail_us` Float ekle. `_description`
  ve `company_id` help'indeki "(TR)"/"TR only" ifadeleri genellestirilir.
- `action_explode_and_net`: avail toplami = avail_tr + avail_us (her biri
  `max(0, oh-rs)` kirpilmali). `net_map`, `pool_map`, branch dagitimi bu toplam
  uzerinden. `incoming_info` (onayli PO) + `open_mo_info` (acik MO) domainleri
  TR-only'dan `[TR, US]`'e genisler (salt bilgi kolonlari).
- `get_tree_with_cost`: tum kit ustlerini listeler (targets filtresi kalkar);
  her ustte `need` (=hedef, default 0), `planned = max(0, need - avail_toplam)`,
  `avail_us/stock_us/reserved_us`, `producible` havuzdan (toplam bazli).
- Yeni: `get_startup_tree()` (son plan veya bos draft + `get_tree_with_cost`) ve
  `set_targets_and_rebuild(plan_id, targets)` (target_json yaz + rebuild).
  `get_entry_products`/`create_plan` legacy olarak durur (harici script kirilmaz).
- `_plan_summary` satir dict'lerine us alanlari eklenir.
- Form view'e (`views/procurement_plan_views.xml`) 3 yeni field eklenir.

## Client degisiklikleri (JS/XML/SCSS + export controller)

- `static/src/xml/procurement_plan.xml`: h2 "Production Plan"; nav 2 sekme
  (1. Plan, 2. Suppliers & Production); Tab 1 pane silinir; agac pane
  `data-pane="1"` olur + toolbar'a Recalculate + plan adi rozeti.
- `static/src/js/procurement_plan.js`: entry render/fill/clear/calc bloklari
  silinir; yerine Needed input handling (`_onNeedInput`), grup Apply
  (`_onGroupFill`), `_onRecalc`, startup `get_startup_tree`; `_theadHtml`,
  `_rowHtml` (TR/US/Needed), sort key'leri (`tr/us/need`), `_collectExportRows`
  14 sutuna uyarlanir; `colspan=12` -> `colspan=14` (2 yer + bos-sonuc satiri).
- `controllers/procurement_export.py`: tree export basliklari
  Part/Usage/TR/US/Producible/Needed/Planned/... (xlsx + CSV format sayilari
  guncellenir).
- SCSS: `.mpp-need` input + `.mpp-group-fill` grup basligi kutusu stilleri.
- Capacity sayfasina DOKUNULMAZ.

## Dogrulama

- `py_compile`, `node --check`, case-sensitive TR-karakter taramasi
  (`Select-String -CaseSensitive`), colspan tutarliligi.
- Deploy: Python var -> Git Deploy + Upgrade/restart (mesai disi + backup).
  Mevcut planlar Recalculate edilmeden yeni Needed/TR-US gorunumu gostermez.

## Implementation (2026-10-06, done - verify on live)

- Server: `_mpp_us_stock_locs` + `_mpp_stock_split` (tek read_group TR + tek
  read_group US); line `stock_us/reserved_us/avail_us`; netting/pool/PO/MO
  TR+US; `_MPP_KIT_BOMS` sira base/outdoor/seat/screws; `get_tree_with_cost`
  tum kit ustlerini listeler (need=targets.get(pid,0), planned=max(0,need-toplam));
  `get_startup_tree()` + `set_targets_and_rebuild()` (Needed kalici); bos-plan
  skeleton dali; `_description`/help de-TR. `py_compile` OK.
- Client: XML 2 tab + Recalculate + Unreserved legend; JS entry kaldirildi,
  Needed input (canli Planned guncelleme, change'te persist+rebuild), grup N
  fill (`need=max(0,ceil(N-avail_total))`), startup son plan; 14 sutun
  (Part/Usage/TR/US/Producible/**Needed**/Planned/...); sort tr/us/need;
  export 16 kolon (x2 usage + per-top). `node --check` OK, TR-char scan clean.
- Degisen: `models/matia_procurement_plan.py`,
  `static/src/{js/procurement_plan.js, xml/procurement_plan.xml,
  scss/procurement_plan.scss}`, `controllers/procurement_export.py`.
