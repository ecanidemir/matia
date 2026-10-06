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

## Tree+Cost Crash: `_last_buy_vals` order_id Tip Uyumsuzlugu (2026-10-06)

- Hata: `get_tree_with_cost -> action_assign_suppliers -> _last_buy_vals` zincirinde `TypeError: 'int' object is not subscriptable` (`lb['order_id'][0]`).
- Kok neden: batch refactor sonrasi `_mpp_last_buys` `order_id`'yi int (`_oid or False`) donerken, tuketici `_last_buy_vals` hala `search_read` seklini (`[id, name]`, `[0]` ile okuma) varsayiyordu. Diger many2one'lar (`partner_id`, `currency_id`, `product_uom`) hala `[id,name]` oldugu icin sadece `order_id` patladi.
- Cozum: `_last_buy_vals` once `lb.get('buy_dt')` kullanir, yoksa `order_id`'yi normalize eder (list/tuple -> `[0]`, int -> aynen) ve `order_dates` (int key) map'inden okur; en son `date_planned` fallback. Ham `search_read` dict'i de kabul edilir.
- Kural: batch'e cevrilmis helper'in dondurdugu dict seklini degistirince tum tuketicileri guncelle; `search_read` `[id,name]` vs normalize edilmis int ayrimi her okumada gozetilmeli.
- Deploy: Python degisikligi staging'de Git Deploy + Upgrade/restart gerektirir (mesai disi + backup); `button_immediate_upgrade` yetmez.

## Production Plan Tab 1 Entry Gruplama (2026-10-06)

- Tab 1 "Enter quantities" artik capacity plan ile ayni grup rozetiyle gruplaniyor: Base, Outdoor Parts, Seat Parts, Common Screws (`procurement_plan.js::_entryGroupOrder/_entryGroupHtml/_renderEntry`).
- Grup rozeti CSS'i (`stock_planning.scss` `tr.group-row` + `.group-title-badge`) sadece `table.msp-table.msp-table-card` icinde gecerli; Tab 1 tablo ayni wrapper'a alindi.
- Kit ve On-Hand Base sutunlari kaldirildi (5 sutun: Code/Product/TR Avail./USA Stock/Qty; `colspan=5` tutarli).
- Grup basi auto-fill: her grup basliginda `Auto-fill <Title> to [N] [Apply]` (fa-magic); `fillN={base,outdoor,seat,screws}` (default 50); `qty=max(0,ceil(N-fill_base))`.
- Toggle class ayrimi kritik: entry butonu `mpp-btn-entry-toggle` (gorsel icin `msp-btn-group-show/hide` yeniden kullanilir) — tree tab'daki `msp-btn-toggle-group` secicisiyle cakismamali, yoksa iki tab birbirini acar/kapatir.
- `kit_key` kaynagi: `get_entry_products` her item'a `kit_key` ekler (`base|outdoor|seat|screws`); bilinmeyen key trailing grup, bossa `(0 Parts)` — cokus yok.
- Plan: `plans/production_plan_entry_groups.md`. Sadece static (JS/XML/SCSS) degisti → deploy icin modul Upgrade yeterli, servis restart gerekmez.

## Capacity Alt-Parca Bagimli Talep Duzeltmesi (2026-10-06)

- Hata: capacity sayfasinda alt-parca ihtiyac sutunlari hep brut `hedef*bom_qty-avail` ile hesaplaniyordu; ornek E2CPAN01 ihtiyaci 5 iken cocugu M3U2PB01 20, torunu M2U2SN06 18 gosteriyordu (dogru: 5 ve 3).
- Kok neden: `get_sub_bom_details` parent net eksigini hic kullanmiyordu; `parent_bom_qty` sadece gorunen kullanim miktarini olceklendiriyordu.
- Cozum: metoda `parent_req_20` + `parent_dynamic_needs` {hedef: net} eklendi; cocuk ihtiyac `parent_need*sub_qty_per_parent - max(0,avail)` (bagimli talep), `None` gelirse legacy brut formulu. JS parent netini `data-req-20`/`data-dyn-needs` (`widget._dynNeedsKey`, `t:v;t:v` format) ile RPC'ye tasir; cache key 4 parcali (urun|qty|req20|dyn), export recursion ayni key ile arar. `max_devices` degismedi (brut kapasite gostergesi).
- Kural: parent OK (0) + cocukta asiri rezerve (avail<0) birlesiminde avail 0'a kirpilir, yoksa sahte NEED cikar. Deploy: Python+JS+XML degisikligi Git Deploy/restart gerektirir (mesai disi + backup); sonrasi tam sayfa reload sart (stale DOM'da attr yok).

## Production Plan Capacity Template (2026-10-06)

- Sorun: procurement JS `msp-*` siniflari uretiyordu ama stiller `stock_planning.scss`'te yalniz `.o_matia_stock_planning` altina scoped idi; procurement koku `.o_matia_procurement_plan` oldugu icin stiller dusuyordu (ham bootstrap gorunum).
- Cozum: kok selector `.o_matia_stock_planning, .o_matia_procurement_plan` oldu; capacity XML deseni (ikonlu header, table-card+search+legend, KPI accent) procurement XML/JS'e tasindi (Tab 1 4 sutun, Tab 2 thead 15 sutun korundu, Tab 3 sirket grup satirli `msp-table`). Detay: `plans/production_plan_capacity_template.md`.
- Kural: shared `msp-*` sinifi ureten her yeni ekran kokunu bu scope'a ekle; scoped SCSS'ta sinif yeniden kullanmadan once kok eslesmesini kontrol et. Static-only degisiklik Upgrade ile yeter, restart gerekmez.

## Bottom-up Producible (2026-10-06, production plan)

- `Producible` artik bottom-up: `pool(X)=own+min_C floor(pay(C->X)/kullanim)`, paylasilan cocuk NET-talep agirlikli bolunur (`pay(C->P)=pool(C)*katki[P->C]/girdi(C)`). Satinalma (planned/net/cascade) aynen durur, sadece goruntu kolonu.
- Saklama: `matia.procurement.plan.producible_json` (`{"pool":{},"branch":{"P>C":int}}`), explode'da yazilir; onbellekli gorunum + sub-BOM buradan okur, eski plansiz cagrilar legacy formüle duser. Phantom own=0.
- Dogrulama: staging canli verisi E2CBAN02 hedef 50 -> net 47, dallar [10,2,43,283,248,24], pool 5 (kullanicinin el hesabi birebir). Paylasim sizinti testi OK (`scratch/verify_pool.py`).
- 2026-10-06 ek (paylasim notu): E2CBAN02 ornegi paylasimi kanitladi — planda ~65 hedef varken Cable 4 BOM'da, Shrink 9 BOM'da kullanildigi icin dallar kirpildi (Cable 10->1, Shrink 283->23); sadece bu BOM'daki Connector/Faston tam pay aldi. `producible_json` artik `share`+`driver` de tutar; `share_n>1` hucrede kehribar rakam + `⇄ % · N parents` notu (JS `_sharedNote`, SCSS `.msp-shared-note`).
- Plan: `plans/producible_bottomup.md`. Deploy: Python degisikligi Git Deploy + Upgrade/restart (mesai disi + backup).

## Expand All + Cross-BOM Search (2026-10-06, production plan Tab 2)

- Expand All yalniz seviye-1 aciyordu (recursive degildi); ayrica tek RPC hatasi chain'i reject edip render'i hic calistirmadigi icin buton "olu" gorunuyordu. Simdi BFS ile tum orman acilir (cycle/depth<=10/node<=2000 guard); basarisiz dal uyarir ama kalan acilir + render calisir.
- Arama kutusu sadece yuklenmis (acik) satirlari filtreliyordu; kapali subtree gorunmezdi. 2+ harfte `search_tree(plan_id, q)` tum ormani server-side gezer (get_sub_bom_cost ile ayni BOM cozumu, depth<=10, cap 100) ve her eslesmeyi parent trail ile dondurur (`trail` TOP-ilk, `path_ids` genisletme icin, `group_key/top_*`). Ornek: E1CBRN06 -> 4 sonuc, her biri ust kod zinciriyle. `Show` filtreyi temizler, yolu top-down acar (net'ler taze parent satirlardan, sayilar exact), satira scroll + sari flash (`.msp-flash`).
- Kural: paylasilan alt agaclar her ust icin AYRI gezilir (dedupe yok) - ayni parca N BOM'daysa N sonuc doner. Deploy: Python var -> Git Deploy + Upgrade/restart (mesai disi + backup).

## Table-Filter Search + Expand All Rewrite (2026-10-06, production plan Tab 2)

- Kullanici karari: arama ayri panel degil TABLONUN kendisinde filtre olacak (acilmamis subtree dahil); Expand All en alt seviyeye kadar acacak.
- Arama artik tablo-ici filtre: 2+ harfte `search_tree` sonuclari `_expandSearchPaths` ile acilir (ortak prefix cache'ten, sira sira RPC, reject yok) ve `_renderFilter` flat tablo cizer (grup + kod sirali, satirda konum trail'i, 15 kolon ve sayilar cache'ten exact). Eslesmeye tiklama `_onMatchJump` ile agaca ziplar (filtre temizlenir, `_expandPath(group, ids, true)`, scroll + `.msp-flash`). Eski panel kaldirildi (`mpp-search-results` div + SCSS blogu + `_renderSearchResults`/`_onSearchGoto`/`mpp-search-goto`).
- Expand All pump rewrite: her adim `.then` icinde kosar (stack-unwind, buyuk agac guvenli), butonda canli `Expanding x/y`, her 10 dugumde ara render, bos kuyrukta `Nothing to expand` uyarisi, calisirken `_expanding` kilidi (Collapse All bekle der), gizli gruplar acilir. `_expandPath` jump + filtre tarafindan ortak kullanilir.
- Teshis notu: staging'de `search_tree` CANLI cikti (`scratch/check_search_tree.py`: 'cab' -> 62 sonuc); sikayet eski koddan degil, render-sizlik + senkron ozyineleme riskiydi.
- Deploy: static-only (JS/XML/SCSS, Python YOK) -> modul Upgrade yeterli, restart gerekmez; sonrasi Ctrl+F5.

## Expand All Hizlandirma (2026-10-06, paralel pump)

- Sikayet: Expand All calisiyor ama cok uzun suruyor. Kok neden: pump kuyruktan TEK dugum cekip RPC yanitini sira sira bekliyordu; acilmamis her alt-BOM = 1 gidis-gelis suresi, art arda. Ayrica `seen` tam-yol uid ile tutuldugu icin paylasilan parca her ebeveyn altinda AYRI RPC yiyor (carpan etkisi).
- Cozum (static-only): en fazla 6 paralel fetch (CONC havuzu), cached dugumler senkron katlanir, ara full-render her 10 yerine her 50 dugumde (buyuyen tabloda render O(n^2) yapiyordu; buton etiketi her dugumde guncellenir). `finish()` tek-seferlik (`_expanding` guard + cap-bitince kuyruk birakma ele alindi). `_expandPath` (arama filtresi) derinlik<=10 oldugu icin sira sira birakildi.
- Kural: toplu agac acma islerinde RPC'yi sira sira zincirleme; CONC=6 havuz + seyrek ara render kullan. Deploy: static-only -> Upgrade yeterli, restart gerekmez; sonrasi Ctrl+F5.

## Expand All Capacity Desenine Gecis (2026-10-06, production plan Tab 2)

- Kullanici geri bildirimi: paralel pump da iyi calismadi, capacity sayfasindaki expand iyi calisiyor. Kok fark: capacity `_onExpandAllBoms` seviyede-seviye gecer - her turda DOM'daki tum gorunur kapali butonlar AYNI ANDA ateslenir (Promise.all), render edilir, sonraki tur yeni gorunen butonlari toplar; durum DOM + expanded bayraginda, elle kuyruk/uid muhasebesi YOK.
- Production `_onExpandAll` ayni desene cevrilidi: tur-basi `expandOneLevel(pass)` (`.msp-btn-sub-bom:visible` tara, acilmamis + olu-degil + level<10 olanlari topla, cache'tekini RPC'siz ac, Promise.all ile atesle, sayiyi don), `runPass` aclan yoksa bitirir (sonraki turlar da bos olurdu), basarisiz dal `dead[]`'e alinir (sonraki turlarda tekrar denenmez), baslangicta arama filtresi temizlenir + gruplar acilir + bir kez render edilir (1. tur gercek DOM'u tarar).
- Kural: agac-acma islerinde kaynagi DOM taramasi yap, uid kuyrugu elle tutma. Deploy: static-only -> Upgrade yeterli, restart gerekmez; sonrasi Ctrl+F5.

## Tree+Cost Sadelestirme + Seller/UoM Duzeltmesi (2026-10-06, production plan Tab 2)

- Kullanici karari: On Hand + Reserved sutunlari kaldirildi, sadece Unreserved gosterilir (netting zaten `avail=max(0,onhand-reserved)`, NCR haric). Net/Order sutunu kaldirildi (Usage+Unreserved+Producible+Planned yeterli). Tablo 15->12 sutun (`colspan=12` 2 yerde guncellendi); sort key'leri `onhand/reserved` silindi; `_onhand` helper olu kod olarak kaldirildi. Excel tree export ayni 4 sutunu birakti (CSV format 20->16 `%s`, xlsx 18->14 kolon: 0 code,1 name,2 usage,3 avail,4 producible,5 planned,6 seller,7 source,8 last,9 usd,10 date,11 rolled,12 est,13 breakdown).
- Turkce UoM (`Adet` DB dilinde sakli) Tree+Cost'ta ham gorunuyordu; capacity'deki `_UOM_NAME_MAP` procurement'a tasindi: server `_MPP_UOM_NAME_MAP` + `_mpp_uom_en()` (tree top/sub/summary/production 4 nokta) + JS `_uomEn()` fallback (cached/legacy satirlar). Degisen 4 dosya case-sensitive TR-karakter taramasinda temiz (`Select-String -CaseSensitive`; NOT: case-insensitive tarama Turkce `i/I` folding yuzunden her satiri eslestirir, her zaman `-CaseSensitive` kullan).
- Seller'da Matia TR/US cikiyordu (sirketlerarasi PO'lar vendor olarak kendi sirketimizi gosterir). Cozum: `_mpp_own_partner_ids()` (tum `res.company` partner_id'leri) `_mpp_last_buys` PO satirlarini + pricelist `seller_map`'i filtreler; `action_assign_suppliers`'da ek safety-net (filtre disi sizma pricelist'e duser). Kural: kendi sirketimiz asla seller olamaz; son-alim yoksa "No supplier".
- Deploy: Python var -> Git Deploy + Upgrade/restart (mesai disi + backup); `py_compile` + `node --check` OK. Capacity sayfasina DOKUNULMADI (reserved-pill/td-reserved SCSS+XML orada durur).

## Largest-Remainder Havuz Dagitimi + Tooltip (2026-10-06, production Producible)

- Kullanici bulgusu: E1CBRN06 4 BOM'da, havuz 5000mm; dagitim 500x1 + 810x2 + 590x2 + 400x2 = 4100, 900mm sahipsiz kaldi. Kullanici el hesabi: 500x2 + 810x2 + 590x2 + 400x3 = 5000 (sifir kalan).
- Dogrulama (staging MPP-0003, salt-okunur `scratch/verify_cable_pool.py`): paylar 830/1365/1990/810 -> kotalar 1.66/2.31/2.45/2.02 -> floor dallari (1,2,2,2). Aritmetik hata YOK; sorun politika: her dal bagimsiz asagi yuvarlaniyor, kalan kimseye verilmiyordu.
- Cozum: largest-remainder dagitimi (display-only, satinalma aynen). Her cocuk icin taban floor dallarindan sonra kalan, en yuksek kesirli kota + sigan kullanim sirasina +1 dagitilir; dal ceil(kota)'yi gecemez (kimse adil payindan fazlasini almaz). Cocuklar ters-topo sirada birer kez islenir, sonra ebeveyn havuzlari tazelenir. Sonuc E1CBRN06: (2,2,2,3) = 5000, kalan 0 (kullanici hesabi birebir; `scratch/test_remainder.py` 6/6 PASS).
- Tooltip: `producible_json` artik `alloc_note` tutar ("E1CBRN06 pool 5000 mm: E2CBAN02 500x2 + ... = 5000, leftover 0 mm"); satirlara `share_note` olarak tasinir, JS `_sharedNote` title yapar (eski metin fallback). Ingilizce + ASCII zorunlu, cift tirnak sanitize.
- Kural: paylasimli havuz dagitiminde bagimsiz floor birakma; largest-remainder + ceil cap kullan. Deploy: Python var -> Git Deploy + Upgrade/restart (mesai disi + backup); MEVCUT planlar Calculate ile yeniden kurulmadan yeni dal/not gorunmez. Once staging'de dogrula.

## Tree+Cost UoM Rollup Hatası (2026-10-06, RAL6K125 x M3MTMN05)

- `last_price` / `last_price_usd` snapshot'ı PO satırının ham biriminden gelir (UoM çevrimsiz); `unit_price` ise satır UoM'una çevrilir. `_compute_rollup` `_own_usd/_own_try` olarak çevrimsiz snapshot'ı kullanıp BOM edge qty ile çarpar.
- Örnek: RAL6K125 son alım 147.96 TRY/**m** (PO/24-00264, date_order 15 Feb 2024) -> 4.82 USD/**m**; BOM'da 282 **mm** kullanılıyor. Ekranda 4.82 x 282 = 1359.24 USD (1000x şişik); doğrusu 4.82/1000 x 282 = ~1.36 USD. Ebeveyn M3MTMN05 (subcontract, 200 TRY/Units -> 6.52 USD) rolled = 6.52 + 1359.24 = 1365.76; doğrusu ~7.88 USD.
- Kural: rolled maliyette UoM uyumsuz ürün (satınalma UoM != BOM/stok UoM) varsa ekrandaki birim fiyatı PO UoM'una aittir, qty ile doğrudan çarpılamaz. Fix: rollup'ta `last_price_usd`'yi satır UoM'una normalize et (ya da `unit_price` USD karşılığını kullan).

## Production Plan Cift Kod Hatasi (2026-10-06, T2STNN03)

- Sikayet: Part Name `[T2STNN03] [T2STNN03] Foot Stabilizing Strap`, dogrusu `[T2STNN03] Foot Stabilizing Strap`.
- Kok neden: `product.product` temizdi (name=`Foot Stabilizing Strap`, display=`[T2STNN03] Foot...`); procurement server `code` ayri + `name`=display_name gonderiyor, JS `[code]` + `name` birlestirince one ek iki kez geldi (Tab1 entry, Tab2 tree, uretim sekmesi, export).
- Cozum: server `name` artik `product.name` (plain); JS `_plainName(code,name)` bastaki `[CODE]` one ekini soyuyor (eski cache guvencesi). Capacity etkilenmedi (zaten `p.name` kullaniyor).
- Kural: kodu ayri gosteren her satirda `name` plain olmali; `display_name` yalniz tek-hucrelik alanlarda kullanilir. Deploy: Python var -> Git Deploy + Upgrade/restart (mesai disi + backup).

## Production Plan Tek Sayfa (2026-10-06, implemented - live dogrulama bekliyor)

- Enter Quantities kaldirildi; tek "Plan" tab'i (baslik "Production Plan"): 14 sutun Part | Usage | TR | US | Producible | Needed | Planned | ... TR/US = unreserved (on-hand - reserved, NCR haric), netting + producible havuzlari TR+US toplami (`_mpp_stock_split`: sirket basina tek read_group). PO/MO domainleri [TR,US]. USA tedarikci ayrimi aynen.
- Needed kalici: `set_targets_and_rebuild` target_json'a yazar; acilis `get_startup_tree()` son plani yukler (yoksa bos draft). Grup basligi N fill: `need=max(0,ceil(N-avail_toplam))`. Alt satirlarda Needed = bagimli brut ihtiyac (salt-okunur). `_MPP_KIT_BOMS` sira base/outdoor/seat/screws (Screws en altta).
- Deploy: Python var -> Git Deploy + Upgrade/restart (mesai disi + backup); MEVCUT planlar Recalculate edilmeden yeni gorunumu gostermez.

## Exact-Enumeration Havuz Dagitimi (2026-10-06, production Producible)

- Largest-remainder'in yerini `_mpp_allocate_exact` aldi (`models/matia_procurement_plan.py`, `_mpp_load_pools` oncesi 3 helper: score/fallback/exact). Cap `ceil(ideal)+slack` icindeki TUM sayim vektorleri numaralandirilir; once en az kalan (waste) kazanir, beraberlikte gorece kare sapma (penalty), sonra ID-sirali ilk numaralama (deterministik). `waste_band=0` default: kalan her zaman once minimize edilir (band=200 canli E1CBRN06'da (1,3,2,2)+90 waste verip kullanici el hesabiyla celistigi icin 0'a cekildi).
- Cap'ler fiziksel max ile kirpilir (`total//size`); kombinasyon x ebeveyn > 2M ise `_mpp_allocate_fallback` (eski largest-remainder, ayni sonuc sekli). Slack kullanimi `over_cap` listesinde raporlenir, tooltip'e `; X over fair share to close waste` eklenir (Ingilizce + ASCII). Cagri blogu `_alloc[_cc]={'pool','used','parts','over_cap'}` sozlesmesini + ebeveyn havuz tazeleme satirlarini korur.
- Canli E1CBRN06: (2,2,2,3) = 5000, kalan 0, over_cap bos. Test: `scratch/test_remainder.py` shipped fonksiyonlari kaynak dilimleyip exec eder (drift yok, Odoo importsuz), 15/15 PASS (canli kablo, slack over-cap, tie determinizm + sira-kararlilik, negatif/bos/sifir-size guard, out-of-band min-waste, fallback parity, sonuc-sekli sozlesmesi).
- Kural: dagitim politikasi degisince once `waste_band` default'unu canli ornekle caprazla; band genisletmek kalan birakir. Deploy: Python var -> Git Deploy + Upgrade/restart (mesai disi + backup); MEVCUT planlar Recalculate edilmeden yeni dali gostermez. Once staging'de dogrula.

## Production Plan Kompakt Tablo + _t Cakismasi (2026-10-06)

- `_t('Apply')` Odoo core TR cevirisine takilip butonda "Uygula" cikiyordu; grup basligi sabit `'Apply'` yazildi. Kural: kisa/jenerik kelimelerde (`Apply`, `Show`, `Save`) `_t()` kullanma — core ceviriyle carpisir; Show/Hide zaten plain string oldugu icin Ingilizce kalmisti.
- Producible paylasim notu kisa: `35.9% of pool · 4 parents` yerine sadece `4 parents` (dagitim detayi tooltip'te). Planned hucresindeki `top_breakdown` alti-notu onceki turda kaldirilmisti.
- Tab 1 kompakt (sadece procurement SCSS, Capacity'ye dokunulmaz): th/td yatay padding `0.85->0.5rem`, Needed input `110->84px`, Seller `max-width:150px` + ellipsis (+title tooltip), Usage `282.00->282` (fmt decimalsiz), UoM notu `/m` inline (satir tek satir). Deploy: static-only -> Upgrade yeterli, restart gerekmez; sonrasi Ctrl+F5.

## Production "N parents" Notu Okuma (2026-10-06, staging MPP-0004 ornegi)

- Level-0 satirdaki `N parents` o urunun KENDI kullanim yeri sayisi DEGIL; onu sinirlayan darbogaz cocugun (driver) plan-ici net talepli ust sayisidir (`share_map[(pid, driver)]`, kod `matia_procurement_plan.py:1859`).
- Ornek: E2MBAN03 satirindaki `4 parents` = driver N1TRRN02 Plastic Cable Tie - Short'un (havuz 0!) 4 ustu: E2ONAN02 (%38.5), E2MBAN03 (%35.9), E2UCAN02 (%12.8), E2SWAN02 (%12.8). N2TLAN01 edge'i var ama net katkisi %0 oldugu icin sayilmaz.
- Kuresel kullanim ayridir: E2MBAN03 `mrp.bom.line`'da 3 BOM'da gecer (TEKRMD04/BOM 1718, Common Parts/BOM 1735 phantom, Common Parts v2/BOM 1766); plan notu ile kiyaslanamaz.

## Production "N parents" Kurali v2 (2026-10-06, kullanici karari)

- Not artik satirin KENDI urununun plan-ici paylasimini gosterir (dar-bogaz cocugun paylasimi ust satira yansimaz). E2MBAN03 gibi kimseye paylasilmayan urunde not + tooltip YOK.
- Tooltip kisa: `Also used in: KOD xADET, ...` (ust kodu + BOM kullanim miktari, dagitim/havuz rakami yok, max 10 + `+N more`). Ureten: `_mpp_par_notes` (`matia_procurement_plan.py`), JSON'da `par_n` + `par_note` (`alloc_note` kaldirildi).
- Test: `scratch/test_par_notes.py` 6/6 PASS (E2MBAN03 sessizligi, kablo-ornegi, kod fallback, tirnak sanitize, cap, ASCII).
- Deploy: Python var -> Git Deploy + Upgrade/restart (mesai disi + backup); MEVCUT planlar Recalculate edilmeden yeni not gorunmez. JS degismedi.

## Capacity vs Production Birlestirme (2026-10-06)

- Clamp politikasi tek: `_msp_clamped_avail` (stock_planning.py) sirket-bazinda `max(0,·)` kirpar, MPP `_mpp_stock_split` tuketicileriyle ayni. Negatif quant'li sirket digerini yemez, need sismez. Capacity artik TR/US ayri read_group yapar (2+2 sorgu).
- Sub-BOM aramada variant-oncelikli deterministik sira (variant -> generic template -> template fallback); tek OR-sorgu birakildi.
- Level-0 UoM kaynagi BOM satiri (`bl.product_uom_id`), urun karti degil. UoM map'lerde `Takim` ASCII + `Takım` TR anahtarlari ikisi de var (py + JS fallback).
- Prod tree export: 16 baslik (Part Code/Name ayri) = 16 sutun; CSV dali `';'.join` listesiyle yazildi (eski `%`-formati 18 placeholder/17 degerle patliyordu).
- Kural kararlari: Usage Prod'da ham satir miktari, baslik `Per-Parent Qty` (Capacity olceklenmis efektif gosterir); expand-all iki sayfada da filtreyi temizleyip tam acar; export ekrani yansitir (gizli grup haric + arama filtresi; Cap'te `_exportNameMatch`, Prod'da `_subtreeMatch` + collapsed skip); Cap arama sadece yuklu satirlarda (placeholder title'da yazar); Prod TR/US kesirli stok gosterir (dec yok).
- Deploy: Python var -> Git Deploy + Upgrade/restart (mesai disi + backup); static-only degisiklik Upgrade yeterli, sonrasi Ctrl+F5.

## Production Auto-Fill Lineless-Top Bug (2026-10-06, staging MPP-0004)

- Sikayet: Screws grubuna 60 + Apply sonrasi stok fazlasi 2 civatada (N1FTAG65 avail 250, N1FTRS12 avail 90) Needed 60, digerlerinde 0. Formül dogru (`need=max(0,N-avail)`), girdi yanlis.
- Kok neden: `_onNeedFill` (procurement_plan.js:225) avail'i client cache `treeGroups`'tan okur; plan satiri OLMAYAN top'ta server `avail_tr/avail_us/avail_total=0` gonderir (`get_tree_with_cost`, `line=None` dali). Satirsiz = onceki hedef + bagimli tuketim (Base patlamasi) YOK demek. 1881/1824'te gross == hedef == 60 (saf targets, bagimli sifir); 1887'de gross 2340/net 681 (bagimli vardi, satir vardi, avail 759 biliniyordu -> need 0 dogru).
- Etki SINIRLI (kritik degil): rebuild `planned=max(0,need-gercek_avail)` ile gercek stoktan netler -> 1881/1824 net 0, order 0 (canli dogrulandi). Yanlis Needed sadece hedef siskinligi + kafa karisikligi; satinalma tetiklemez.
- Fix yonu: `get_tree_with_cost`'ta satirsiz top'a canli `_mpp_stock_split` stokunu koy (0 yerine) veya auto-fill'i server-side RPC yap (`auto_fill_group`: gercek avail ile hesapla + yaz + rebuild). Gecici cozum: satirlar olustuktan SONRA Apply'a tekrar bas (artik avail biliniyor -> 60'lar 0'lanir; gercek acik 2418 gibi avail 0 olanlarda 60 kalir, dogru).
- Deploy: Python var -> Git Deploy + Upgrade/restart (mesai disi + backup).

## Production Tab 2 Expandable Suppliers (2026-10-06)

- Istek: Tab 2 Supplier listesinde tedarikci isimleri acilabilir olacak, altinda hangi parcalarin alindigi gorunecek.
- Server: `get_supplier_summary` her tedarikciye code-sirali `lines` ekler (code/name/order_qty/uom/route/last_price/last_currency/last_usd/last_date/rolled_usd/total_usd); toplamlar degismedi.
- Client: `_supKey` (seller:company), `_onSupToggle` (caret + isim tiklamasi), `_supplierLinesHtml` (acik satir altinda mavi alt-satirlar: kod/ad, order+UoM, route rozeti, rolled x qty = total + last-price notu); durum `expandedSup` map'inde, plan degisince sifirlanir. TR-karakter 0 (yeni kod), py_compile + node --check OK.
- Deploy: Python var -> Git Deploy + Upgrade/restart (mesai disi + backup); sonrasi Ctrl+F5.

## Production Sifir-Siparis Seller Boslugu (2026-10-06, M1WHRN02)

- Sikayet: M1WHRN02 (Back Wheel - Indoor, product 1331) son alimi Rolko North America'dan 27.95 USD (PO/24-00324, staging PO 334, 210 adet) olmasina ragmen agacta tedarikci bos, fiyat gorunuyordu.
- Kok neden: `action_assign_suppliers` (`matia_procurement_plan.py`) `order_qty==0` olan buy/subcontract satirlarinda sadece fiyat snapshot yazip seller atamadan `continue` ediyordu. MPP-0004'te M1WHRN02 gross 11, stok karsiliyor -> net 0, order 0, seller False, last_price 27.95 USD. Agac + sub-BOM seller'i `line.seller_id`'den okudugu icin fiyat gorunup tedarikci bos kaliyordu. Urun route'u Buy, 2 supplierinfo (ROLKO KOHLGRUBER 9.5 EUR sirket-bagimsiz + ROLKO North America 27.95 USD US), kendi sirket partner filtreleri temizdi.
- Fix: sifir-siparisli buy/subcontract satirlari da seller mantigindan gecer (`seller_id` + `unit_price` yazilir, bilgi amacli); min-qty uyarisi `order_qty>0` sarti aldi (siparis yoksa uyari yok); subtotal zaten `price x 0 = 0`. Guvenli: RFQ gruplama (`order_qty>0 and seller_id`) + supplier ozeti (`buy and order_qty>0`) filtreli oldugu icin hayalet RFQ uremez.
- Kural: agacta gorunen seller her zaman `line.seller_id`'dir; bilgi-amacli seller yazmak RFQ uretmez cunku RFQ yolu order filtresinden gecer. Deploy: Python var -> Git Deploy + Upgrade/restart (mesai disi + backup); MEVCUT planlar Calculate/supplier-preview tekrar calismadan seller'i gostermez.

## Production Auto-Fill Gross-Want Duzeltmesi (2026-10-06, cift-netting + paylasimli parca)

- Onceki bulgu (yukaridaki Lineless-Top) semptomdu; derindeki hata: auto-fill `need=N-avail` yaziyor, rebuild cascade'i (`net=demand-avail`, `matia_procurement_plan.py:820`) stoktan BIR KEZ DAHA dusuyordu. `0<avail<N` olan HER satir avail kadar EKSIK siparis uretiyordu (simulasyon `scratch/test_autofill_gross.py`: avail 10/N 60 -> net 40, dogrusu 50; paylasimli ornekte 240 vs 250; avail 250 + dep 200 durumunda 0 vs dogrusu 10 - siparis tamamen yok oluyordu).
- Cozum (brut-anlam): `_onNeedFill` artik `needMap=N` yazar (stok okumaz -> lineless bayat-avail sinifi kapandi); stok dusumu tek elde (server cascade). Satirsiz top'lar `get_tree_with_cost`'ta canli `_mpp_stock_split` stokunu gosterir (tek bulk okuma, eskiden 0/0). Tooltip + Needed/Planned basliklari guncellendi: Needed = brut istek, Planned = havuzlanmis net (paylasimli tuketim dahil).
- Paylasimli parca sorusunun cevabi: Needed artik "net acik" iddiasinda degil, o yuzden yaniltmaz; siparis karari Planned'dan okunur (brut istek + diger ebeveynlerin net tuketimi - stok). `Also used in` notu paylasimi gosterir (v2 kurali).
- Yukaridaki "Tek Sayfa" girdisindeki `need=max(0,ceil(N-avail))` formulunu GECERSIZ kilar (tarihsel kayit olarak durur).
- Test: `py_compile` + `node --check` OK; simulasyon 5/5 NEW-dogru. Deploy: Python var -> Git Deploy + Upgrade/restart (mesai disi + backup); JS icin sonrasi Ctrl+F5. Plan: `plans/production_autofill_gross_fill.md`.

## Production Tab 2 Toplam Duzeltmesi (2026-10-06, sellerless + cift-sayim)

- Sikayet: 2. Suppliers & Production sayfasindaki toplam rolled USD dogru mu; tedarikci grubuna giremedigi icin hesaba katilmayan ama siparis edilecek parca var mi; fiyati/tedarikcisi belli olmayanlar gosterilmeli.
- Staging MPP id 24 canli dogrulama (salt-okunur): 4 ayri bosluk kanitlandi:
  1. `get_supplier_summary` filtresi `buy/subcontract + order>0 + seller` idi: sellerless buy (ornek 2418 Brake Cable, order 60, rolled 0) NE supplier NE production listesindeydi -> toplamda yok, ekranda yok.
  2. `unknown` route'lu satirlar (route atanmamis urunler) iki listede de yoktu: ornek 1271 Wheel Nut Tool (order 31, rolled 35.23 -> ~1092 USD kayip), 1190 Front Cover Set (order 50, rolled 19226 -> tek basina ~961k USD kayip).
  3. Fiyati sifir ama seller'li satirlar (ornek T1CBRN01 kablo order 13000, rolled 0; N1LBRN15 etiket order 34, rolled 0) 0 USD ile toplama giriyor, "ucretsiz"den ayirt edilemiyordu.
  4. Cift-sayim: toplam `rolled_usd x order` toplaniyordu ama rolled = own + cocuklar. BOM'lu buy ebeveyn + cocuklari AYNI ANDA order>0 olunca (ornek P3CPPG22 boya order 50 rolled 374 + cocugu P3CPIN22 unpaint order 50 rolled 372, BOM 1666 1:1; ornek 1159 strap own 1.57 vs rolled 14.57) toplam ~9-500x sisiyordu. 5 satirlik ornekte eski baz 19309.72, PO-degeri 126.72 (`scratch/test_supplier_totals.py` 7/7 PASS).
- Cozum (`matia_procurement_plan.py::get_supplier_summary` + JS/XML Tab 2): kapsam buy/subcontract/unknown + order>0 (seller sarti YOK) -> sellerless "No supplier" grubu (RFQ butonu gizli, "Assign a seller first"); satir toplami PO-degeri (`last_price_usd x UoM factor x order`, RFQ `_rfq_groups` ile ayni baz); rolled satirda bilgi olarak durur, toplama girmez; `grand_total_usd` (PO) + `grand_rolled_usd` (bilgi) + `unsourced/unpriced_count`; uyar banner + satir rozetleri (No supplier / Unknown route / No price). Make satirlari production'da aynen (maliyet komponentlerde).
- Kural: supplier toplaminda rolled ASLA toplanmaz (ebeveyn+cocuk cift sayar); satin alma tahmini = own x order, rolled = mal degeri bilgisidir. RFQ tutarlariyla caprazla (ayni baz olmali).
- Deploy: Python var -> Git Deploy + Upgrade/restart (mesai disi + backup); MEVCUT planlar Recalculate/supplier-preview tekrar calismadan yeni toplami gostermez; sonrasi Ctrl+F5. Commit/push YOK (kullanici onayi bekleniyor).

## Expand All Bulk Tek-RPC (2026-10-06, production Tab 1)

- Kok neden: her acilmamis node 1 RPC (`get_sub_bom_cost`) yiyordu; her RPC 2 BOM search + tum lokasyon taramasi + 2 read_group + 1 POL search_read + convert'ler + workers=2 kuyrugu + her pass'te full render.
- Cozum: `get_full_tree(plan_id, top_nets, max_depth=10, cap=2000)` — Faz1 yapi yuruyusu (pid-cache BOM), Faz2 toplu yuk (tek stock split / tek last-buy / tek BOM-varlik search), Faz3 top-down insa (net yayilimi: cocuk neti = parent net x kullanim - avail). Satir kurucu `_mpp_sub_items` helper'a cikarildi; `get_sub_bom_cost` ayni helper'i cagirir (drift yok). JS `_onExpandAll` tek RPC + tek render; uid semasi/level/cap/cycle kurallari birebir.
- Kural: agac-acma islerinde N-RPC yerine tek bulk RPC + paylasilan satir-kurucu helper kullan. Deploy: Python var -> Git Deploy + Upgrade/restart (mesai disi + backup); once staging. Plan: `plans/production_expand_all_bulk.md`. Commit/push YOK (kullanici onayi bekleniyor).

## Production Cift-Gosterim Faz-1 (2026-10-06, 54 uret / 51 net alim)

- Ornek: P2CPAS32 (id 1190) Needed 60, TR 0, US 6, producible 9 (6 hazir + 3 monte edilebilir), Planned 54, net alim 51. Planned 54 kalir (uretim gercegi; ayni order_qty hem MO'yu hem RFQ netlemesini besler; 51'e cekmek MO'yu ve cascade'i bozar).
- Kural: Needed = BRUT istek; Planned = brut-uretim rakami (MO + alim netlemesi); acik (net alim) = max(0, need - pool), pool = producible. Maliyet: agac rolled = birim x brut (batik maliyeti yeniden sayar, bilgi); supplier ozeti grand_total = own x order (gercek PO-degeri); operasyon/MO maliyeti planda YOK (Faz-2).
- Client (saf JS, Python yok): `_openQty` (seviye0: need-pool; alt: gross-branch pool), `_openBadge` ("build 54 / buy 51", open<net ise, Planned hucresinde), `_estTitle` (seviye0 Est hucre tooltip: full-deger vs stok-karsilanan), kalici 54/51 aciklama notu Planned baslik tooltip'inde (Needed basligi sadece girdi yeri olarak kisa: ihtiyac adedi buraya yazilir), Rolled/Est baslik netlestirmeleri, Needed input'ta `data-prod` + `_onNeedInput` canli rozet (OK<->sayi gecisi hucreyi yeniden kurar), `_collectExportRows`'ta `open_qty` anahtari (Excel kolonu icin server `_export_tree` degisikligi Faz-2'de).
- Dogrulama: `node --check` OK; `scratch/verify_openqty.js` gercek koddan fonksiyon cekip 15/15 PASS (P2CPAS32 60/9/51, M3 rozetsiz, needMap fallback); odoo-reviewer salt-okunur denetim: kritik yok (XSS yeni risk yok, export fazladan anahtari server yoksayar).
- Deploy: sadece JS -> modulu upgrade + Ctrl+F5 (Git Deploy/restart gerekmez, asset bundle yenilenir). Plan: `plans/dual_qty_cost_display.md`. Commit/push YOK.


## Production Prices Tab (2026-10-06, Tab 3, commit bekliyor)

- Yeni model matia.procurement.price.override (product unique, corrected_price_usd, location tr/us; ACL group_system). Global: tum planlarda gecerli, DB'de kalici.
- Server: get_price_overview (4 kit BFS, depth<=10, variant-BOM oncelikli), save_price_override / ulk_set_location / clear_price_overrides. Override = efektif USD (faktor 1.0): _compute_rollup._own_usd/_own_try, supplier PO-degeri, RFQ fiyat+currency(USD)+company hepsinde last-buy yerine gecer. Location TR->sirket 1, US->sirket 2 (_MPP_OVERRIDE_COMPANY).
- Tree/summary satirlari corrected_usd + eff_usd tasir (Tab 1/2 rozet henuz yok, server alani hazir). Tab 3 client: kolon-basi filtre, tikla-sort, checkbox + Set TR/US + Clear, satir-basi Save.
- Dogrulama: py_compile + node --check + XML parse OK; TR-karakter taramasi temiz (tek eslesme eski UoM map anahtari). Plan: plans/production_price_tab.md. Deploy: Python var -> Git Deploy + Upgrade/restart (mesai disi + backup); sonrasi Ctrl+F5. Commit/push YOK.
- Rota kurali (2026-10-06, guncelleme): Manufacture urunlerde corrected YASAK (server save reddeder, UI input kilitli, _own_usd/_own_try yoksayar); location SERBEST (uretim yeri TR/US raporu icin, bulk dahil). Tek kaynak: _mpp_classify_route (Subcontract>Manufacture>Buy>purchase_ok). Subcontract own = fason hizmet bedeli (duzeltilebilir); rolled = own + cocuklar.

## Production Study Slots 0-9 (2026-10-06, commit bekliyor)

- `matia.procurement.plan.slot` Integer (default -1 = slotsuz legacy; CHECK -1..9, Odoo 15 tuple `_sql_constraints`; DB unique YOK, slot basi en yeni plan gecerli). Metodlar: `get_slot_list` (10 girdi: plan_id/name/state/target_count/rfq_count/write_date, bosta plan_id=False), `load_slot`, `save_slot` (hedef temizligi `set_targets_and_rebuild` ile ayni), `get_startup_tree` artik en son yazilan slot planini acar (yoksa latest legacy'yi slot 0'a baglar, o da yoksa slot 0'da bos plan acar); sonuc `slots` + `active_slot` tasir (`_plan_summary` de `slot` ekler, RFQ override super() ile korunur). JS'te `ensure_one` YOK (RPC bos recordset ile gelir).
- Client: header'da slot bar (select 0-9 + Save + durum rozeti); dropdown degisimi `load_slot` (yazma yok), Save secili slota `save_slot` (baska dolu slot veya RFQ'lu plan uzerine yazarken `Dialog.confirm`). `active_slot` 0 gecerli degerdir, truthiness kontrolu YOK (`hasOwnProperty` + null/undefined/false karsilastirmasi). `set_targets` yaniti slotsuz gelir -> `_applySummary` listeyi korur.
- Kural: slot karsilastirma Excel'i (orn. slot 0 vs 3 tek dosyada) AYRI is; veri modeli hazir (slot + target_json + line snapshot). Deploy: Python var -> Git Deploy + Upgrade/restart (mesai disi + backup); sonrasi Ctrl+F5. Plan: `plans/production_plan_slots.md`. Manifest 15.0.2.1.0. Commit/push YOK.

## Production Prices 964 Dogrulama (2026-10-06, staging)

- `get_price_overview` 964 satir dondu (unique product_id 964, duplicate 0, kod duplicate 0, boskod 0); bagimsiz BFS (4 kit BOM 1766/1737/1738/1736, variant-oncelikli, depth<=10, `scratch/verify_prices_964.py`) ayni 964 kumeyi verdi: disaridan urun 0, eksik 0 (MATCH). Top-level giris 125 tekil urun.
- Not: prod instance'ta `matia.procurement.plan` modeli yok (Fault 2) — dogrulama staging'de yapildi.

## Prices Kit Tipi + TEMP Route Log (2026-10-06, henuz deploy edilmedi)

- Kit = aktif phantom BOM'lu urun (_mpp_kit_tmpl_ids); Prices'ta route 'kit'/'Kit' (rozet badge-info, filtre secenegi), corrected-price make gibi yasak (JS input disabled + save_price_override guard). 4 kit'in kendisi de satir olarak eklendi (once BFS'e girmiyordu). Paylasilan classifier'a dokunulmadi (Tab1/2 etkilenmez). Manifest 15.0.2.2.0.
- TEMP-DEBUG: get_price_overview sonunda _logger.info('MPP-TEMP ...') (uid/plan/histogram/route tablosu/E2CBAN03-M2H1WN05-N2PGAN02-M2WHAN04 izi). Filtre sorunu cozulunce silinecek.
- Arka plan: tarayici Network'te route=unknown + sifir make/subcontract, ayni metoda MCP make donuyor; staging restart cozum olmadi.

## Route Cevirisi Kok Nedeni (2026-10-06, cozuldu, 15.0.2.4.0)

- stock.location.route name'ir.translation ile cevrilir: TR kullanicida 'Uretim'/'Siparis Uzerine Fason Firmaya Tedarik', MCP'de (en) 'Manufacture'/'Resupply Subcontractor...'. _mpp_classify_route Ingilizce substring baktigi icin TR oturumda make/sub hep unknown'a dustu (buy purchase_ok fallback ile kurtuldu).
- Cozum: route name okunan 3 nokta (line build, get_price_overview, _mpp_product_routes) lang='en_US' ile okur. Beklenen dagilim: buy ~571, subcontract ~305, make ~88, kit 5, unknown ~0.
- Kural: cevrilebilir display name uzerinden anahtar eslestirme YASAK; ya kaynak dilde oku ya ID/xmlid karsilastir. TEMP MPP-TEMP log + response debug blogu kaldirildi.
