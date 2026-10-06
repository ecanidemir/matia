# Module Health Report — matia_stock_planning (Odoo 15)

Branch: `chore/module-health-overhaul` (push YOK — insan kararı).
Kapsam: procurement dosyaları (düzenlenebilir) + Capacity sayfası
(salt-okunur, dokunulmadı). Canlı DB'ye write YOK.

## Düzeltilen bug'lar (dosya:satır + kök neden)

1. `controllers/procurement_export.py` (düzenleme öncesi ~satır 60):
   non-tree xlsx dalında `return` yoktu → xlsxwriter kurulu iken
   `suppliers` tipinde `None` dönüyordu. Kök neden: CSV dalı kopyalanıp
   xlsx bloğu eklenirken return unutulmuş. Çözüm: bağımsız xlsx dalı
   eklendi (`export_xlsx` içine).
2. Aynı dosya `_export_tree` sonu (~satır 171-226): "Supplier Summary"
   xlsx bloğu ölü koddu (fonksiyonun CSV/xlsx return'lerinden sonra,
   tanımsız `total`/`groups` adlarıyla → erişilse NameError).
   Çözüm: blok ait olduğu yere (`export_xlsx` non-tree dalı) taşındı,
   ölü kopya silindi.
3. `static/src/js/procurement_plan.js` `_sortIcon`: `treeSort.dir`
   numerik (-1/1) iken `'asc'` stringiyle karşılaştırılıyordu → ikon
   hep desc gösteriyordu. Çözüm: `dir === 1` karşılaştırması.
4. `models/matia_procurement_plan.py` `action_assign_suppliers`
   (~satır 595): kur çevrimi korumasızdı → eksik kurda ham traceback
   ile tüm önizleme çöküyordu (diğer kollarda sessiz-0 politikası
   vardı). Çözüm: `_mpp_price_in_plan_currency` helper'ı — kur yoksa
   teknik detay log'a, kullanıcıya ürün-adlı net UserError.

## Silinen ölü kod / sadeleştirme

- `_export_tree` sonundaki ölü Supplier-xlsx bloğu silindi (yukarıda #2).
- last-buy + pricelist kollarındaki tekrarlı kur-çevirimi helper'a
  indirgendi (davranış aynı, hata politikası netleşti).
- `get_rfq_preview` + `action_create_draft_rfqs` UI'dan çağrılmıyor
  ama **public RPC API olarak korundu** (kaldırma = API değişikliği).
- `_(...)` kapsaması yeterli (JS `_t` kullanıyor); adlandırılmış
  sabitler zaten mevcuttu (`_MPP_KIT_BOMS`, `_MPP_MAX_LEVEL`,
  `_MPP_TR_COMPANY_ID`); hardcoded şirket/lokasyon ID yok (grep temiz).

## Stabilite (Faz 3)

- Ek-A sözleşme tablosu `plans/module_health_overhaul.md` içinde
  dolduruldu (14 satır, kod okumasıyla doğrulandı).
- ACL: procurement modelleri `base.group_system` only — menü + route
  ile tutarlı admin-only tasarım, değişiklik yok.
- Sessiz `except` noktalarına `_logger.warning` eklendi (rollup TRY,
  `_mpp_line_try`); sıfır-dönüş davranışı değişmedi.

## Performans (Faz 4, DB turu önce → sonra)

- `action_assign_suppliers`: ürün-başı `search_read` (N) + satır-başı
  `Supplier.search_read` (N) → 3 sabit toplu sorgu + mevcut browse'lar.
- `_mpp_last_buys`: ürün-başı `search_read` (N) → 1 toplu sorgu,
  Python'da ürün-bazında ilk-5 gruplama (aday kümeleri birebir aynı).
- Değişmeyenler (zaten verimli): quant/PO/MO tarafı `read_group`
  kullanıyor; ağaç render tek DOM yazımı; sub-BOM client-cache'li.

## Doğrulama (Faz 5)

- `python -m py_compile`: 5 Python dosyası OK.
- Yapı grepi: `export_xlsx` → CSV+xlsx return; `_export_tree` →
  CSV+xlsx return; `add_worksheet` 2 adet; `heryerde` yok.
- `node --check`: 2 JS dosyası geçti (hata çıktısı yok).
- XML parse (`xml.dom.minidom`): views + data XML'leri OK.
- `@odoo-reviewer` final denetimi: bu turda çalıştırılmadı (aşağıya bak).

## Reviewer denetimi (@odoo-reviewer, salt-okunur) + kapanış

Doğrulanan ve düzeltilenler:
5. `matia_procurement_plan_rfq.py` 3 metotta `self.ensure_one()` —
   JS `_rpcPlan` ids göndermiyor (boş recordset) → `Expected singleton`
   hatası, `action_create_supplier_rfq` (TR/US RFQ butonları) fiilen
   kırıktı. Çözüm: 3 `ensure_one` kaldırıldı (metotlar `plan_id` ile
   sudo-browse yapıyor, `self` kaydına dokunmuyor) + yorumu eklendi.
6. Çift `@api.model` tekrarı (`_mpp_price_in_plan_currency` üstünde,
   Faz 2-4 editi sırasında girmiş) — biri silindi.
7. `UserError(... % exc)` ile ham traceback diyaloğa sızıyordu (2 nokta)
   → `_logger.exception` + genel mesaj.
8. Sessiz `except`ler (UoM fallback, tree-FX) → `_logger.warning`
   eklendi; MO `str(exc)` satır-nedeni korundu (UI'da satır teşhisi
   için gerekli) + `_logger.exception` eklendi.
9. `ir.sequence` kaydı yoktu (`data/` klasörü hiç yoktu) →
   `next_by_code('matia.procurement.plan')` hep False dönüp tüm planlar
   `MPP` adını alıyordu. Çözüm: `data/matia_procurement_plan_sequence.xml`
   (prefix `MPP-`, noupdate korunur sayaç) + manifest `data` girişi
   (ara süreçte dosyaya yanlışlıkla Python coding satırı konmuş,
   XML parse ile yakalanıp düzeltildi).

Bilinçli olarak DEĞİŞTİRİLMEYENLER (insan kararı gerekir):
- `action_explode_and_net` içindeki `line_ids.unlink()` RFQ/MO sonrası
  yeniden patlatmada satır-izini (`purchase_order_id`, `mo_id`) siler —
  engel koymak davranış değişikliğidir.
- RPC metotlarında grup kontrolü yok (sudo ile ACL baypas); menü+route
  admin-kilitli ama doğrudan RPC açık. Yetki sıkılaştırma canlı erişimi
  etkiler.
- `mrp.bom.search` N+1 döngüleri (explode/tree yolu) — toplu okumaya
  çevirme ayrı test ister.
- Minör: `create_date/create_uid` yeniden tanımı, `xpath` yerine alan
  adı (rfq views), Excel/JS `_()` eksikleri, `@api.model` tutarlılığı.

## İNSAN ADIMLARI (sırayla)

1. ~~`node --check` (tüm JS) + XML parse doğrulamasını çalıştırın
   (bu ortamda yapılmadı).~~ YAPILDI — PY-OK (5 dosya), JS1-OK,
   JS2-OK, XML-OK (tüm xml, xml.dom ile).
2. ~~`@odoo-reviewer` ile salt-okunur final denetimi isteyin.~~ YAPILDI
   (yukarıdaki bölüm); kapatılmayan maddeler bilinçli erteleme.
3. Staging yok: değişiklikleri canlıya almadan önce odoobulut
   panelinden backup alın; Python değişikliği Git Deploy + servis
   restart gerektirir (mesai dışı; `button_immediate_upgrade` Python
   yüklemez).
4. Canlı test senaryoları: procurement önizleme (kur-eksik ürün),
   tedarikçi RFQ oluşturma (tek + toplu), suppliers/tree xlsx export,
   MO oluşturma.
5. Push/merge kararı + branch temizliği.
6. Kalıcı bulgular `docs/discovery.md` sonuna eklenecek (henüz
   eklenmedi).

## TAM TARAMA TURU (2026-10-06, capacity dahil)

Kullanıcı isteği: capacity dahil her dosyaya bakılması, bakılmamış
yer kalmaması, tüm iyileştirmelerin yapılması, çalışan yerin
bozulmaması. Bu turda capacity yasağı kaldırıldı.

**Düzeltilenler:**
- procurement `get_sub_bom_cost` `_is_cycle` göndermiyordu →
  client uid yolundan cycle türeten `_markCycles` helper
  (`procurement_plan.js`); capacity'deki path kontrolüyle aynı
  mantık. Döngüsel BOM'da sınırsız derinleşme riski kapandı.
- Capacity refresh `_fetchPlanningData` hatayı yutup success toast
  gösteriyordu → `_lastFetchOk` bayrağı, hatada toast yok.
- Capacity expand-all catch sessiz + final toast hep success →
  `_expandFails` sayacı + kısmi-başarı uyarısı.
- Search input'a 150ms debounce (`stock_planning.js`).
- Ölü sort `code` dalı silindi (capacity `th` yok).
- Dinamik `_t` concat 2 nokta düzeltildi (`_onFill`, capacity
  `_onSort`).
- Ölü `this.targets` yazımları silindi (okuyan yok).
- Capacity model: `_MSP_TR/US_COMPANY_ID` + `_MSP_FLOAT_EPS`
  sabitleri; ölü `if max_dev<0` guard ×2 silindi; `ceil`lere
  epsilon (tam sayılar aynı, float gürültüsü +1'i önlenir).
- `main.py`: bare except ×2 → `(TypeError, ValueError)`; `need`
  dalında bozuk girişte `val=0` fallback (xlsxwriter çöküyordu);
  `json.loads` koruması. `procurement_export.py`: `json.loads`
  koruması.
- SCSS ölü temizlik: procurement scss'ten capacity sınıflarını
  kullanan ağacın kopya stilleri; capacity scss'ten ebeveyni
  olmayan `.msp-add-col-input` + mobil `.msp-control-bar` bloğu.
- Template yorumu `clamped to 5` → 8 (JS + SCSS 1-8 ile tutarlı).

**Bilinçli dokunulmayanlar (risk):** capacity menü `group_user`
(export'a grup kilidi eklenmedi — bozardı); location/env kurulum
tekrarı (iki metot farklı include mantığı); unlink iz-silme; RPC
grup kontrolü; `mrp.bom.search` N+1'leri.

**Canlı notu:** MCP bağlı ama `matia.procurement.*` model yok
(Fault 2) — canlı alan doğrulaması upgrade'e kadar bloklu.

**Doğrulama:** PY-OK, JS1-OK, JS2-OK, XML-OK.

## PERFORMANS PAKETİ (2026-10-06, kullanıcı seçimi)

Kullanıcı 4 paketten "Performans paketi"ni seçti. JS API değişmedi;
tüm değişiklikler `matia_procurement_plan.py` içinde.

**Önbellekli ağaç (lazy recompute):**
- Yeni alan `built_target_json`: satırlar hangi hedeflerle
  kurulduysa onun kopyası (`action_explode_and_net` sonunda yazılır).
- `get_tree_with_cost`: satırlar mevcut + hedefler aynıysa tam
  yeniden kurulum ATLANIR (unlink + yüzlerce create/write yok).
  Özet `_plan_summary` + `_kits_from_stored` ile salt-okunur kurulur
  (kayıtlı rolled değerlerden; `_compute_rollup` ile aynı
  `_aggregate_kits` yardımcısını kullanır, sonuç birebir aynı).
- Yan fayda: yeniden görüntüleme artık satırlardaki RFQ/MO
  izlerini silmiyor (unlink tehlikesi bu yolda kapandı).
- Hedef değişirse veya eski planlarda alan boşsa tam kurulum çalışır.

**Toplu sorgular (N+1 → 1):**
- Ağaç `has_bom` yedeği: satır-başı `mrp.bom.search` → eksik
  şablonlara tek `in` sorgusu.
- `get_sub_bom_cost` `has_bom`: çocuk-başı search → tek `in`
  sorgusu.

**No-op write eleme:**
- Yeni `_mpp_write_if_changed`: değerler aynıysa `write`
  atlanır (UPDATE + stored-computed zinciri yok). Assign
  döngüsündeki 3 write + rollup write'ı buna bağlandı. Many2one
  karşılaştırması id ile yapılır.

**Önce/sonra (plan başına, N = satır sayısı):**
- Yeniden görüntüleme: ~2N write + N okuma + patlatma → ~10 sabit
  okuma, 0 write.
- İlk kurulum: -2N `mrp.bom.search`, değişmeyen satırlarda -N write.

**Doğrulama:** PY-OK. Canlı upgrade sonrası ilk açılışta tam
kurulumun bir kez çalışacağı, ikinci açılışta önbellekten
geleceği test edilmeli (insan adımı).
