# Plan: Production plan net-cost semantiği (rolled=net, scratch=sıfırdan)

Tarih: 2026-10-07 | Durum: implementasyon | Deploy: Python var -> Git Deploy +
Upgrade/restart (mesai disi + backup); mevcut planlar Recalculate edilmeden
yeni semantiği göstermez; sonrası Ctrl+F5. Commit/push kullanıcı onayıyla.

## Kullanıcı kararları (2026-10-07, question tool, dördü de önerilen yön)

1. `rolled_usd` NET birim maliyete dönüşür (`net_cost / net_qty`, net=0 ise 0);
   sıfırdan birim maliyet `scratch_unit_usd` adlı YENİ sütunda saklanır,
   `_mpp_crosscheck_vs_cost` scratch'e bağlanır, `est` = satır toplam net maliyeti.
2. Seviye-0 pool/producible maliyete girmez (cascade net yeterli, pool display-only).
3. `corrected_usd` her yerde wins (make hariç, mevcut kural); `unknown` route
   fiyatlıysa buy gibi own maliyet yazar (`_own_usd/_own_try`'a `'unknown'` eklendi;
   MPC `_mpc_price_map` zaten make/kit hariç her şeyi fiyatlıyor, uyumlu).
4. Supplier `grand_total_usd` kasa tutarı kalır (own x order); ağaç est'i toplam net
   malzeme ihtiyacı (bilgi); yaprak seviyede iki baz aynıdır (çapraz kontrol).

## Formül (satır başına, reverse-topo, çocuklar önce)

- `own_net(P) = order_qty(P) x eff_unit(P)` (eff: corrected > 0 ise o — make hariç —
  yoksa buy/subcontract/unknown'da `last_price_usd x _mpp_line_uom_factor`, else 0).
- Paylaşılan çocuğun stoğu kullanıma göre düşülür: çocuğun TOPLAM net maliyeti
  ebeveynlere brüt katkı oranıyla bölünür,
  `pay(P->C) = net_cost(C) x contrib(P,C) / demand(C)`.
  Her ebeveyn sadece kendi gap payını taşır (stokla karşılanan kısım kimseye
  yazılmaz); bir çocuğun payları toplamı her zaman kendi net maliyetine eşittir.
  Satır okuma yok (sadece own satırı) → satırsız/phantom çocuklar şeffaf akar.
- `net_cost(P) = own_net(P) + Σ pay`; `net_unit(P) = net_cost / net_qty` (net > 0).
- Phantom geçişli (own=0, cascade'de netlemez — mevcut `btype` kuralı aynen).
- Kit toplamları (`_aggregate_kits`, `_kits_from_stored`) scratch bazında kalır
  (full-want değeri); özet anahtarı `rolled_total_usd` -> `scratch_total_usd`.
- Supplier `grand_total_usd` = buy+subcontract PO-değeri; unknown route listede
  görünür ama nakit toplama girmez (`unknown_total_usd`/`unknown_count` ayrı).
  Legacy `_plan_summary` supplier filtresi ekranla aynı kapsama genişletildi
  (buy/subcontract/unknown + sellerless) ki Excel eksik satır bırakmasın.

## Doğrulama (staging plan 26, `scratch/fetch_plan26_netcheck.py`, salt-okunur)

- Cascade replika fidelity: 963/963 satır replika==saklı; yaprak buy çaprazı 427/427.
- E2CBAN03 (net 84): scratch 130.341 (değişmez), eski est 10,948.64 ->
  yeni net toplam 10,171.20, net birim 121.0857.
- E2MBAN03 (net 89): scratch 1878.6826, eski est 167,202.75 ->
  yeni net toplam 48,305.60, net birim 542.7595 (stok karşılaması yüksek).
- Kural: implementasyon sonrası staging Recalculate'da bu iki satır birebir tutmalı;
  Product Cost sayfasındaki 130.34 ile scratch (130.341) karşılaştırılır (cross-check).

## Değişiklik

- `models/matia_procurement_plan.py`: line model +4 field
  (`scratch_unit_usd/try`, `scratch_total_usd/try`); `_own_*`'a unknown;
  `_compute_rollup` içinde net-cost bloğu (demand/topo/contrib explode ile aynı
  mantıkta yeniden kurulur — cascade 963/963 replika ile kanıtlı);
  cross-check `scratch_unit_usd`'ye; tree/summary/sub payload'lara `scratch_usd`;
  supplier docstring net-dil.
- `views/procurement_plan_views.xml`: form tree'ye scratch alanları.
- `static/src/js/procurement_plan.js`: başlık "Rolled USD" -> "Net USD" + yeni
  "Scratch USD" sütunu (colspan 14->15, 2 yer); est/tooltip metinleri net-dile;
  export satırına `scratch_usd`; supplier alt-satır "Rolled" -> "Net (gap)".
- `controllers/procurement_export.py`: tree export +1 kolon (csv+xlsx).
- `__manifest__.py`: 15.0.2.6.0.
- DokunulMAyanlar: Product Cost sayfası, RFQ gruplama, capacity sayfası, pool/branch.

## Test

- `py_compile` + `node --check` + TR-karakter taraması (CaseSensitive).
- `scratch/test_net_cost.py`: saf-fonksiyon net-cost (paylaşımlı çocuk, phantom,
  net=0 çocuk, override'lı yaprak) — implementasyon sonrası silinebilir (scratch).
- Staging: Git Deploy + Upgrade sonrası plan 26 Recalculate ->
  E2CBAN03 scratch 130.341 / net toplam 10,921.60 / net birim 130.019;
  Product Cost 130.34 ile cross-check temiz.
- `@odoo-reviewer` salt-okunur denetim.
