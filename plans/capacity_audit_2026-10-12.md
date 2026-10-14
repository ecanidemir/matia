# Capacity Denetim Raporu — 2026-10-12 (formül + backend + UI)

Kapsam: `matia_stock_planning` (Capacity dashboard Plan/Suppliers&Production/Release, Product Cost dışı).
Kod değişikliği YOK — salt denetim. Odoo 15 kuralları geçerli.
Şüpheli satır aralıkları kodda `fields_get`/okuma ile doğrulanmalı.

## 0. Bloker: staging veri doğrulaması yapılamadı

- `odoo_staging_list_instances` + `odoo_matia_list_instances` ikisi de `url="" db=""` döndü
  (opencode `scripts/start-opencode.ps1` ile başlatılmamış, `.env` yüklenmemiş).
- A1–A8 kod-eşleşmesidir; sayı kanıtı için yeni sessionda önce
  `powershell -ExecutionPolicy Bypass -File scripts/start-opencode.ps1` ile başlatıp
  şu salt-okunur sorguları çalıştır: seçili tek üründe `stock.quant` read_group
  (WHTR/Stock% + WHUS/Stock% + NCR ayrıştırmalı), `_rfq_coverage_map` çıktısı,
  `_rfq_groups` bucket listesi, `release_snapshot` JSON.

## A. Formül denetimi (kod eşleşmesi — hepsi DOĞRU, koru)

- A1. `avail_qty = max(0,TR_stock−TR_res) + max(0,US_stock−US_res)` (şirket-bazlı clamp)
  → `models/stock_planning.py:55-63`.
- A2. NCR hariç (`WHTR/Stock%`, `WHUS/Stock%` only; `NCR` içeren location ayrı listede)
  → `models/stock_planning.py:118-139`.
- A3. Production aynı kural: `avail_tr/avail_us/planned=max(0,need−avail)`
  → `models/matia_procurement_plan.py:388-421`, `1509-1510`, `1754-1780`, `3173-3227`, `3499-3618`.
- A4. Kapsama haritası ürün-bazlı; plan-linkli PO + plan sonrası manuel PO; iptal hariç; UoM çevrimli; satır-id sırası
  → `models/matia_procurement_plan.py:4080-4199`.
- A5. RFQ gruplama (seller+currency+company), `remaining` gruplanır, draft top-up, PO fiyatı ezilmez
  → `models/matia_procurement_plan_rfq.py:173-237`, `258-329`.
- A6. MO dedup `(origin=plan.name, product_id, company_id, state!=cancel)` → relink, yoksa create + `_onchange_move_*`
  → `models/matia_procurement_plan.py:4571-4654`. ŞÜPHE (Orta): anahtarda UoM yok.
- A7. Snapshot `build_snapshot_payload(rev,user,rfq,mo)` + write + acting-user chatter
  → `models/mpp_release_common.py:52-67`, `models/matia_procurement_plan_release.py:333-360`.
  ŞÜPHE (Yüksek): snapshot `write` try dışında → yarı-release riski.
- A8. `no_need` server'da doğru (`order_qty<=0` → `no_need`, attention=False)
  → `models/matia_procurement_plan_release.py:472-476` (client rozet sorunu C2'de).
- A9. Export avail aynası `avail_total ?? avail_tr` → `controllers/procurement_export.py:425-444`, `499-539`.
  ŞÜPHE (Düşük): toplam yoksa tek bacak kullanılır.

## B. Backend (kritik→düşük sırayla)

- B1 (Kritik). `action_unrelease`/`action_close_release`/dashboard wrapper'larda admin kontrolü yok
  → `models/matia_procurement_plan_release.py:80-107`, `432-457` → `_mpp_can_create_docs` yoksa `AccessError`.
- B2 (Yüksek). `write()` guardı yalnız `released` kilitler, `closed` açıkta
  → `models/matia_procurement_plan_release.py:70-78` → `in ('released','closed')`.
- B3 (Yüksek). `action_explode_and_net` + `action_assign_suppliers` başında guard yok (RPC bypass)
  → `models/matia_procurement_plan.py:1372-1384`, `1856-1860` (şüpheli) → `UserError` ekle.
- B4 (Yüksek). `set_targets_and_rebuild` + `save_slot`: explicit lock kontrolü + try-except yok
  → `models/matia_procurement_plan.py:3041-3042`, `3006-3010` → kontrol + try içine al.
- B5 (Yüksek). CSV `group_user`'a tam yetki → `security/ir.model.access.csv:9-12` (şüpheli) → `1,0,0,0`.
- B6 (Yüksek). Dashboard unrelease/close sudo record üzerinden `message_post` (yazar yanlış)
  → `models/matia_procurement_plan_release.py:438-457` → user-env browse deseni (`:344`, `:423`).
- B7 (Orta). Formda kilit görünmez, `note` released iken düzenlenebilir
  → `views/procurement_plan_views.xml:30-40`, `11-24` (şüpheli) → `release_state` alanları + readonly attrs.
- B8 (Orta). `get_startup_tree` legacy planı `slot=0` yazar, state ayrımı yok
  → `models/matia_procurement_plan.py:2851-2857` → `draft` şartı.
- B9 (Orta). `_mpp_write_if_changed` `line.write` korumasız (hot-loop)
  → `models/matia_procurement_plan.py:2607-2609` (şüpheli) → satır-bazı try-except.
- B10 (Orta). `action_unrelease` sebep almaz/loglamaz, draft'ta sessiz no-op
  → `models/matia_procurement_plan_release.py:80-92` → `reason` parametresi + chatter.
- B11 (Orta). `_rfq_bom_chatter` sudo PO üzerinden post → `models/matia_procurement_plan_rfq.py:637-639` (şüpheli) → user-env.
- B12 (Düşük). `create_plan` + slot/price auto-create `create()` korumasız
  → `models/matia_procurement_plan.py:1285-1291`, `2903-2910`, `4683-4689` (şüpheli) → try-except.
- B13 (Düşük). Watcher yalnız `released` izler → `models/purchase_order_mpp_watcher.py:47-50` (şüpheli) → closed dahil veya yorum.
- B14 (Düşük). `copy()` override yok: released plan Duplicate ile snapshot taşınır → `copy()` sıfırla.
- B15 (Düşük). `UserError` EN+ASCII-TR karışık → `models/matia_procurement_plan_release.py:74-77`.

## C. UI (Operate; odoo-15 + impeccable + ui-visual-composition)

- C1 (Yüksek). Tracking `status` ham code (`no_mo`, `rfq_draft`, `unknown`) → `static/src/js/procurement_plan.js:3219` + `models/mpp_release_common.py:25` → label map + `_t()`.
- C2 (Yüksek). `no_need` rozeti aksiyon satırlarıyla aynı → `:3219` + release `:476` → gri `No order` rozeti.
- C3 (Yüksek). Capacity NEED rozeti color-only → `static/src/xml/stock_planning.xml:349` + scss `:739` (şüpheli) → ikon + bold.
- C4 (Yüksek/Orta). `_poStateTr`, supplier/production rozetleri, tablo başlıkları, `Loading…`/`No lines.` `_t()` dışı
  → `procurement_plan.js:2538`, `2619`, `2444`, `2601`, `2677`, `2498`, `2115`, `2661`, `3033` (şüpheli) → `_t()` kapsama.
- C5 (Orta). Attention renk+`!` only → `:3219` → ikon + `Attention` metni.
- C6 (Orta). Üç kilit sinyali dağınık → `xml/procurement_plan.xml:57` + js `:2946`, `:3163` (şüpheli) → tekil status bar.
- C7 (Orta). Tab3 `h6` outline + labelsiz select → js `:3094`, `:3123`, `:3143` (şüpheli) → başlık seviyesi + label.
- C8 (Orta). Klavye tablist eksik → js `:22`, `:135` + xml `:18` (şüpheli) → WAI pattern.
- C9 (Orta/Düşük). Release bar hiyerarşisi + `title`/`aria-label` `_t()` dışı + SCSS token yok → js `:2946`, `:2987`, `:2628`, `:2955` + scss `:1` (şüpheli).
- C10 (Bilgi). Odoo 15 kısıtları temiz — değişiklik yok.
