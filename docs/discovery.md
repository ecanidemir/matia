# Discovery - Matia Odoo Hub Bilgi Deposu

> **Amaç:** Bu dosya, `matia.odoobulut.com` (Odoo 15) sunucusu hakkında keşfedilen KALICI bilgileri içerir.
> **KURAL:** AI her seansta bu dosyayı OKUR ve yeni keşfedilen önemli bilgileri dosyanın SONUNA ekler.
> **Nedir bu bilgiler?** Yapılandırma detayları, hata sebepleri ve çözümleri, model ilişkileri, çoklu-şirket ayarları, özel modüller, tespit edilen tutarsızlıklar.
> **Ne DEĞİLDİR?** Geçici notlar, denemeler, script çıktıları. Bunlar `scratch/` altında kalır.

---

## Bağlantı Bilgileri

| Parametre | Değer |
| --- | --- |
| URL | <https://matia.odoobulut.com> |
| DB | matia.odoobulut.com |
| Odoo Sürüm | 15.0 (20250101) |
| Transport | XML-RPC |
| SSH | Yok (sadece XML-RPC API) |
| Toplam Kurulu Modül | ~211 |
| Şirketler | ID=1: Matia Robotics Mekatronik A.Ş. (TR), ID=2: Matia Robotics (US) Inc. |

## Kritik Yapısal Bilgiler

- **Şirketler bağımsız root şirketlerdir** — parent-child ilişkisi yoktur. Bu nedenle multi-company validasyonları (`_check_company_auto`) sıkı çalışır.
- **Özel modüller:** `whitelabel`, `mrp_ux`, `mrp_analytic_link`, `mrp_maintenance_link`, `bsi_merge_any_purchase`, `sh_hide_menu`, `web_pwa_oca`, `l10n_tr_account_einvoice` (Foriba)
- **Work Center'lar:** "Montaj Alanı" (ID 1, Şirket 1), "Elektronik Alanı" (ID 2, Şirket 1)
- **`mrp.routing.workcenter` kayıtları** "Montaj - {dakika}" formatında isimlendirilmiştir
- **BOM Tipi phantom (kit) olan ürünler:** TekRMD Common Parts, TekRMD Common Screws, TekRMD Outdoor Parts, TekRMD Seat Parts — tümü `company_id=False`

## Odoo 15 API Notları

- XML-RPC çalışıyor (JSON-2 yok, Odoo 19 ile gelmiştir)
- API key username/password yerine kullanılabiliyor (Odoo 15.0 sonrası)
- Odoo `copy()` metodu: varsayılan değerler `{'default': {'field': value}}` olarak geçilmeli, flat `default_field=value` değil

## Bilinen Hata Desenleri

### Multi-Company BOM Kopyalama

- `company_id=False` olan phantom BOM'lar çoğaltılırken "Uyumsuz şirket kayıtları" hatası alınabilir
- **Sebep:** BOM satırları `check_company=True` olan alanlara sahipse, copy sırasında `_check_company_auto` validasyonu takılır
- **Çözüm:** API ile `copy(id, {'default': {'company_id': 1}})` kullanarak belirli bir şirkete ait kopya oluşturun
- Orijinal BOM'da `company_id` değiştirmeye çalışılırsa Odoo uyarı verir (ürün kullanılmışsa engellenebilir)

## TekRMD Stok & Kapasite Planlama Modülü Keşifleri

### Reçeteler (BOM)

- **TekRMD Common Parts v2** (ID: 1766, 84 parça): Base grubu cihaz parçaları.
- **TekRMD Outdoor Parts** (ID: 1737, 9 parça): Outdoor özelliği bileşenleri.
- **TekRMD Seat Parts** (ID: 1738, 7 parça): Transfer Board / Seat özelliği bileşenleri.

### Stok ve NCR Lokasyonları

- **TR Lokasyonları (ID=1):** `WHTR/Stock%` altında 149 internal lokasyon (OTS Storage, Raw Storage, Spare Storage vb.).
- **TR NCR:** `WHTR/NCR Alanı` (ID: 333). Net stok hesaplamasına katılmaz, bilgi amaçlı gösterilir.
- **USA Lokasyonları (ID=2):** `WHUS/Stock` (ID: 26) ve `WHUS/Stock/Spare Storage` (ID: 331).
- **USA NCR:** `WHUS/NCR Storage` (ID: 332). Net stok hesaplamasına katılmaz, bilgi amaçlı gösterilir.

### Modül: `matia_stock_planning`

- Envanter altında "Cihaz Kapasite Planı" ekranı.
- Tek bir RPC çağrısıyla 3 reçetedeki 103 tekil ürünün stoklarını `stock.quant` üzerinden çeker.
- TR / USA lokasyon filtreleme, Kullanım Miktarını Gizle/Göster, 3 adede kadar dinamik hedef cihaz sütunu ekleme.
- Ekranda o an görünen haliyle Excel (.xlsx) dışa aktarma (xlsxwriter / CSV fallback).
- Alt reçeteler (Sub-BOM) ana tabloda aynı sütun yapısıyla girintili satır olarak açılır; açık alt reçeteler Excel çıktısına da dahil edilir.
- Bottleneck (darboğaz) uyarısında ürün adı yanında stok miktarı gösterilir: `[CODE] Name (X Units)`.

### Odoo 15 Teknik & Mimari Notlar

- **`self.env` vs Recordset `sudo()`:** Odoo 15'te `Environment` nesnesinin doğrudan `.sudo()` metodu yoktur (`AttributeError: 'Environment' object has no attribute 'sudo'`). Doğru desen:

  ```python
  all_company_ids = self.env['res.company'].with_context(active_test=False).sudo().search([]).ids
  env_sudo = self.with_context(allowed_company_ids=all_company_ids, active_test=False).sudo().env
  ```

- **Pasif/Arşivlenmiş Şirketler (Multi-Company Bypass):** Bir şirket (örn. USA) pasife alınmışsa veya kullanıcının aktif şirket seçiminde yoksa bile stoklarını çekebilmek için `active_test=False` ve `allowed_company_ids` ile `sudo()` ortamı oluşturulmalıdır.
- **Python Değişikliklerinin Yansıması:** Modüldeki Python kodu değişiklikleri XML-RPC ile `button_immediate_upgrade` yapılarak belleğe yüklenemez; Cloudpepper üzerinden Git Deploy veya Odoo servis restart gereklidir.
- **Rezerve Stok & Net Kapasite Hesabı:** `stock.quant`'tan `quantity` (On-Hand) yanı sıra `reserved_quantity` alanı da okunur. Tablodaki "Net Stock" sütunu fiziksel toplam eldeki stoku gösterir; rezerve miktarlar (`reserved_quantity`) ise tüm üretilebilir cihaz (`max_devices`) ve ihtiyaç (`req_20_val`, dinamik hedefler) hesaplamalarından (`avail_qty = stock_qty - reserved_qty`) düşülerek net kapasite hesaplanır. Hücre tooltip'inde rezerve ve net kullanılabilir miktar detaylı görünür.
- **Dinamik Sütun Görünürlüğü (BOM Qty, Reserved, NCR):** Kullanım miktarı (BOM Qty), Rezerve (Reserved) ve NCR Storage sütunlarının her biri toolbar'daki butonlarla bağımsız gizlenip gösterilebilir; Excel export da o anki görünür sütunları baz alır.
- **On Hand (incl. reserved) & Rezerve / NCR Ayrımı:** Sütun adı "On Hand (incl. reserved)" olarak güncellendi. Toplam eldeki fiziksel stoku gösterir; üretilebilir cihaz kapasitesi ve ihtiyaç adetleri hesaplanırken Rezerve ve NCR miktarları hesaba katılmaz.
- **Sütun Başlığı Tıklama / Sıralama Stili:** Sıralanabilir başlıklara (`msp-th-sortable`) tıklandığında veya odaklandığında başlığın beyaza bürünmesi `:active` ve `:focus` durumlarına `#0f172a` / `#334155` ve `user-select: none` kuralları verilerek düzeltildi.
- **Alt Reçete (Sub-BOM) Dinamik Sütun & Önbellek Yönetimi:** Dinamik hedef sütunu eklendiğinde veya silindiğinde `sub_bom_cache` otomatik temizlenir. `_isSubBomCacheValid` kontrolü ile eksik hedef içeren eski önbellekler elenir, açık olan alt parçalar yeni hedeflerle otomatik re-expand edilerek ekrandaki değerlerin `-` gelmesi engellenir.
- **Mobil Görünüm & Scroll Kilidi Düzeltmesi:** Mobil ekranlarda (`@media (max-width: 991px)`) `.table-responsive` içindeki `calc(100vh - 380px)` sınırlaması kaldırılarak iç/dış çift kaydırma kilidi çözüldü; ana kapsayıcıya `6rem` alt boşluk verilerek Common Screws dahil en alttaki bileşenlerin mobil tarayıcı çubukları arkasında kaybolması önlendi.
- **Mobil Lokasyon Rozetleri Yan Yana:** `.msp-filter-group` içine `.msp-loc-options` sarmalayıcı eklendi; mobilde TR/USA rozetleri `flex-wrap: nowrap` ile yan yana durur, `.loc-sub` (WHTR/Stock, WHUS/Stock) `display:block` ile alt satıra alınarak genişlikten tasarruf edilir.
- **Ürün Sütunu Hizalama & Kaydırma:** Reçetesi olmayan satırlarda boş `msp-bom-spacer` yerine solda nokta ikonu (`.msp-no-bom-dot`, `fa-circle`) kullanılarak tüm ürün adları aynı hizaya getirildi; buton ve spacer genişliği 22px'e eşitlendi. Ana ürün hücresi (`td-product`, `.prod-code`, `.prod-name`) `white-space: nowrap` + `width:auto` ile içerik bitiminde biter, alt satıra geçmez. Alt ürünlerde girinti span'i (`sub-bom-indent`) kaldırıldı (ikon + satır rengi yeterli sinyal); `[part code]` (`sub-prod-code`) `nowrap`, ürün adı wrap olabilir.

## Cloudpepper Infra (2026-09-25)

- Server V15-12C24R-199.247.21.64: 12 CPU, ~24GB RAM, Ubuntu 22.04, Python 3.10, Odoo 15.0 Community (15.0.20240109, Update pending). Tek instance: matia.odoobulut.com, workers=2.
- 2 haftalik Monitoring: CPU avg <%10 idle (max %20-50, 14 Eylul %90 spike), Memory %70-85 surekli yuksek (20.5GB used), Disk stabil ~250GB, DB connections 120-290/500 anormal yuksek (2 worker icin beklenmez).
- Config: limit_time_cpu=600 (def 60), limit_time_real=1200 (def 120) cok yuksek -> takilan istekler worker bloklar, memory/connection sismesi suphesi. log_level=error, proxy_mode=True, list_db=False dogru.
- Tavsiye: once limit_time dusur (120/240), Show-all options + PostgreSQL sekmesi incelenmeli (max_cron_threads, db_maxconn, limit_memory_soft/hard), sonra memory izlenip workers 4 e kademeli artirim.


- Kullanim (2026-09-25): TR+USA 24 saat, ayni anda max 2 kullanici, cok hafif kullanim; ileride max 4 eszamanli. 12C/24GB server bu yuk icin oversize, workers=2 su an yeterli.


## Cloudpepper Config Baseline (2026-09-25, PDF 4 sayfa)

- workers=2, db_maxconn=64, max_cron_threads=2, limit_time_cpu=600, limit_time_real=1200, limit_time_real_cron=-1, limit_memory_soft=2147483648, limit_memory_hard=2684354560, limit_request=8192, longpolling_port=8072, proxy_mode=True, list_db=False, db_name set, log_level=error, smtp localhost:25.
- Oneri: limit_time_cpu 120, limit_time_real 240, limit_time_real_cron 300, max_cron_threads 1, db_maxconn 32; workers 2 sabit. Save+Restart mesai disi, oncesi backup.
- MCP notu: odoo_matia default instance test-argerobotik.cloudpepper.site isaret ediyor ve auth fail veriyor; matia prod canli kontrolu yapilamadi, sadece config uzerinden oneri verildi.


## MCP Env Karisikligi Cozumu (2026-09-25)

- Sorun: Windows User-level env ODOO_URL/ODOO_DB/ODOO_USERNAME test-argerobotik.cloudpepper.site isaret ediyordu; workspace .env (matia.odoobulut.com) eziliyordu, odoo_matia yanlis projeye baglaniyordu.
- Cozum: User-level 3 degisken silindi (kullanici onayli). Bu oturumun MCP prosesi eski env ile basladigi icin restart/reconnect sonrasi matia degerlerini gorecek.
- UYARI: argerobotik projesi bu User-level degiskenlere bagimli olabilir; o projenin workspace inde kendi .env dosyasi olmali, yoksa eklenmeli.


## MCP Env Yukleme Notu (2026-09-25)

- opencode.json {env:ODOO_*} yalnizca proses environment'indan okunur; workspace .env OTOMATIK yuklenmez. Bos gelirse MCP url/db bos gorunur.
- Cozum: opencode'u powershell -ExecutionPolicy Bypass -File scripts\\start-opencode.ps1 ile baslat (once .env'i yukler). Dogrudan opencode komutuyla baslatirsan MCP baglanamaz.
- Mevcut scripts/load_env.ps1 iki ust klasordeki odoo/.env dosyasini ariyor (o dosya yok) - bu workspace icin start-opencode.ps1 kullanilmali.


## Canli API Kontrolu (2026-09-25, dogrudan XML-RPC)

- Baglanti OK (uid=2, server 15.0-20240109). Aktif internal kullanici: 8, portal: 0. Kurulu modul: 212.
- Aktif cron: 35, suresi gecmis: 0 -> cron saglikli, max_cron_threads 2->1 guvenli.
- mail.mail: outgoing 0, sent 3, exception 85 -> giden posta BOZUK (sebepler: OAuth access token hatasi, SMTP 'Connection unexpectedly closed'). localhost:25 postfix/OAuth ayri konu olarak incelenmeli.
- MCP notu: odoo_matia MCP bu oturumda hala bos env gosteriyor (eski proses); canli kontroller dogrudan XML-RPC ile yapildi.

## Goc Envanteri (2026-09-25, Odoo 15 -> 19 planlama)

- Baglanti OK: 15.0-20240109, uid=2. Aktif kullanici 8 (tamami internal, portal 0). Kurulu modul 211 (99 Odoo standard + 74 Projetgrup/TR + 35 OCA + 2 diger 3rd-party + 1 matia_*).
- Kritik sayilar: res.partner 394 (94 musteri / 227 tedarikci / 230 sirket); product.product=product.template=1174 (varyantsiz 1:1); mrp.bom 511 (1568 satir; 152 normal / 6 phantom / 353 subcontract; sirket: 495 TR + 9 US + 7 global); sale.order 152 (149 sale + 3 cancel, 0 acik); mrp.production 2982 (1610 cancel + 1356 done + 16 acik); purchase.order 159 (157 purchase + 2 acik); stock.picking 2032 (1684 done + 334 cancel + 14 acik); stock.quant 9442 (4635 qty>0, 3745 negatif! 140 rezerve); stock.move 42063 (33954 done + 7684 cancel).
- Yan veriler: pricelist 2 + 123 item; workcenter 6 + routing.workcenter 151 + workorder 709 (3 acik); uom 24; product.category 8; supplierinfo 1443 (1042 template'te seller var); warehouse 2 (WHTR/TR, WHUS/US); location 168 (154 internal); attachment 749 (481'i sale/mrp/purchase/picking'e bagli); res.groups 81.
- Tarih araligi: sale 2022-12-28..2026-09-10 (2026'da 60 siparis); mrp 2022..2026-09-22, 2024'te 2701 MO spike (cogu iptal, toplu deneme/ice aktarma suphesi); purchase 2023..2026-07-20 (2024'te 115); picking 2022-11..2026-09-21.
- KRITIK BULGU muhasebe: kullanilmiyor denmesine ragmen account.move posted=30574 (stock_account/mrp_account otomatik uretmis). Goc'te muhasebe tasinmaz ama Odoo 19'da valuation/CoA karari sart.
- KRITIK BULGU stok kalitesi: 3745 negatif quant var (stock_no_negative kurulu olmasina ragmen). Cutover oncesi envanter sayimi + negatif temizligi sart; quant birebir tasinmaz.
- `matia_*` prefixli tek modul: matia_stock_planning (AbstractModel matia.stock.planning, 7 xml_id, ~517 satir py + 763 satir legacy JS + 427 satir QWeb + 247 satir xlsx controller). Diger ozel gorunumluler matia_* degil: mrp_ux, mrp_analytic_link, mrp_maintenance_link, whitelabel (Projet/Projetgrup), sh_hide_menu (BulutKobi), bsi_merge_any_purchase, web_pwa_oca. En buyuk port riski 74 Projetgrup l10n_tr modulu (19 karsiligi yoksa kurulmaz karari verilmeli).
- Urun yapisi: template=product (varyant yok) gocu kolaylastirir. sale_ok 252 / purchase_ok 1013; detailed_type: 1096 storable, 68 consu, 9 service, 1 gift. BOM hard-coded ID'ler: 1766/1737/1738/1736 (19'da isme gore arama oncelikli olmali).

## Tedarik & Uretim Onizleme Plani (2026-10-01, preview-only, admin-only)

- Yeni bagimsiz kod: `matia.procurement.plan` + `matia.procurement.plan.line` (`models/matia_procurement_plan.py`), 3 asamali client action (`tag matia_procurement_plan.dashboard`), ayri JS/QWeb/SCSS (`mpp-` prefix), ayri Excel route `/matia_procurement_plan/export_xlsx`.
- Mevcut Capacity sayfasina DOKUNULMADI (stock_planning.js/xml/views, controllers/main.py ayni). Manifest'e `purchase` depends + yeni dosyalar eklendi; menu ayni app altinda 2. menü, `groups=base.group_system` (sadece admin).
- Taslak PO/MO acma YOK (2. kademe, `action_create_drafts` henuz yazilmadi). Plan satirlari kalici saklanir (seller_id/order_qty/price snapshot) ki 2. kademe ayni veriyi kullansin.
- Canli dogrulama: `stock.warehouse.orderpoint` company 1'de 0 kayit (otomatik min/max ikmal YOK); rotalar Buy(5)/Manufacture(6)/Resupply Subcontractor on Order(9) aktif; subcontract BOM 353 (company 1 ornekli). Son-tedarikci mantigi `purchase.order.line order by date_planned desc` ile calisiyor (ornek 1151 -> partner 1226).
- Kural kararlari: TR-only netleme (`WHTR/Stock%`, NCR haric, `max(0,onhand-reserved)`), yoldaki (onayli PO + acik MO) sadece bilgi kolonu, tedarikci basina tek RFQ + birlestirme uyarisi (2. kademe), snapshot fiyat (TRY, vergisiz), UoM cevrilmis tutar.
- 2026-10-05 ek: son-alim fiyati kendi para birimi + o tarihteki USD kuruyla USD kolonlari (`last_price`, `last_currency_id`, `last_price_usd`, `last_date` as Mon YYYY); tum onizleme ekrani %100 Ingilizce (Turkce kelime 0, ASCII taramayla dogrulandi). Rolled-up USD: patlatmada `edge_json` {parent:{child:qty}} saklanir, `_compute_rollup` yapraklardaki `last_price_usd`'yi kullanim miktarıyla carpip yukari toplar (operasyon maliyeti yok, make/phantom sadece cocuk toplami); kit toplam + genel toplam Adim 3 + Excel'de. Fiyat snapshot artik siparissiz buy/subcontract satirlarina da yaziliyor.
- 2026-10-05 Kademe 2 (draft RFQ, v15.0.2.0.0): yeni dosya `models/matia_procurement_plan_rfq.py` (`_inherit`, Kademe 1 + Capacity untouched): plan state `rfq_created` (selection_add), `purchase_order_ids` M2M (rel `matia_proc_plan_po_rel`, silinmez link), `rfq_count`; satirda `purchase_order_id`/`purchase_line_id` izlenebilirlik. `get_rfq_preview` (salt-okunur) + `action_create_draft_rfqs(plan_id, confirm)` (tedarikci,endusuk para birimi) gruplu: sadece buy+order_qty>0+seller; `price_unit=last_price`, PO currency=snapshot (karisik kurda supplier basina para birimi adedi kadar RFQ); TR incoming picking (IST Receipts), origin=plan.name, draft (RFQ). Tekrar korumasi: mevcut RFQ varsa `needs_confirm` + liste doner, `confirm=True` ile yeni RFQ eklenir. `_plan_summary` override supplier gruplarina `rfqs` + ozet `rfqs`/`rfq_count` enjekte eder. JS/XML sadece procurement dosyalarinda: Adim 3'te Preview/Create/Confirm butonlari + olusturulan RFQ listesi; form/tree inherited view `views/procurement_plan_rfq_views.xml`. TDD simulasyon (scratch/test_rfq_grouping.py) RED->GREEN; py_compile/XML/node --check OK, TR-karakter 0. Deploy: Git Deploy/restart gerekli (Python), mesai disi + backup; Kademe 1 henuz deploy edilmemisti (canlida model yok).

## Staging Instance (2026-10-05)

- URL/DB: `staging-matia.odoobulut.com` (kullanici adi/API key prod ile ayni, sadece adres farkli). Dogrulama: XML-RPC `version` 15.0-20240109, `authenticate` OK (uid=2), `res.users` aktif=8.
- Env: `ODOO_STAGING_URL/DB/USERNAME/PASSWORD/TRANSPORT` + `ODOO_MCP_ENABLE_WRITES_STAGING=1` (`.env` + `.env.example`).
- MCP: `opencode.json`'da 2 server — `odoo_matia` (prod, `ODOO_MCP_ENABLE_WRITES` yok = default salt-okunur) + `odoo_staging` (staging, writes staging env'den acik). Kural: prod API ile salt-okunur, modul denemeleri staging'de, staging'e duruma gore yazmak serbest.
- NOT: yeni MCP server icin opencode restart gerekir (`scripts/start-opencode.ps1` ile baslat, `.env` otomatik yuklenir).

## Staging Upgrade Hatasi (2026-10-05, procurement_plan_rfq_views.xml)

- `button_immediate_upgrade` ParseError verdi: `View inheritance may not use attribute 'string' as a selector` (`view_matia_procurement_plan_form_rfq`, satir 5).
- Sebep: `<page string="Lines" position="after">` — Odoo 15 kalitimda `string` secici olarak yasak.
- Cozum: `<xpath expr="//page[field[@name='line_ids']]" position="after">` + yeni page'e `name="draft_rfqs"` eklendi. Kural: inherit secici olarak sadece `name` (field) veya `xpath expr` kullan, `string` ile secme.
- Ek bulgu: staging `ir.module.module` `installed_version=15.0.2.0.0` / `latest_version=15.0.1.0.0` gosteriyordu ve `ir.model`'de `matia.procurement.*` yoktu — hata duzeltilip Git Deploy + Upgrade tekrarlanmali.

## Module Health Overhaul (2026-10-06, chore/module-health-overhaul)

- JS RPC cagrilari `model/method/args` formunda `self` bos recordset ile gelir; boyle cagrilan metoda `ensure_one()` konursa her cagri `Expected singleton` patlar (rfq 3 metodu, TR/US RFQ butonlari kirikti). Kural: JS'ten cagrilan metoda `ensure_one` koyma.
- `next_by_code()` fallback'i sessizce ayni ismi uretir: `data/` sequence kaydi yoksa tum planlar `MPP` adini alir. Kural: sequence kullanan her `create` icin `data/*.xml` kaydini manifest `data` sirasina ekle.
- Supplier-preview xlsx blogu `_export_tree` icinde return sonrasi olu koddu ve tanimsiz `total` kullaniyordu; `export_xlsx` non-tree dalina tasindi.
- `assign_suppliers` + `_mpp_last_buys` N+1 batch'lendi (urun-basi search_read kaldirildi); kur cevrim hatasi artik urun-adli `UserError`, teknik detay log'da.
- ACL: procurement modelleri yalniz `base.group_system` (admin-only tasarim); dogrudan RPC cagrilari grup kontrolsuz sudo ile calisir — bilinclilik karari, raporda (`plans/module_health_report.md`).
- Push YOK, 4 faz commiti branch'te; deploy + upgrade insan adimi.

## Tam Tarama Turu (2026-10-06, capacity dahil)

- Procurement `get_sub_bom_cost` `_is_cycle` gondermiyordu; client `_markCycles` helper ile uid yolundan cycle turetiyor (capacity'deki path kontrolunun aynisi). Kural: server cycle bayragi gondermiyorsa client uid-yolu ile ayni-dal tekrarini yakala.
- Capacity `_fetchPlanningData` hatayi yutup success toast gosteriyordu; `_lastFetchOk` bayragi eklendi. Kural: toast'tan once sonuc bayragini kontrol et.
- Capacity model sabitleri: `_MSP_TR/US_COMPANY_ID`, `_MSP_FLOAT_EPS=1e-9` (ceil oncesi float gurultusu +1'i onler; tam sayilar degismez).
- `controllers/main.py` bare except -> `(TypeError, ValueError)`; `need` dalinda bozuk giriste `val=0` (xlsxwriter cokuyordu); `json.loads` korumasizdi (2 controller).
- SCSS olu temizlik: procurement agaci capacity siniflarini kullaniyor, kopya stiller silindi; `.msp-add-col-input` + mobil `.msp-control-bar` blogunun ebeveyni yoktu.
- Canli MCP bagli ama `matia.procurement.*` model yok (Fault 2) -> canli alan dogrulamasi upgrade sonrasina bloklu.
- DokunulMAyanlar: capacity menu `group_user` (export kilidi bozardi); location/env tekrari (farkli include mantigi); unlink iz-silme; RPC grup kontrolu; `mrp.bom.search` N+1'leri.

## Capacity Turu (2026-10-06)

- Negatif quant 3752 (once 3745); NCR icinde negatif 0 -> tamami plana giren lokasyonlarda. NCR TR 333 + US 332 aktif ve kural gecerli; NCR'lar haric tutulmaya devam (kullanici karari).
- `has_bom` satir-basi `bom_ids` erisimi N+1'di; tek `search_read` ile toplulastirildi (iki metot). Kural: `active_test=False` env + ek domainsiz batch, anlambilim birebir.
- Expand-all cift tiklamada yinelenen RPC zinciri kuruyordu; `_expanding` kilidi + butonda `(X/Y)` ilerleme + hata guvenlik agi eklendi.

## Performans Paketi (2026-10-06)

- `get_tree_with_cost` satirlar hedeflerle uyumluysa yeniden kurulumu atlar (`built_target_json` alani). Kural: ongorulebilir RPC metodlarinda girdi-hash'i sakla, ayni girdiyle gelen cagrida salt-okunur sun.
- `_mpp_write_if_changed`: ayni degerleri `write` etme (UPDATE + computed zinciri yok). Many2one karsilastirmasi id ile.
- `items = []` gibi yaygin anchor'larla edit yapma: yanlis blogu tuttu, IndentationError verdi, py_compile ile yakalandi. Kural: edit oncesi hedef blogun ustundeki benzersiz 3-5 satiri anchor'a dahil et.
- `mrp.bom.search` N+1'leri (agac + sub-bom `has_bom`) tek `in` sorgusuna indi.

