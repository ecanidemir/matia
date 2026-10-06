# Expand All Bulk (tek-RPC) — Production Plan Tab 1

## Problem

`_onExpandAll` (procurement_plan.js:523) seviye-seviye `Promise.all` ile
atesliyor: her acilmamis node = 1x `get_sub_bom_cost` RPC. Her RPC icinde:

- 2x `mrp.bom` search (parent cozumu) + 1x child BOM-varligi search,
- `_mpp_tr/us_stock_locs` = TUM internal location'larin taranmasi (168 loc),
- 2x `stock.quant` read_group + 1x `purchase.order.line` search_read
  (`_mpp_last_buys`) + PO read + currency/UoM convert'leri,
- her pass sonunda full `_renderTree` (binlerce satirlik string concat).

Ayrica server'da workers=2: onlarca paralel RPC sadece kuyruk yapar,
hizlanmaz. Sonuc: yuzlerce RPC x (100-400ms + latency + kuyruk) + Nx render.

## Cozum: `get_full_tree(plan_id, top_nets, max_depth=10, cap=2000)`

Tek RPC ile tum ormani server-side acar (search_tree'nin yuruyus deseni +
action_explode_and_net'in bulk yukleme deseni):

**Faz 1 — yapi yuruyusu (ucuz, sadece BOM okumalari):**
kokler = 4 kit BOM'un TUM top'lari (Ekrandaki DOM ile birebir: tree_groups
tum kit satirlarini gosterir, sadece target'lari degil). pid-bazli bom
cache (`_kids_bom`, search_tree ile ayni variant-oncelikli cozum).
Cycle guard: cocuk ata zincirinde varsa item'a `_is_cycle` isareti,
kuyruga eklenmez. depth > max_depth kesilir. cap = ziyaret edilen parent
sayisi (mevcut `fetched >= 2000` ile ayni sinir).

**Faz 2 — toplu veri (sabit sorgu sayisi, N'den bagimsiz):**
tek `_mpp_stock_split(tum pids)` (2 read_group) + tek `_mpp_last_buys`
(1 search_read + 1 PO read) + tek child-BOM-varligi search + tek USD read +
`plan.line_ids` tek pass dict + pool/branch/share map'leri (memory).

**Faz 3 — top-down insa (BFS sira, parent'lar cocuklardan once):**
her node icin satirlar `_mpp_sub_items` helper ile kurulur
(get_sub_bom_cost ile AYNI kod — asagiya bak). Net yayilimi mevcut kural:
`net_cocuk = max(0, net_parent * bom_qty - avail)`; top net'leri client
gonderir (`top_nets` {uid: net}, DOM dataset ile ayni `_rowNet` degeri),
verilmezse server fallback: `line.net_qty` varsa o, yoksa
`max(0, need - avail)`.

Donus: `{'trees': {parent_uid: [items...]}, 'count': N, 'capped': bool}`.
Client `subCache[uid] = {items, level: uid.split('/').length,
groupKey: uid.split(':')[0]}`, `expanded[uid] = true`, `_markCycles`
idempotent tekrar calir, TEK `_renderTree`.

## Kod degisikligi (2 dosya, capacity'ye DOKUNULMAZ)

1. `models/matia_procurement_plan.py`:
   - yeni `_mpp_sub_items(...)` helper: get_sub_bom_cost'un satir-kurma
     blogunun tasinmis hali (snapshot/rolled/seller/UoM/branch, `_is_cycle`
     isaretleme opsiyonlu `ancestors` param'li). `order_dates` olu kodu
     tasinmaz (kuruluyor ama hic okunmuyor).
   - `get_sub_bom_cost` helper'i cagirir (davranis birebir, tek-parent
     cache'lerle) — drift yok.
   - yeni `get_full_tree` (Faz 1-2-3 yukarida).
2. `static/src/js/procurement_plan.js`: `_onExpandAll` tek-RPC'ye iner
   (buton spinner + `topNets` toplama + tek `_rpcPlan('get_full_tree')` +
   cache doldurma + tek render + capped/empty bildirimleri).
   `_expandPath` (arama-ziplama) ve `_onSubBom` (tekil tik) aynen kalir.

## Neden bu siralamada dogru

- Mevcut davranisla birebir: ayni uid semasi (`grup:pid/...`), ayni net
  formulu, ayni cap (2000), paylasilan alt-agac her parent altinda AYRI
  (dedupe yok — arama kuraliyle tutarli).
- Bayat-cache riski yok: sonuc taze hesap, `subCache` uzerine yazilir.
- Yanit hacmi eski toplamla ayni (2000 parent x cocuklari); sadece tek
  transfer + tek JSON parse + tek render.

## Beklenti + deploy

- Nx(DB sorgu seti + network gidis-gelis + kuyruk) -> 1 RPC (birkac sn).
  Agirlik DB'den network'e kayar; DOM render tek seferlik kalir (~10k
  satirda 1-3 sn; yetmezse sonraki adim render sanallastirma).
- Python var -> Git Deploy + Upgrade/restart (mesai disi + backup);
  once staging'de dogrula. JS icin sonrasi Ctrl+F5.
- Dogrulama: `py_compile` + `node --check` + TR-karakter taramasi
  (`Select-String -CaseSensitive`) + `git diff --stat` (capacity dosyasi yok).
