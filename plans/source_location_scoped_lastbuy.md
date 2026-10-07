# Plan: Prices Location → Plan Source + Location-Scoped Last Buy

## Istek (2026-10-07, kullanici onayi alindi)

Prices'taki `location` (TR/US) plan sayfasindaki **Source** sutununa direkt yazilsin;
son satinalma da location'in sirketi (TR=1 / US=2) uzerinden bakilsin.

Ornek: `[P3CPPGA5]` override `location=us` → Source `USA` (manuel isaretli),
son alim US sirketindeki gercek tedarikcilerden aranir.

## Koken (staging olcumu)

- Source bugun = `plan.line.last_company_id` = sirketler-arasi global son GERCEK alimin sirketi.
- P3CPPGA5'in tek PO satiri sirket-ici (partner = Matia, filtreleniyor) → `lb` bos →
  `last_company=False`, fiyat 0 → Source `—`. Seller sutunu pricelist'ten PAKEL
  doldugu icin tablo tutarsiz gorunuyor (Seller dolu / Source bos).
- RFQ gruplama zaten override location'a saygi duyuyor (`_MPP_OVERRIDE_COMPANY`);
  sadece Source rozeti gostermiyor.

## Davranis spec

1. Override `location`'i olan urunde son alim **o location'in sirketiyle sinirli**
   aranir (`purchase.order.company_id` = TR/US, `order_id.company_id` domain traversali).
   Location'suz urunlerde global kural korunur (sirketler-arasi en son alim).
2. Kendi sirketlerimiz (TR/US partnerleri) hicbir modda gecerli satici degildir
   (mevcut `own_partners` filtresi korunur).
3. Source rozeti: `last_company_id` varsa aynen; yoksa override location sirketi
   (`TR`/`USA`) **manuel isaretiyle** (`last_company_manual=True`, rozette `*` +
   tooltip "Manual location (no purchase in this company yet)").
4. Seller/pricelist mantigi DEGISTIRILMEZ (global fallback korunur).
5. RFQ `_rfq_line_eff`'e dokunulmaz (sadece fiyatli override route eder — ayri konu).

## Kod degisiklikleri (`matia_stock_planning`)

- `models/matia_procurement_plan.py`
  - `_MPP_OVERRIDE_COMPANY` yakınına modul helper: `_mpp_last_buy_scope(ovr_map)`
    → `{pid: company_id}` (location'i olanlar).
  - `_mpp_last_buys(env_sudo, pids, company_by_pid=None)`: scope'lu pid'ler
    sirket-bazli gruplar halinde ek `search_read`
    (`order_id.company_id = cid`, max 2 ek sorgu, bulk korunur); aday secimi ayni.
    Docstring guncellenir.
  - Yeni method `_mpp_source_label(env_sudo, company_id, pid, ovr_map)`
    → `(label, manual)`.
  - Cagrilar scope gecirir (overrides fetch siralama duzenlenir):
    `action_assign_suppliers` (~1573), `get_sub_bom_cost` (~3186),
    `get_full_tree` (~3333), `get_prices` (~4072), `_mpc_price_map`
    (`matia_product_cost.py:178`).
  - Source fallback uygulanan row builder'lar: `_plan_summary` val (~2291) +
    suppliers satirlari (~2334), `get_tree_with_cost` top (~2734),
    `_mpp_sub_items` line (~3016) / lb (~3065) / row (~3115) —
    her birine `'last_company_manual'` anahtari.
- `static/src/js/procurement_plan.js`
  - `_srcBadge`: manuelde `*` + tooltip. Export (`source: r.last_company`) aynen
    calisir (fallback label otomatik duser).

## Dogrulama (Odoo 15, XML-RPC, staging)

1. `python -m py_compile` (butun degisen `.py`).
2. Yerel mantik provasi mumkun degilse staging'de salt-okunur check:
   P3CPPGA5 plan satiri `last_company_id` + liste `seller/last_price_usd`;
   Prices `get_prices` US satiri ayni degeri gosteriyor mu.
3. `@odoo-reviewer` salt-okunur denetim (modul degisikligi proseduru).
4. Deploy: PYTHON degisikligi → odoobulut Git Deploy + servis restart
   (mesai disi + oncesi backup) + modul Upgrade + Ctrl+F5.
   `button_immediate_upgrade` YUKLEMEZ. Commit/push yok (kullanici onayi olmadan).
