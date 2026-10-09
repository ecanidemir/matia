# Web Hizli Maliyet Plani — Odoo Controller (2026-10-09, revize)

> Revizyon: "Odoo'ya dokunma" kalkti. En hizli ve basit dizilim: sayfa + API
> Odoo'nun icinde, harici hosting (JustCloud) YOK. `scratch/web_base_cost/`
> prototipindeki join mantigi porta edilir.

## Kararlar (kullanici onayli)
- Hedef: base-outdoor-seat (= full kombo) + adet kutusu -> brüt + stok-düsülmüs net USD.
- Her sey Odoo controller'da: HTML sayfa + JSON quote API. Ek sunucu/env dosyasi yok.
- Login YOK (auth public) ama gizli `QUOTE_KEY` sart (`?key=` tutmazsa 403).
- Kapsam v1: SADECE okuma. Slot-write / rebuild / slot gizleme (1..9) YOK, faz-2.
- Anahtar `ir.config_parameter`'da tutulur (`web_quote.key`), koda/repoya ASLA gomulmez. Staging + prod'a manuel girilir.

## Mimari (degisen dosya sayisi: 2)
- YENI `controllers/web_quote.py` (`matia_stock_planning` icinde):
  - `GET /web_quote` (type=http, auth=public): basit HTML (adet input default 100, Hesapla, özet + tablo). Inline string — XML/view dosyasi yok, manifest `data` degisikligi yok.
  - `GET /web_quote/quote?qty=N&key=...` (type=http, auth=public, csrf=False): key'i `ir.config_parameter` ile karsilastir, qty'yi 1..10000 arastir, internal cagri yap, JSON don:
    - `request.env['matia.product.cost'].sudo().get_cost_tree()` — rolled unit USD + `combos.full`.
    - `request.env['matia.stock.planning'].sudo().get_capacity_planning_data(include_tr=True, include_usa=True, dynamic_targets=[N])` — avail + `dynamic_needs[N].val`.
    - Hesap: brüt = `full x N`; net = SUM(top-level `net_ihtiyac x rolled_unit`) (base+screws+outdoor+seat). Sadece top-level net; alt-BOM yok, sayfada yazar.
  - Write metodu CAGRILMAZ (`save_slot`, `set_targets_and_rebuild` yasak v1'de).
- EDIT `controllers/__init__.py`: yeni controller importu (tek satir).
- Baska dosya yok: model/view/CSV/menu degisikligi yok.

## Odoo 15 kurallari
- `auth='public'` + `csrf=False` (mevcut controller'lar `auth='user'`; bkz. `controllers/main.py:15`).
- Public env yetkisizdir: cagrilar `.sudo()` ile, ic metodlar zaten `_mpp_env_sudo` desenini kullanir (`Environment.sudo()` yok, recordset üzerinden).
- Ezber alan/metod yok: `get_cost_tree` / `get_capacity_planning_data` imzasi dosyadan dogrulanir; supheli alan `fields_get` + kucuk `search_read` ile.
- Skill-first: kod yazmadan ONCE `odoo-15` skill'i yüklenir.

## Güvenlik
- `QUOTE_KEY` sizarsa herkes okur (stok+maliyet) ama YAZAMAZ (v1'de write yok). Rotate: config param'dan degistir, restart gerekmez.
- F5-abuse notu: her Hesapla tam patlatma demek; v1'de kabul, gerekirse faz-1.1'e kisa TTL cache.
- Secret taramasi: `lint_error_log.ps1` + kodda key/şifre aramasi temiz olmali.

## Test / deploy
- Local: `py_compile` + HTML'e `key` siz/siz erisim (403/200), qty sinir (0, 10001 -> 400).
- Staging: Git Deploy + Upgrade/restart (Python degisikligi button-upgrade ile YUKLENEMEZ; mesai disi + oncesi backup). 100 adet quote: brüt = fullx100, net <= brüt; Capacity sayfasi `dynamic_needs` ile capraz kontrol.
- Prod: staging yesil + KULLANICI ONAYI, ayni deploy prosedürü.
- Dogrulama bitti demeden once `verification-before-completion`: komut ciktisi görülmeden "oldu" denmez.

## Faz-2 (bu planda YAPILMAZ)
- Slot 0 web'e ayirma: `get_startup_tree` + `get_slot_list` domain `> 0`, loop 1..9, fallback 0->1 (`matia_procurement_plan.py:2852,2923,2927,2854-2859`).
- Web'den slot-write + rebuild (loginli veya imzali write; RFQ-link/son-yazan-kazanir cözülmeden acilmaz).

## Acik sorular
- `QUOTE_KEY` degeri + dagitimi (linki kimler bilecek)?
- 10000 adet limiti + TR+US sabit filtre uygun mu?
- F5-abuse icin v1'de cache sart mi, degil mi?
