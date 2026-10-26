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

## M1WHRN07 Cift Kaynak (buy + make) Ornegi (2026-10-06, staging)

- Urun: [M1WHRN07] Outdoor Tail Wheel (product/template 1243, Units, purchase_ok, route Buy+Manufacture). 2 normal BOM (TR 1220, US 1714): M1WHRN08 Rim x1 + M1WHRN09 Rubber x1 + M1WHRN10 Tube x1 (3 cocuk saf Buy, SIFIR satinalma gecmisi).
- Kullanim: TEKRMD04 (BOM 1718) + TekRMD Outdoor Parts (BOM 1737) icinde 2'ser adet.
- Son montajli alim: 23.95 USD, ROLKO North America, PO/24-00324 (Mar 2024). Cocuklarin last-buy'u yok -> pricelist fallback ROLKO KOHLGRUBER (Rim 1098.9 / Rubber 280.92 / Tube 85.38 TRY), last_price 0 (unpriced).
- 15.0.2.4.0 oncesi plan satirlari parent'i 'buy' gosterir (ceviri bug'i mirasi): MPP-0004'te parent gross 46 / avail 4+0 / net-order 42 + seller ROLKO NA + rolled 23.95, cocuklar gross 46 / order 46 -> montajli + komponent CIFTE siparis. Fix sonrasi Recalculate sart: parent 'make' olur (seller/fiyat silinir, rolled = cocuk toplami = su an 0), cocuk talebi parent NET x kullanim olur.
- Kural: hem alinip hem uretilen urunde kod her zaman uretimi secer (BOM varsa patlatilir, Manufacture varsa make); buy-vs-make karari manueldir, Prices'ta montajli son-fiyat sadece bilgi olarak yanina konmali.

## M2C2HN06 Subcontract Gorunumu (2026-10-07, canli veri)

- Urun: [M2C2HN06] Transfer Board Metal 6 Countersink (product/template 2198, Units, purchase_ok=False, sale_ok=False, company global). Template route [Manufacture(6), Resupply Subcontractor on Order(9)] DOGRUDAN template'te (kategori Manufactured routesuz).
- BOM 1226: type normal (uretim), TR sirket, tek satir M3C2LN11 Laser x1. Yani BOM uretim, dogru.
- Prices/Product Cost'ta Subcontract cikma sebebi: `_mpp_classify_route` onceligi Subcontract > Manufacture > Buy; cift rotali urun her zaman subcontract siniflanir.
- Zincir: M3C2LN11 (laser) -> M2C2HN06 (countersink, normal) -> M3C2PB06 (painting, BOM 1341 type subcontract). Route 9 fason akis (boyama) icin bilerek konmus olabilir; T1RURB51/T1CBRN01 ornegiyle ayni sinif (komponent fason BOM'da kullaniliyor).
- COZULDU 2026-10-07 (kod fix, henuz deploy edilmedi): `_mpp_classify_route` artik BOM-tipine bakiyor (asagidaki Route-vs-BOM girdisi). Route 9'a DOKUNULMADI (resupply akisi korunur); M2C2HN06 artik 'make'.

## Route-vs-BOM-Tipi Tersine Siniflandirma (2026-10-07, canli veri, FIX UYGULANDI - deploy bekliyor)

- Olay: M2C2HN06 (countersink, normal BOM 1226) Prices'ta Subcontract; M3C2PB06 (painting, subcontract BOM 1341, fasoncu LEHMANN 1028) Buy gorunuyor. Kullanici hakli: roller ters.
- Olcu: aktif subcontract BOM 353; bunlarin 240 template'inde route 9 YOK (hepsi Buy gorunuyor). Route 9'lu 319 template'in 48'inde normal BOM var (hepsi Subcontract gorunuyor, uretim olmalilar).
- Kok neden: `_mpp_classify_route` SADECE route'a bakar (Subcontract > Manufacture > Buy). Odoo 15 standardinda (`mrp_subcontracting` kurulu) bitmis fason urun rotasi Buy olur, `Resupply Subcontractor on Order` (9) KOMPONENTLERE konur. Yani VERI standarda uygun, kodun bakis acisi yanlis. Data-fix (route ekle/sil) YASAK - Odoo resupply akisini bozar.
- Fix (matia_procurement_plan.py, commit/push YOK): yeni bulk helper `_mpp_subcontract_tmpl_ids` (200-chunk search_read, N+1 yok; bilerek fail-fast - sessiz bos donus yanlis PO uretir, docstring'de yazili); `_mpp_classify_route(route_names, purchase_ok, has_subcontract_bom=False)` oncelik: subcontract BOM > Manufacture > Subcontract-route > Buy (Manufacture bilerek resupply route'unu ezer - testte yakalandi). `_mpp_product_routes` + line-build + price-overview ayni helper'a baglandi; kit kurali degismedi. Test scratch/test_classify_route.py 10/10 + py_compile OK. odoo-reviewer: Odoo 15 API temiz, mantik onayli (2 bulgu duzeltildi: chunk + fail-fast gerekcesi).
- Plan sayfasi etkisi (Recalculate sonrasi; eski planlar eski etiketi tasir): miktarlar (gross/net/order/stok) DEG Tayfa patlatma BOM-tipine bagli, route degil.
  - 48 uretim ara-urunu (orn. M2C2HN06) subcontract->make: artik RFQ/PO URETILMEZ, MO olusturma gelir (normal BOM var); tedarikci ozeti grand_total_usd bunlarin PO degerince DUSER; rolled = cocuk toplami (own 0); varsa manuel duzeltme fiyati make satirinda yok sayilir.
  - 240 fason bitmis urun (orn. M3C2PB06) buy->subcontract: RFQ ayni satici + ayni fiyattan gider (toplamlar DEG Tayfa PO onayi artik standart fason teslim + MO zincirini tetikler (istenen); satir subtotal 0 olur (buy-only), agac Est USD gosterir; uretim sekmesinde yeni subcontract satiri belirir.
- DEPLOY: Git Deploy + servis restart (mesai disi + backup) + plan Recalculate + M2C2HN06/M3C2PB06 etiketiyle teyit.

## Subcontract Etiketi Ornegi (2026-10-06, T1RURB51 + T1CBRN01)

- T1CBRN01 Cable 1.5mm2 (1382) + T1RURB51 Elasticated Column Band 50mm (1462): kendi BOM'u YOK, purchase_ok, template route [Buy(5), Resupply Subcontractor on Order(9)].
- `_mpp_classify_route` onceligi Subcontract > Manufacture > Buy oldugu icin ikisi de 'subcontract' cikar (Buy olmasina ragmen).
- Gerekce: ikisi de BOM 1680 [T2SCNN01] Seat Cushion (type subcontract, TR) komponenti -> fasoncuya resupply edilen malzeme, route 9 muhtemelen bilerek konmus.
- Kural: komponent fason BOM'da kullaniliyorsa template'teki route 9'u silme (fason resupply kirilir); etiket "fason akisina giriyor" demektir, tedarik yine PO ile cikar. Dogrulama: malzeme fiziken fasoncuya gidiyor mu?

## Prices UoM Kolonu + Corrected Birim Semantigi (2026-10-06, henuz deploy edilmedi)

- Sorun: Prices sekmesinde birim kolonu yoktu; T1CBRN01 stok UoM 'mm', satinalma UoM 'm' (BOM 1680'de koltuk basi 260 mm). Corrected'a metre fiyati (orn. 2) girilse tum formuller bunu per-mm sanip 1000x siserdi (260 x 2 = 520 USD/minder).
- Semantik (kalici): corrected INPUT her zaman satinalma (ticari) UoM'undan girilir; `save_price_override` `_mpp_stock_per_po_factor` ile stok/satir UoM'una cevirip saklar (2 USD/m -> 0.002 USD/mm). STORAGE degismedi: tum maliyet formulleri (_own_usd/_own_try, supplier PO toplamlari, _rfq_line_eff, tree Est.) hala per-line-UoM okur, kod degisikligi gerekmez. Gosterge tersi yonde carpar (stored x faktor).
- Prices items yeni alanlar: uom (satir/stok), last_uom (son alim birimi, farkliysa parantez), price_uom (giris birimi), price_factor, corrected_display (giris birimine cevrilmis). Sifir override vardi -> migrasyon riski yok.
- Reviewer yakaladi: ilk surumde display `/` ile bolunuyordu (2 -> 0.000002 gorunurdu); `*` olarak duzeltildi (get_price_overview + save else-kolu).
- T1CBRN01 corrected etkisi (kod izi, ampirik dogrulama deploy sonrasi): miktarlar (gross/net/order) ASLA degismez; subtotal hep 0 (subcontract'a subtotal yazilmaz); seller yoksa unit_price 0 + 'No supplier'. Degisen: T2SCNN01 rolled_usd += 260 x saklanan-per-mm (2 USD/m girilirse +0.52 USD/minder), supplier PO toplami (order>0 subcontract satirlar dahil, own x order), RFQ taslak fiyati (seller atanirsa; PO satir UoM = mm, ticari olarak m'ye cevrilmesi manuel). Beklenen delta formulu: minder basi = kullanim_mm x girilen_USD_per_m / 1000.
- Dogrulama: py_compile OK, node --check OK, eklenen satirlarda non-ASCII 0 (dosyadaki TR karakterler pre-existing header). Deploy: Python var -> Git Deploy + Upgrade/restart (mesai disi + backup); sonrasi Ctrl+F5. Commit/push YOK.
- UI revizyonu (2026-10-07, henuz commitlenmedi): UoM kolonu kaldirildi (10 kolon). Giris birimi corrected input'un yaninda "per X" yazar (per m / per unit / per kg; X = price_uom). Son-alim birimi farkliysa Last Price hucresinde "/X" gorunur (orn. "0.5700 TRY/m" E1CBRN09). E1CBRN26 ornegi: son alim yok, stok mm + satinalma m -> input "per m" bekler (metre fiyati girilir). Reviewer: sayi tutarliligi + escHtml + alan uyumu OK, kritik bulgu yok.

## Product Cost Sayfasi (2026-10-07, henuz deploy edilmedi)

- Yeni admin-only menu 'Product Cost' (Capacity app, sequence 30, base.group_system).
  Tek client action'da 2 sekme: 1. Cost (canli bottom-up rolled USD, 1-cihaz seti)
  + 3 combo kutusu (base vidalari icerir: full, base+outdoor, base+seat); 2. Prices
  (plan sayfasindan TASINDI - plan sayfasinda artik Prices sekmesi yok).
- Server: yeni AbstractModel `matia.product.cost` (models/matia_product_cost.py).
  Metodlar: get_cost_tree / get_sub_bom_cost / get_prices / reset_prices_to_usd.
  Hepsi @api.model, ensure_one YOK (JS model-style cagirir). Plan kaydi OLUSTURMAZ
  (get_price_overview plan_id=False iken latest plan bulur + yoksa draft OLUSTURUR,
  bu yuzden yeni sayfa onu kullanmaz; override/last-buy her zaman canli okunur).
- Ayni modulun helper'lari import edilir: _mpp_find_kit_boms, _mpp_price_overrides,
  _mpp_product_routes, _mpp_kit_tmpl_ids, _mpp_uom_en, _mpp_stock_per_po_factor,
  _mpp_env_sudo (+ _MPP_MAX_LEVEL, _MPP_TR_COMPANY_ID). Para cevriminde sirket = TR(1).
- Kaydetme ayni global tabloya gider (matia.procurement.price.override): tek satir
  Save -> plan modelindeki save_price_override; toplu TR/US -> bulk_set_location;
  Clear -> clear_price_overrides (hepsi zaten global, plan dosyasi degismedi).
  Reset (yeni): secili satirlarin computed USD'sini corrected'a kopyalar (overwrite,
  confirm'li); make/kit + fiyati 0 olanlar skipped listesinde raporlanir.
- Client: static/src/js/product_cost.js + xml/product_cost.xml (tag
  matia_product_cost.dashboard). SCSS kapsam paylasilir: stock_planning.scss +
  procurement_plan.scss kokune `.o_matia_product_cost` eklendi (msp-/mpp- class
  reuse; combo kutulari icin kucuk mpc- blogu procurement_plan.scss sonunda).
- Excel: yeni route /matia_product_cost/export_xlsx (controllers/product_cost_export.py,
  admin-only, grup + acilmis sub-BOM satirlari, combo ozeti).
- ACL: access_matia_product_cost_admin (model_matia_product_cost, base.group_system).
  Manifest 15.0.2.5.0. Dogrulama: py_compile OK, node --check OK (2 dosya), XML parse
  OK, plan JS/XML'de Prices kalintisi yok (grep temiz).
- Deploy: Python var -> odoobulut Git Deploy + Upgrade/restart (mesai disi + backup);
  sonrasi Ctrl+F5. Commit/push YOK (istenmedi).

## Plan Rolled UoM normalizasyon hatasi (2026-10-07, E2CBAN03)

- Olay: Production plan E2CBAN03 rolled 972.66 USD, Product Cost ayni urun 130.34 USD.
  Bagimsiz XML-RPC okuma + canli `matia.product.cost/get_sub_bom_cost` (staging, modül
  15.0.2.5.0): Cost toplami 130.33 (ekran 130.34 ile ayni) -> **Product Cost DOGRU,
  plan YANLIS** (fark 842.32).
- Kok neden: BOM 1200 satiri 2317 (E1CBRN03 Cable UP) `370 mm` ama urunun stok/line/PO
  UoM'i `m`. Plan `edge_json` ham 370.0 saklar, `_compute_rollup` bunu metre fiyati
  2.28 USD ile carpar -> 843.60 (dogrusu 0.37 x 2.28 = 0.84). +842.76 sisirme.
  Ayni sinifin tersi E1CBRW01: BOM `1.76 m`, stok/line `mm` -> plan 1.76 mm sayar
  (0.0005), dogrusu 1760 mm (0.44). Net fark 842.32 = 972.66 - 130.34 birebir.
- `_mpc_explode` (product cost) BOM qty'yi stok UoM'una cevirir, o yuzden dogru.
  Plan patlatmasi cevirmez (sadece fiyat tarafi `_mpp_line_uom_factor` ile cevrilir).
- Fix yonu: (1) kod - plan explosion'da edge qty'yi line/stok UoM'una normalize et
  (`_mpc_explode` deseni); (2) veri - 2317 satiri `0.37 m`, E1CBRW01 satiri `1760 mm`
  olarak duzelt (muhendislik teyidiyle; uretimi etkiler); (3) mevcut planlar
  Recalculate edilmeden duzelmez (22/24/25/26 hepsi 972.6578 sakliyor).
- Teyit + tam tarama (2026-10-07, staging salt-okunur, `scratch/teyit_uom_lines.py` +
  `scratch/audit_bom_uom.py` -> `scratch/audit_bom_uom_report.json`):
  E1CBRN03 stok/PO UoM `m` (PO/24-00237: 150 m @ 2.13 USD/m; MO tuketimleri m ve mm
  karisik, Odoo MO satir UoM'unda tuketip stoga cevirir - dogru desen), E1CBRW01 stok
  `mm`/PO `m` (PO 200 m, giris hareketi 200000 mm; MO tuketimleri cogunlukla mm).
  BOM satirlari fiziksel dogru (muhendis pratik birimle girmis), hata %100 plan
  patlatmasinda. Capraz kontrol: 972.66 - 842.76 + 0.44 = 130.34 Product Cost ile
  kurusuna uyar.
- Ayni sinif TUM aktif BOM'larda 10 satir (511 BOM / 1551 satir tarandi, farkli
  kategori 0): E1CBRN03/E2CBAN03 (1000x, ~843 USD), E1CBRW01/E2CBAN03 (0.001x,
  ~0.44 eksik), T1HLRB51 x3 (Knee/Seat Cushion, ~101-185 USD), T1HSRB50 x4 (Velcro
  setleri, ~20-96 USD), N1PGRN02/Packaging (fiyat yok, etkisi 0). Dar nokta:
  `matia_procurement_plan.py` patlatma L869-875 (phantom) + L883-891 (normal) ham
  `bl.product_qty` saklar; satir uom_id her zaman stok UoM (L1181-1197),
  `_compute_rollup` (L1472+) qty x satir-UoM fiyati carpar. Ayni ham qty net cascade,
  pool/branch, exact allocation, edge_json, gross/net/order_qty ve RFQ/MO uretimini
  besler (E1CBRN03'e 370 m siparis riski). Fiyat tarafi saglam (rolled per-line-UoM,
  digits (16,4)). Plan: `plans/production_plan_edge_qty_normalization.md`.

## FIX Production Plan UoM normalizasyonu (2026-10-07)
`_mpp_norm_bom_qty(bl)` helper + 5 cagri (patlatma phantom/normal, _mpp_need_per_top
x2, _mpp_sub_items); lineless faktor PO->stok UoM'a cevrildu, satir uom etiketi stok
UoM, edge_json help guncellendi. BOM verisi degismedi. Simulasyon: E2CBAN03 plan
toplami 972.66 -> 130.34 (Product Cost ile ayni). odoo-reviewer: approve-with-nits
(kabul edilmeyen: `or 1.0` modul konvansiyonu korundu; tooltip UoM suffix kapsam disi).
Dogrulama: py_compile + scratch/simulate_rollup_fix.py. DEPLOY: Python degisikligi
Git Deploy/restart gerektirir (mesai disi + backup); eski planlar Recalculate
 edilmeden duzelmez (cache). Pushed main 8d2cb4a.
CANLI TEYIT 2026-10-07 (staging 15.0.2.5.0, plan 26 Recalculate): E2CBAN03 rolled 130.341 = own 0 (make, last buy yok) + 35 cocuk edge qty x cocuk rolled toplami (edge 0.37 m / 1760 mm normalize ONAYLI). 130.34 birim maliyet needed/stoktan BAGIMSIZDIR; needed 100 (E2MBAN03) + stoklar sadece gross/net/order/est'i belirler: MB net 89 (US stok 11) -> E2CBAN03 gross 100, demand 89, net 84 (TR stok 5) -> est 130.341x84=10,948.64. UYARI: canli (matia.odoobulut.com) hala 15.0.1.0.0 ve procurement modelleri yok -> canliya henuz deploy edilmedi.
FOLLOW-UP 2026-10-07: MPC de ayni helper'a gecti (matia_product_cost._mpc_explode 2 nokta: kit tops + children walk, zero-guard ile eski 0.0 semantigi korundu) -> tek donusum noktasi; davranis degisikligi yok (reviewer teyitli). Recalculate sonrasi capraz kontrol eklendi: _mpp_crosscheck_vs_cost plan rolled_usd vs Product Cost unit_map karsilastirir (tolerans abs>0.05 VE rel>%0.5, sifir-birimler atlanir, her hata yutulur); uyumsuzluk log + summary.cost_check + JS warning bildirimi. Bilinen benign fark: buy-rotali phantom top (planda own fiyatli, cost'ta sifir). DEPLOY: onceki fix ile ayni (Git Deploy/restart + Recalculate).

## Product Cost Prices Urun Linki (2026-10-07, henuz deploy edilmedi)

- Istek: Prices sekmesinde urun adina tiklaninca urun sayfasi yan sekmede acilsin.
- Cozum (static-only): Tab 2 Part hucresi `<a class="mpp-prod-link" data-pid>` oldu; `click .mpp-prod-link` -> `_onOpenProduct` `window.open('/web#id=PID&model=product.product&view_type=form','_blank')` (preventDefault + stopPropagation; satir secimi/checkbox etkilenmez). Tab 1 Cost agacina DOKUNULMADI (oradaki tiklama sub-BOM acar). SCSS: `.mpp-prod-link:hover` underline (procurement_plan.scss price-table blogu).
- Dogrulama: `node --check` OK; TR-karakter taramasi temiz (tek eslesme pre-existing UoM map). Deploy: static-only -> modul Upgrade yeterli, restart gerekmez; sonrasi Ctrl+F5. Commit/push YOK.

## Production Plan Net-Cost Semantigi (2026-10-07, henuz deploy edilmedi, 15.0.2.6.0)

- Kullanici karari: plan sayfasi sifirdan maliyet DEGIL gap gosterir. 
olled_usd = NET birim (
et_cost/net_qty), sifirdan birim scratch_unit_usd'de (Product Cost ile cross-check scratch'e bagli). est = satir net toplami. Kit ozetleri + export toplami scratch bazinda (scratch_total_usd).
- Paylasimli cocuk stoku oransal dusulur: pay(P->C) = net_cost(C) x contrib(P,C)/demand(C) (her ebeveyn sadece gap payini tasir; satir okunmadigi icin phantom/satirsiz cocuk seffaf akar; pool/producible maliyete girmez, display-only). Staging plan 26 replika (963/963 cascade, 427/427 yaprak): E2CBAN03 net 84 -> toplam 10,171.20 / birim 121.0857 (scratch 130.341); E2MBAN03 net 89 -> 48,305.60 / 542.7595.
- Reviewer duzeltmeleri: _kits_from_stored scratch okur; legacy supplier filtresi ekranla ayni kapsama genisletildi (buy/subcontract/unknown); unknown route nakit toplama girmez (unknown_total_usd/unknown_count ayri, RFQ uretmez); _own_* unknown'u fiyatlar (MPC ile uyumlu). Deploy: Git Deploy + Upgrade/restart (mesai disi + backup) + plan Recalculate + E2CBAN03 sayilariyla teyit; sonrasi Ctrl+F5. Commit/push kullanici onayiyla.

## Prices Std USD Kolonu + Copy Std (2026-10-07, henuz deploy edilmedi)

- Istek: Prices sekmesinde standard_price USD kolonu + secili satirlari corrected'a kopyalayan buton (son alimi olmayan urunlere hizli doldurma).
- Yontem (`_mpc_std_usd_map`): `product.price.history` YOK; variant `write_date` her zaman son SVL `create_date`'ine esit (islevsiz), template `write_date` bayat. Tahmin: `standard_price`'a `max(0.005, 1e-4*deger)` toleransla eslesen EN SON incoming (`quantity>0`) `stock.valuation.layer` `create_date`'i = son degisim gunu; o gunun TR-company USD kuru (`res.currency.rate`, `company_id=1` SART — US sirketi TRY satirlarinda rate ~32 yazar, ters yon!). Eslesme yoksa en guncel TR kuru (`*` isaretli). `std_usd = std_TRY * rate`; display = `std_usd * _mpp_stock_per_po_factor(stok, URUN `uom_po_id`)'si (save_price_override ticari girdiyi urun PO-UoM'una gore boldugu icin round-trip birebir). Dogrulama (5 urun): RAL6K125 0.15 TRY/mm -> 4.6635 USD/m (son alim ~4.8 USD/m); E1CBRN06 -> 0.6154 USD/m (son alim 0.68 EUR/m).
- RPC `copy_std_to_corrected`: reset ile ayni desen (make/kit + std<=0 skip, `Mpp.save_price_override(pid, std_usd*pf, False)`). JS: Std USD kolonu (siralama/filtre, rate-gunu altyazi, `*` = latest fallback) + Copy Std butonu (confirm'li). Bilinen kapsam-disi tutarsizlik (DEGISTIRILMEDI): `reset_prices_to_usd` ve `corrected_display` last-buy PO-UoM faktorunu kullanirken save urun `uom_po_id`'sine gore boler; ikisi farkliysa reset saklanan degeri sasisir (normalde ayni UoM oldugu icin pratikte sorun yok).
- Deploy: PYTHON degisikligi -> odoobulut Git Deploy + servis restart (mesai disi + backup), `button_immediate_upgrade` YUKLEMEZ; sonrasi modul Upgrade + Ctrl+F5. Commit/push YOK.

## Prices Std Iki-Yonlu (TR/US) + Location-Aware Type (2026-10-07, henuz deploy edilmedi)

- Istek: P3CPPGA5 TR'de 135.52 TRY, US'te 5.0 USD (ayni urun, sirkete gore farkli deger). Std kolonu location'a gore taraf secmeli: us -> US degeri (USD oldugu icin cevrim YOK), tr -> TR degeri (TRY->USD cevrimli), bos location -> kisa Ingilizce `location needed` placeholder'i. Birim cevrimleri (mm->m) her zaman uygulanir.
- Bulgular: `standard_price` sirket-bagimsiz (ir.property satiri YOK); US 5.0 USD degeri US-company SVL katmanlarindan gelir (en yeni 2026-04-28). 0.1113 gizemi cozuldu: 5.0 x 2026-04-28 TR kuru (0.022252238) = 0.11126 — USD fiyat TRY'ymis gibi cevrilmis; sayfayi gosteren kaynak henuz identify edilmedi (canlida Prices sekmesi YOK).
- Yontem: `_mpc_std_usd_map` iki taraf doner — TR: std_TRY x TR-layer eslesme gunu kuru (fallback latest, isaretli); US: en yeni US-company incoming layer `unit_cost` (cevrim YOK). `get_prices` location'a gore taraf secer + `std_needs_location` bayragi; `copy_std_to_corrected` satir location'ina gore tarafi kopyalar, locsuz satiri skip eder, save'e row loc gecer (False degil).
- Type display: location doluysa sirket-gorunur (company_id in (False,C)) subcontract BOM -> subcontract, normal BOM+Manufacture -> make, seller+Buy/purchase_ok -> buy; gorunmezse global siniflama korunur; kit her zaman global. Helper'lar: `_mpp_company_bom_types`, `_mpp_company_seller_tmpls`, `_mpp_location_routes` (200-chunk bulk, fail-fast). `save_price_override` guard effective-location (kaydedilen, yoksa stored) ile ayni helper'dan siniflar; maliyet matematigi (`effective_usd`) bilerek global kalir. Dogrulama: P3CPPGA5 TR 6.9588 USD (135.52 x 2023-05-06 kuru), US 5.0000 USD, Type TR->subcontract / US->buy. Reviewer: kritik yok; latent (loc,tm) key + copy spf_cache uygulandi.
- Deploy: PYTHON degisikligi -> Git Deploy + restart (mesai disi + backup) + modul Upgrade + Ctrl+F5. Commit/push YOK.

## Plan Source Bosa Dusme — P3CPPGA5 (2026-10-07, staging olcumu)

- Gozlem: Prices'ta location=us (override id 163, 17.63 USD) ama plan Source sutunu bos.
- Kok neden: Source = `plan.line.last_company_id` = son GERCEK (3rd-party) alimin sirketi; override location ayri alan ve tree'ye dusmuyor. P3CPPGA5'in tek PO satiri PO/23-00004 (2023-05-08, US sirketi) partneri kendi sirketimiz (Matia, id 1) oldugu icin `_mpp_last_buys` own-partner filtresine takiliyor -> lb bos -> last_company=False, last_price=0. Seller sutunu pricelist fallback'ten PAKEL doldugu icin tablo Seller dolu / Source bos gorunuyor.
- RFQ/sirket gruplama override location'a saygi duyar (`_MPP_OVERRIDE_COMPANY`: US->2), yani RFQ US sirketine gider ama Source rozeti bunu gostermez — tasarim boslugu.
- Aday fix (ONAYSIZ uygulama): tree `last_company` bosken override location fallback'i (`us`->USA, `tr`->TR, manual isaretiyle) `get_tree_with_cost`/`get_sub_bom_cost`/`_plan_summary`'de goster.
- Uygulama (2026-10-07, kullanici onayli, henuz deploy edilmedi): `_mpp_last_buys(env_sudo, pids, company_by_pid=None)` — location'li urunde son GERCEK alim o location'in sirketiyle sinirli aranir (`order_id.company_id` traversali, sirket basina 1 bulk sorgu); locsuz urunde global kural korunur. 5 caller scope gecirir (`action_assign_suppliers`, `get_sub_bom_cost`, `get_full_tree`, `get_prices`, `_mpc_price_map`). Yeni `_mpp_source_label()` — `last_company_id` varsa aynen, yoksa override location (`last_company_manual=True`, rozette `USA*` + `_t` tooltip). Sirket kodu `_MPP_COMPANY_CODE_CACHE` ile memoize (restart temizler). Seller/pricelist ve `_rfq_line_eff` DEGISTIRILMEDI. Reviewer hukmu: sartli onay (kritik yok). Deploy: Git Deploy + restart (mesai disi + backup) + modul Upgrade + Ctrl+F5; `button_immediate_upgrade` YUKLEMEZ. Commit/push YOK.

## M1WHRN07 Fiyat Gorunmeme (2026-10-07, staging olcumu)

- Sikayet: plan (Cost) sayfasinda M1WHRN07 fiyati 0, Prices'a 37.95 USD girilmis, BOM'u kaldirilmis.
- Olcu: staging OWN-BOMS BOS (1220/1714 silinmis), override id 7 = 37.95 USD + location us, son gercek alim 23.95 USD ROLKO NA (PO/24-00324). Template 1243 route [Buy(5), Manufacture(6)] HALA cift; `_mpp_classify_route` Manufacture'i ustun tutar -> global route 'make'.
- Kok neden: `_mpc_price_map` own fiyati global route ile sifirlar (`if route not in ('make','kit')`, matia_product_cost.py:238). Location-scoped 'buy' (US seller + BOM yok -> `_mpp_location_routes` buy doner) SADECE Type rozeti + save guard'da gecerli (get_prices:709, save:4337), maliyet matematigine girmez. Yani BOM silmek YETMEZ, template'te Manufacture durdukca Cost 0 kalir; Prices eff 37.95 gosterir ama Cost'a yansimaz.
- Refresh sorusu: `_onRecalculate` (product_cost.js:145) `get_cost_tree` + (yukluyse) `get_prices`'i CANLI ceker, `subCache`/`expanded` temizler; stale cache YOK. Fiyat yoklugu refresh'ten degil, route mantigindan.
- Prod notu: canli `matia.odoobulut.com` hala 15.0.1.0.0 (product.cost/override modeli YOK) ve BOM 1220 (TR) + 1714 (US) AKTIF (3 satir: Rim/Rubber/Tube). Kaldirma + fiyat girisi SADECE staging'de.
- Fix yonleri (ONAYSIZ, deploy bekler): (a) kod: `_mpc_price_map`'te override location varsa location-scoped route ile own hesapla (save guard deseni); (b) veri: template'ten Manufacture route'unu kaldir (urun artik saf Buy - ROLKO'dan aliniyor - ama MO akisi kapanir, muhendislik karari). scratch/check_m1whrn07*.py silindi.
- Guncelleme (2026-10-07, kullanici rotayi kaldirdi): template 1243 artik SADECE [Buy(5)], purchase_ok=True, BOM HIC YOK (aktif/pasif), override id 7 = 37.95 USD + us. `_mpp_classify_route` -> global 'buy' (location'a bakmadan, dogrudan template route'tan), `_mpc_price_map:238` own = 37.95. CANLI dogrulama: `matia.product.cost get_cost_tree` M1WHRN07 (outdoor) unit_usd=37.95 donuyor. Yani backend duzeldi; ekranda hala 0 gorunuyorsa sebep browser cache -> plan sayfasinda Recalculate + Ctrl+F5. Not: staging MCP su an auth hatasi veriyor (process env `test-argerobotik`'e bakiyor); olcum failover `scratch/verify_m1whrn07_route.py` (XML-RPC, .env) ile yapildi.
- Guncelleme 2 (2026-10-07, Plan sayfasi): Cost sayfasi 37.95 gosterirken Plan tree'de Last USD 0. CANLI `get_startup_tree`: M1WHRN07 eff_usd/corrected_usd=37.95 (live override) AMA last_usd/last_price/rolled=0 (sakli satir). Kok neden: Plan refresh (`mpp-btn-reload` -> `_onReload` -> `get_startup_tree`/`get_tree_with_cost`, procurement_plan.js:313) target degismediyse CACHED dala girer (`built_target_json == target_json`, matia_procurement_plan.py:2659) ve sakli `plan.line` satirlarini aynen doner; satirlar urun henuz make iken hesaplandigi icin last/rolled 0 kalmis. Plan tree'de eff/corrected sutunu YOK, Last USD sutunu `r.last_usd` basar (procurement_plan.js:1104) -> fiyat bos gorunur. Cozum: Needed'i degistirip blur/enter -> `set_targets_and_rebuild` (js:365) -> `action_explode_and_net` satirlari UNLINK+recreate eder (plan.py:1460) ve buy olarak yeniden hesaplar. DIKKAT: rebuild RFQ/MO linklerini siler (cached dalin varlik sebebi bu); rebuild oncesi plandan uretilmis RFQ/MO var mi kontrol et.
- Rebuild butonu (2026-10-07, kullanici istekli, kodlandi - deploy BEKLIYOR): Plan sayfasi header'a Refresh yanina `Rebuild` butonu (btn-warning, mpp-btn-rebuild; procurement_plan.xml:19-21). Tiklayinca `Dialog.confirm` (Odoo 15 callback deseni, product_cost.js Reset/Copy ile ayni) RFQ/MO uyari + onay -> `set_targets_and_rebuild(plan_id, needMap)` (mevcut Needed'larla, ayni `_applySummary`+`_renderTree` akisi; js:322-360). Boylece Needed kurcalamadan (200->201->200 hack) master veri (rota/BOM/stok/fiyat) degisiklikleri tek tikla yeniden hesaplanir. Refresh davranisi DEGISTIRILMEDI (sadece kayitli durumu gosterir). Manifest 15.0.2.6.0->15.0.2.6.1. `node --check` + XML parse OK, odoo-reviewer HUKMU: ONAY (kritik yok). Deploy: Python degisikligi YOK -> restart gerekmez ama odoobulut Git Deploy + modul Upgrade gerekir (canli DB: mesai disi + oncesi backup); sonrasi Ctrl+F5 (asset bundle).
- Hiz farki + Rebuild butonu EKSIKLIGI (2026-10-07): `_onRebuild` ile `_onNeedChange` AYNI RPC'yi (`set_targets_and_rebuild`, ayni needMap) cagirir - JS'te fark YOK. Fark `get_tree_with_cost` (plan.py:2659) `built_target_json == target_json` kontrolu: Needed degismediyse CACHED dal (`_plan_summary`+`_kits_from_stored`, hesap yok) -> Rebuild HIZLI; Needed 50->51 degisince GERCEK rebuild (`action_explode_and_net` BOM patlatma + TR/US netting + fiyat cozumu + `action_assign_suppliers`, satir unlink+recreate) -> YAVAS. SONUC: Rebuild butonu Needed degismeden basilirsa cached dala girer, Refresh ile AYNI isi yapar - rota/BOM/fiyat degisikligini yansitmaz (buton amacini tutmuyor). Duzeltme: `set_targets_and_rebuild`'e `force` bayragi (cached kosulunu atlatip `action_explode_and_net`'e zorlar) - kucuk Python degisikligi, Git Deploy + restart ister (mesai disi + backup).
- (2026-10-07 KAPANDI, commit 466794d): force bayragi uygulandi (`set_targets_and_rebuild(..., force)` -> `get_tree_with_cost(..., force)`, JS `true` gonderir); odoo-reviewer SARTLI ONAY (kod dogru, sart: Git Deploy + restart). Kucuk notlar (ileride): `json.dumps` `sort_keys` yok (key sirasi degisirse gereksiz rebuild), `bool(force)` dis XML-RPC string "false" edge'i, force rebuild `state`'i calculated'a dusururken header RFQ'lar durur.

## E1RCRN01 Remote Control 0.6126 vs 192.61 TL (2026-10-07, canli veri, cozuldu)

- TR 192.61'nin kaynagi: `standard_price=192.61` TRY (fifo, real_time, company global). Incoming SVL katmanlari (qty>0, sadece 4 adet): 2023-05-08 sayim 291x192.61 (TR), 2024-02-27 duzeltme 200x192.61 (TR), 2026-03-02 US giris 10x30.0 (US, PO/26-00002), 2026-05-11 duzeltme 1x192.61 (TR). Yani 192.61, 2022-12-31 sayim girisinden kalan manuel maliyet; hicbir PO'dan gelmiyor. Tek PO sirkelerarasi (US sirket, USD, partner kendi TR sirketimiz id 1) -> `_mpp_last_buys` own-partner filtresine takilir, TR std'yi etkilemez (ayri sirket katmani).
- 0.6126'nin kaynagi: 30 (USD PO fiyati) x 0.0204207074 (3 Eki USD kuru) = 0.612621 -> 0.6126 birebir. USD fiyat TRY sanilip bir kez daha USD'ye cevrilmis (cift cevrim) + sirketerarasi alim gercek tedarikci sanilmis. Ayni sinif onceden: 0.1113 = 5.0 x 28 Nis kuru (yukaridaki Std Iki-Yonlu girdisi). Guncel kodda iki koruma var (own-partner filtresi + `cur_id != usd` guard); staging eski deploy'la calistigi icin 0.6126 gorunmus.
- Deploy sonrasi beklenen (kod 15.0.2.6.2): Last bos/0 (3rd-party alim yok), Std location'a gore TR ~4.26 USD (192.61 x 9 May kuru 0.0221287896, May-11 tabakaya en yakin) / US 30.00 USD; location bosken placeholder.
- EKONOMI UYARISI: 30 USD ~1305 TRY (Sub kuru) / ~1473 TRY (bugun); TR std 192.61 ~7x bayat. Maliyet guncelleme kullanici karari.
- Yan bulgu (ACIK): urun karti seller_ids [2876,3596] gosterir ama `product.supplierinfo` MCP'de 0 kayit doner (bosa filtreli bile 0); diagnose_access okunabilir der. UI'dan bakilmali (sirket-kapsamli kayit suphesi).

## E1RCRN01 Duzeltme — standard_price sirket-bagimliymis (2026-10-08, commit 5d0e831, deploy BEKLIYOR)

- Ustteki "cozuldu" girdisi YANLISTI: staging eski kod kosmuyordu, guncel kodda acik vardi. `standard_price` company_dependent=true (`ir.property` satirlari var; 2039: TR 192.61 id 5326 / US 30.0 id 6441, prod+staging ID'ler bile ayni). `_mpc_std_usd_map` pinsiz okuyunca US baglamindan 30.0 alip TR kuruyla carpti: 30.0 x 0.0204207074 = 0.612621222 (Oct 2026, latest=true). Docstring'deki "company-dependent degil" iddiasi da yanlisti.
- Fix (kullanici karari: location TR -> TR firmasindan, US -> US firmasindan): TR tarafi force_company=1 ile TR std (TRY->USD, katman-gunu kuru eslesmesi aynen), US tarafi force_company=2 ile US std (cevrim YOK; ay dipnotu varsa en yeni US katmanindan, yoksa bos). Katman sorgusu iki std'den birine sahip urunleri kapsar. `copy_std_to_corrected` docstring'i guncellendi (davranis map'ten geldigi icin otomatik duzeldi). odoo-15 skill yuklendi, `py_compile` OK, push'landi.
- Deploy sonrasi beklenen: staging (TR katmani YOK) TR ~3.93* USD (192.61 x latest, `*` isaretli); prod TR ~4.26 USD (11-May eslesme -> 9-May kuru); US 30.00 USD. Deploy: Git Deploy + restart (mesai disi + backup) + modul Upgrade + Ctrl+F5.

## Plan Cost Header (2026-10-08, henuz deploy edilmedi)

- Istek: Product Cost - Cost sekmesindeki grup toplam kartlari (4 KPI + 3 combo, screenshot) Production Plan - Plan sekmesine tasinsin; ayni gorunum, sadece ana 4 grubun kutusuna sayi giris alani eklensin.
- Cozum (static-only, Python YOK): Plan pane 1'in ustune `mpp-cost-kpi-grid` + `mpp-cost-combo-row` container'lari eklendi (procurement_plan.xml); eski `mpp-fill-bar` kaldirildi. `procurement_plan.js` `_fetchCost` ile `matia.product.cost get_cost_tree`'yi cagirir (iki sayfa da base.group_system, cross-model RPC guvenli), `_renderCostKpis` Cost sayfasindaki kartlari birebir cizer + her karta `mpp-fill-n` N input'u koyar (input degerleri `fillN`'den, refresh'te DOM'dan geri okunur). `_onNeedFillAll` DEGISTIRILMEDI (ayni class'i okur); tek Apply butonu kartlarin altinda (`mpp-cost-apply`). Kartlar pane 1 icinde oldugu icin Tab 2'de otomatik gizlenir (`_showTab` fill-bar blogu silindi). Stiller paylasimli kapsamdan gelir (stock_planning.scss `.msp-kpi-card`, ayni dosyadaki `.mpc-combo-box`); yeni SCSS sadece kart-ici input (`flex:1 1 100%`, wrap) + apply satiri.
- Cost fetch: `willStart` + Rebuild sonrasi (fiyat degisebilir); `_renderTree` icinde DEGIL (typing focus/reset korunur). Dogrulama: `node --check` OK (2 dosya), XML parse OK, TR-karakter taramasi temiz (tek eslesme pre-existing UoM map).
- Deploy: static-only -> modul Upgrade yeterli, restart gerekmez; sonrasi Ctrl+F5. Commit/push YOK.
- DUZELTME (2026-10-08, kullanici uyarisi): ilk implementasyon kartlara Cost sayfasinin BRUT 1-set toplamlarini (`get_cost_tree set_total`, stok dusulmemis) koymustu; Plan sayfasinda kartlar alttaki listenin STOK-DUSULMUS (net) toplamlarini gostermeli. Yeni cozum (hala static-only, Python YOK): `_fetchCost`/`_rpcCost` ve `get_cost_tree` RPC'si KALDIRILDI; `_renderCostKpis` grup toplamini `treeGroups`'taki her top'un `rolled_total_usd` toplami olarak hesaplar (server `_mpp_net_costs`: paylasilan cocugun net maliyeti ebeveynlere oransal bolunur, cift sayim yok; stok karsilanan malzeme haric). Combo'lar bu net grup toplamlarindan turetilir (base = base+screws). Kart alt yazisi "N tops · net of stock". `_renderCostKpis` artik her `_applySummary` sonunda calisir (startup/refresh/rebuild/slot - agacla hep senkron); `_renderTree` icinde DEGIL (typing focus korunur), N input degerleri render oncesi DOM'dan `fillN`'e geri okunur. `node --check` OK. Deploy: static-only -> modul Upgrade + Ctrl+F5.
- ORTALAMA CIHAZ SATIRI (2026-10-08, kullanici istegi): Needed top bazinda farkli olabilir (coguna 50, bazisina 60-70). Kartlara toplam altina yaklasik 1 cihaz maliyeti eklendi (`kpi-avg`, mavi `~$X / device`): cihaz sayisi = toplam Needed / toplam BOM kullanim (kullanim-agirlikli ortalama; Needed'siz top'lar haric), birim = net grup toplami / cihaz sayisi. Stok-dusulu oldugu icin `~` isaretli + tooltip aciklamali. Ornek: 4 top (50/50/60/70, kullanim 1) -> 57.5 cihaz. Combo'larda yok (sadece grup kartlarinda). SCSS'e `.kpi-avg` eklendi; `node --check` OK; static-only.
- APPLY KALDIRILDI (2026-10-08, kullanici istegi): kartlarin altindaki Apply butonu + `.mpp-cost-apply` satiri silindi (xml/js/scss). Karta N yazinca `_onFillNInput` (`input` eventi) o grubun tum top'larina Needed=N yazar, `_markNeedsDirty` (Rebuild kirmizi) + `_renderTree` ile liste aninda guncellenir; server'a bir sey gitmez, Rebuild'e basinca `set_targets_and_rebuild` hesaplar. `_onFillNBlur` (`change`) degeri normalize edip `fillN`'e yazar. Eski `_onNeedFillAll` + click binding silindi; referans taramasi temiz, `node --check` + XML parse OK; static-only.
- KART-DOLDURMA GORSEL BUG (2026-10-08, kullanici bildirimi): karta 60 yazinca Needed'lar listede degismiyordu. Kok neden: satir render `r.need` (server degeri) varsa onu basar, local `needMap`'e sadece `r.need` bosken duser (js ~1088/~1191/~1464); `_onFillNInput` sadece `needMap`'i guncelleyip `_renderTree` cagiriyordu, eski `r.need` kazaniyordu (eski Apply'da da ayni yuzden gorsel degismiyordu). Fix (JS only): doldurma sirasinda grubun satir objelerinde `r.need = N` de yaziliyor; `_renderTree` yeni sayilari gosterir, Rebuild kirmizi, Rebuild hesaplar. `node --check` OK; static-only.

## Slot Aciklama Alani (2026-10-08, henuz deploy edilmedi)

- Istek: Production Plan slot bar'da slot secimi ile Save butonu arasina her study icin aciklama alani.
- Cozum: `matia.procurement.plan.note` (Text, zaten modelde vardi, migration yok) slot aciklamasi olarak kullanilir. `_plan_summary` -> `slot_note`, `get_slot_list` -> her girdide `note`, `save_slot(slot, targets, note=False)` 3. parametre (False/None = dokunma, '' = temizle; eski 2-arg cagrilar uyumlu). JS: `mpp-slot-note` input (xml), `slotNote`/`dirtySlotNote` state + `_onSlotNoteInput`, `_renderSlotBar` aktif slot note'unu doldurur, `_onSlotSave` note'u 3. arg olarak gonderir; Reload onayi `dirtySlotNote`'u da kapsar. SCSS: `.mpp-slot-note` flex genislik. Dogrulama: `py_compile` + `node --check` + XML parse OK, odoo-reviewer kritik bulgu yok.
- Deploy: PYTHON degisikligi var -> Git Deploy + servis restart gerekir (mesai disi + backup), `button_immediate_upgrade` yetmez; sonrasi modul Upgrade + Ctrl+F5.

## Bos USD Hucreleri — sub-cent Fiyatlar (2026-10-08, henuz deploy edilmedi)

- Sikayet: Product Cost - Prices sayfasinda E1PCK245 ve E1TRRN13'te Son Fiyat dolu ama USD sutunu bos.
- Kok neden: `res.currency._convert()` hedef kurun yuvarlamasina gore yuvarlar (USD 0.01). Son alimlar minik TRY tutarlar (0.10 / 0.15 TRY, Sub 2024) -> ~0.0033/0.0049 USD -> 0.00'e yuvarlanip 0.0 yaziliyor; JS 0/falsy degeri bos hucre gosteriyor. Kurlar EKSIK DEGILDI (15/16-Sub-2024 kurleri mevcut).
- Fix: `_convert` cagrilarina `round=False` (Odoo 15 imzasinda gecerli kwarg, resmi 15.0 kaynaginda dogrulandi): `_last_buy_vals` (plan satiri `last_price_usd`, digits 16,4), `_mpc_price_map` (live `last_usd`), tree-cost fallback (planda satir yokken). Plan para birimine (TRY) ceviren 5 cagri DEGISTIRILMEDI (muhasebe/RFQ/toplam degerleri yuvarlanmis kalmali). `_last_buy_vals` docstring'ine @param/@return eklendi. Dogrulama: `py_compile` OK, odoo-reviewer kritik bulgu yok.
- Deploy sonrasi: E1PCK245 ~0.0033, E1TRRN13 ~0.0049 USD (4 ondalik) gorunur. MEVCUT plan satirlarindaki 0.0 degerleri planlar yeniden hesaplanana (assign-suppliers) kadar aynen kalir. Deploy: PYTHON degisikligi -> Git Deploy + restart (mesai disi + backup) + modul Upgrade + Ctrl+F5.
- Not: float domain `['last_price_usd','=','0']` search_read'de 0 satir doner ama kayitlar 0.0 (float '=' karsilastirma cilvesi; urun-kapsamli sorgu kullan).

## Supplier & Production UI Revizyonu (2026-10-08, henuz deploy edilmedi)

- Istek (6 madde): supplier acinca sayfa yukari atmasin; alt-satirlar ana sutunlarla hizali olsun; grup sirasi USA ustte TR altta; supplier gruplarinda Show/Hide; Draft RFQ/MO kartlari yerine USA/TR Est Total; Suppliers kartinda USA/TR supplier + RFQ/MO sayilari.
- Cozum (static-only, Python YOK): `_preserveSupScroll` (action-root + window scroll kaydet/geri-yukle; `$` yoksa `window.scrollTo` fallback) `_onSupToggle`/`_onSupGroupToggle`'da + `_renderSup`'un icinde (RFQ/MO olusturma sonrasi async doldurma da ziplamaz); sira `{'USA':0,'TR':1}`; grup basligina `mpp-btn-sup-group-toggle` Show/Hide (durum `collapsedSupGroups`, plan degisince sifirlanir); alt-satirlar 6 sutunu birebir doldurur (order sag, route orta, total sag, last-buy RFQs kolonunda) + `.mpp-sup-sub-prod` girinti; kartlar: Suppliers (USA x - TR y / Draft RFQ z - MO w), Est Total (grand), USA Est, TR Est (`_supCompanyStats` client-side, server grand ile ayni PO-degeri bazi).
- Dogrulama: `node --check` OK; yeni satirlarda TR-karakter 0 (tek eslesme pre-existing UoM map). Deploy: static-only -> modul Upgrade yeterli, restart gerekmez; sonrasi Ctrl+F5. Commit/push YOK.

## Forest Search: Product Cost + Device Capacity (2026-10-08, henuz deploy edilmedi)

- Plan sayfasindaki agac-ici `search_tree` deseni iki sayfaya tasindi: debounce 350ms + token + server-side orman yuruyusu + ata-yolu genisletme + keep-set filtre (eslesme + tum atalar gorunur, gerisi gizli; sonuc yoksa "No parts match" satiri). Kapali BOM'lar da bulunur, yuklenirken anlik yerel filtre calisir.
- Server: `_mpp_search_kit_forest(env_sudo, query, cap=100)` (matia_procurement_plan.py) — plan `search_tree`'nin hedef-filtresiz ikizi; 4 kit BOM (1766/1737/1738/1736), depth<=_MPP_MAX_LEVEL, cap guard'lar ikizle birebir (append/recurse sonrasi return + dongulerde break). `matia.product.cost` + `matia.stock.planning`'e `search_tree(query)` eklendi (cost `_mpp_env_sudo`, stock inline env + tek-yonlu import, dongu yok).
- Cost client (product_cost.js): `_expandPathCost/_expandOneCost` (subCache `pid|path`, nodeKey `pid|path|chain`, mevcut `get_sub_bom_cost` + `_insertSubRows` kullanilir); filtre keep-set comma-joined prefix. Stock client (stock_planning.js): `_expandPathStock/_expandOneStock` (nodeId `g-grp-p0/p1..`, mevcut `_toggleSubBomForProduct` ile req20/dyn korunur; acik dal asla kapatilmaz); filtre keep-set slash-joined data-path.
- Kural: `search_tree` RPC imzasi `(self, query)` <-> JS `[q]`; yeni metodlar salt-okunur (search/browse), sudo mevcut desenle ayni. No-match satirinda kullanici sorgusu `_escHtml` ile kacar (stock'a helper eklendi, cost'ta vardi); stock bildirim stringleri `_t()` ile sarildi (dosya konvansiyonu; kisa/jenerik kelime uyarisi gecerli ama dosya zaten her seyi _t ile sariyor).
- Dogrulama: `py_compile` + `node --check` OK; odoo-reviewer kritik bulgu yok. Deploy: Python var -> Git Deploy + restart (mesai disi + backup) + modul Upgrade + Ctrl+F5. Commit/push YOK.

## Prices Save All + Secim Temizleme + Hover (2026-10-08, henuz deploy edilmedi)

- Istek (3 madde): corrected'lari tek tek Save yerine tek tusla toplu kaydet; toplu TR/US sonrasi + filtre degisiminde checkbox secimi kalkmali; satir hover'inda renk degisimi.
- Cozum: server `bulk_save_price_overrides(rows)` (matia_procurement_plan.py, max 2000; satir basi `save_price_override` cagirir, make/kit + gecersiz deger skipped/errors listesinde toplanir, batch yari yolda durmaz). JS `priceDirty` map'i (degisen alanlar; sort/filter re-render'inda DOM degil map kaynaktir, satir `mpp-row-dirty` amber bar tasir) + toolbar'da `Save All (N)` butonu (product_cost.xml, kirli sayida yesile doner). Secimler: `_onPriceBulk/_onPriceClear/_onPriceReset/_onPriceCopyStd/_onPriceImport` basarisinda `priceSel={}` + `_onPriceFilter`'da temizlenir (Reload korur). Hover: generic `tr.item-row:hover` td-seviye manual/checked arka planlarinin altinda kalir, o yuzden price-table'a td-seviye hover kurallari eklendi (procurement_plan.scss: duz #f1f5f9, manual #fef3c7, checked #dbeafe, ikisi #fde68a).
- Manifest 15.0.2.6.2->15.0.2.6.3. Dogrulama: `py_compile` + `node --check` + XML parse OK; python taramada TR-karakter 0 (PowerShell `Select-String` case-sensitive TR deseninde locale folding yuzunden YANLIS POZITIF verir, supheli durumda python ile caprazla).
- Deploy: PYTHON var -> Git Deploy + restart (mesai disi + backup) + modul Upgrade + Ctrl+F5. Commit/push YOK.

## English-Only Sayfa Kurali (2026-10-08, Product Cost, henuz deploy edilmedi)

- Sikayet: sayfada Turkce buton isimleri (Save->Kaydet, Reload, Clear...). Kaynakta sabit Turkce string YOKTU (python tarama temiz); sebep Odoo'nun QWeb statik metinleri kullanici arayuz diline OTOMATIK cevirmesi (JS uretimi duz string'ler etkilenmez, `_t()` sarmali da yoktu).
- Kural: Ingilizce-kalacak her QWeb sayfasinda gorunen statik metne `t-translation="off"` konur (product_cost.xml'de 21 nokta: baslik, sekmeler, Recalculate/Excel, legend'lar, Expand/Collapse, Prices toolbar 9 buton). JS `_confirmEn` helper'i (`new Dialog` + sabit Ingilizce butonlar) `Dialog.confirm` yerine gecer (3 nokta: Reset/Copy Std/Import) cunku confirm'in Cancel butonu `_t("Cancel")` ile cevrilir. Title/placeholder attribute'lari client QWeb'de cevrilmez, degisiklik gerekmez.
- Dogrulama: `node --check` + XML parse OK. Deploy: static-only (JS+XML) -> modul Upgrade + Ctrl+F5 (ayni paketteki Python bulk_save icin Git Deploy + restart hala sart). Commit/push YOK.

## Modul Erişim Açılımı: RFQ/MO Admin-Only (2026-10-08, henuz deploy edilmedi)

- Kullanici karari: modulun TUM sayfalari herkese acik; Suppliers & Production'daki RFQ (Create RFQ/Create Again/TR-US RFQ) + Create MO butonlari SADECE admin'e gorunur. Prices duzeltme butonlari (Save/Save All/Clear/Import/TR-US) herkese ACIK kalir (kullanici onayi).
- Denetim cevabi (kullanicinin 2. sorusu): RFQ/MO disinda da YAZAN aksiyonlar VAR ama standart Odoo belgesine dokunan SADECE RFQ/MO'dur (`purchase.order(+line)` create, `mrp.production` + `procurement.group` create). Diger yazmalar modulun kendi tablolarina: plan/line (Rebuild/Slot Save/Needed, unlink+recreate), price.override (Prices Save/Clear/Import - GLOBAL, tum plan + RFQ tutarlarini etkiler). Salt-okunur: Capacity tamami, Excel exportlar, tree expand/search, supplier/RFQ preview, get_rfq_preview.
- Cozum: menuler `base.group_system`->`base.group_user` (procurement + product cost); ACL'ye 4 group_user satiri (plan/line/override/cost, full 1,1,1,1 - rebuild/slot/price akislari unlink dahil yazma ister). `get_supplier_summary` yanitina `can_create_docs` (CALLER env `has_group('base.group_system')` - sudo env DEGIL, yoksa herkes True gorur); JS `_renderSup`'ta `canCreateDocs`'a yazar, RFQ/MO butonlari yerine "Admin only" rozeti + 3 handler'da erken-uyari. Server guard: `_mpp_can_create_docs()` helper (plan.py) + `action_create_mos`/`action_create_supplier_rfq`/`action_create_draft_rfqs` basinda `AccessError` (buton gizleme RPC'den bypass edilebilir, sudo'lu metodlarda grup kontrolu YOKTU). Header "Admin only." yazisi guncellendi.
- Kural: sudo ile calisan her olusturma metodunda grup kontrolu CALLER env'den yapilir; client bayragi sadece gorunum, guvenlik degil. Deploy: Python var -> Git Deploy + restart (mesai disi + backup) + modul Upgrade + Ctrl+F5. Commit/push YOK.

## Combined Export Duzeltmeleri (2026-10-08, popup Products/Suppliers, henuz deploy edilmedi)

- Sikayetler: Products'ta grup sirasi karisik; Unit Cost'ta $0; grup subtotal yok; Suppliers'ta Location belirsiz; tedarikci tutarlari ~40x sisik (ASSAN 50 cihaz $859k).
- Kok neden (en kritigi): popup `_plan_summary.suppliers` kullaniyordu (`subtotal`/`cost` plan para birimi = TRY); ekran Tab2 `get_supplier_summary` (PO-value USD). Export TRY'yi USD diye yaziyordu. Ayrica `_usd0num=round()` 0.5 altini $0 yapiyordu; combined canon client sirasina guveniyordu.
- Cozum (`procurement_export.py` + `procurement_plan.js`, plan: `plans/combined_export_fixes.md`): server-side kanonik sira Base > Outdoor > Seat, Screws 'Base' etiketiyle Base blogu sonunda (satirda `gkey`, yoksa basliktan turetim; `_GROUP_RANK`te screws=0 + screws-last bayragi); never-show-0 kurali (0/None -> bos, 1 alti -> 2dec, 0.005 alti -> 4dec, diger ham deger; CSV'de dec parametreli, half-up cunku banker's round(0.5)=0); Products'ta grup SUBTOTAL + grand TOTAL (statik, tam hassasiyet birikimi); Suppliers basligi 'Buy From'; tedarikci v2 payload (`get_supplier_summary` per slot, `sup_v=2`, company-bazli USD; legacy sekil destegi surer); `cost_slots` server-side `get_supplier_summary` kullanir; single supplier sheet v2 (Buy From kolonu + No supplier/Unknown/No price rozetleri).
- Test: `scratch/test_combined_export.py` gercek modulu stub-odoo ile yukler, 32/32 PASS (sira, half-up, v2 tablo, legacy split, CSV). `py_compile` + `node --check` OK, TR-karakter taramasi temiz (tek eslesme `_uomEn`'deki kastli 'Takim' anahtari).
- Kural: export para hucrelerinde `round()` kullanma (half-up `math.floor(v+0.5)`); client siralamasina guvenme, server-side kanonik sira; supplier tutarinda ekranla ayni baz (PO-value USD) + RFQ ile caprazla. Deploy: Python var -> Git Deploy + Upgrade/restart (mesai disi + backup); sonrasi Ctrl+F5. Commit/push YOK (kullanici onayi bekleniyor).

## Capacity Dinamik Sutun Kaliciligi (2026-10-08, henuz deploy edilmedi)

- Istek: Capacity sayfasinda "Add Column" ile eklenen hedef-cihaz sutunlari sayfa yenilenince kayboluyordu (`dynamic_targets` sadece memory'de).
- Cozum (SADECE JS, Python yok -> restart GEREKMEZ, Git Deploy + modul Upgrade yeterli): `stock_planning.js` `init`'te `this.dynamic_targets = this._loadPersistedTargets()`; ekle/cikar aksiyonlarinda `this._persistTargets()`; saklama `localStorage['msp_dynamic_targets']` (JSON dizi). Yuklemede sanitize: dizi degilse/bos JSON -> [], 20 haric, pozitif int, benzersiz, max 3, sirali (server `get_capacity_planning_data` zaten ayni kuralla kesiyor). Private-mode/quota hatasinda sessiz gec (tablo calisir, sadece kalicilik olmaz).
- Excel tarafi ZATEN HAZIRDI: `_onExportExcel` basliklara + `_buildExportCells` satira dinamik sutunlari yaziyor; kalicilik sayesinde reload sonrasi export da ayni sutunlari icerir. Ayrica dogrulama yok.
- Test: `scratch/test_dyn_targets_persist.js` GERCEK dosyadaki fonksiyon govdelerini calistirir, 9/9 PASS (stale/20/dup/max3/sort, round-trip). `node --check` OK.
- Kural/teklif: kullanici-tercihi tarzi UI durumu icin `res.users` alani (restart ister) yerine localStorage yeterli; cihaza/degisik tarayiciya tasinmaz - kullanici isterse server-side'a gecilir.

## Capacity Dinamik Sutun Server Kaliciligi (2026-10-08, henuz deploy edilmedi)

- Istek: sutunlar baska bilgisayardan acilinca da gorunsun -> Odoo tarafinda, kullanici bazinda saklama.
- Cozum: `models/res_users.py` (YENI, `res.users` inherit, view yok): `matia_capacity_targets` Char alan (JSON liste, default `'[]'`). `stock_planning.py`: `_msp_sanitize_targets()` helper (pozitif int, 20 haric, bool-guard, benzersiz, sirali, max 3) + `matia.stock.planning` uzerinde `get_my_capacity_targets` / `set_my_capacity_targets` (`@api.model`, SADECE `self.env.user`, sudo kendi kaydina scoped - baska kullaniciya erisim YOK). JS: `willStart` once `_fetchSavedTargets` (dolu server listesi local'i ezer + local cache tazelenir; bos server ilk kurulumda local'i korur), ekle/cikar'da `_saveTargetsServer` (sessiz catch, local zaten yazili). `_loadPersistedTargets` artik ortak `_sanitizeTargets` kullanir.
- Guvenlik: yeni model/ACL YOK; view'da alan YOK (gizli tercih). Iki cihaz ayni anda aciksa last-writer-wins.
- Test: `scratch/test_msp_sanitize.py` 11/11 (bool-guard, tuple, cap3 dahil); `scratch/test_dyn_targets_persist.js` 9/9; `py_compile` + `node --check` OK. odoo-15 skill yuklendi (Char inherit + @api.model + sudo-scoped own-record deseni 15-safe).
- Deploy: PYTHON VAR -> Git Deploy + restart (mesai disi + backup) + modul Upgrade + Ctrl+F5. Commit/push YOK (kullanici onayi bekleniyor).

## Plan vs Supplier Total Esitligi (2026-10-08, henuz deploy edilmedi)

- Sikayet: Plan Full Set 94,928.94 vs Suppliers 94,886.64 (staging plan 26, slot 1 '50 Devices', 125x50; fark 42.30 USD).
- Kok neden (canli edge_json ile kanitli): hedef girilen civatalar (1840/1845/1887/1871...) ayni zamanda baska urunlerin bileseni; net maliyet hem kendi top satirinda hem ust ebeveynlerde sayiliyordu (yapisal cift sayim). Ayrica agirliklar demand'e bolunuyordu (girilen+itilen karisik) ve her asamada farkli yuvarlama vardi (satir 2-dec, supplier satir-round, 4-dec rolled_usd kesilmesi).
- Cozum (tek baz, sifir UI degisikligi): `_mpp_line_own_usd` (tek fiyat kurali: override>make-guard>last-buy x UoM faktor), `_mpp_po_cents` (tek yuvarlama: round(x,2)->kurus), `_mpp_split_cents` + `_mpp_retain_push_cents` (en buyuk kalan, kurus-kesin; metin sentinel YOK - int siralamayi bozar, test yakaladi). `_mpp_net_costs` faz-2 her satirda tutulan/itilen kovasi ayirir (want payi satirda kalir, itilen pay ebeveynlere dagilir; phantom tutmaz). Satirlar `rolled_total_usd`'de TAM net gostermeye devam eder (agac dogru kalir); kartlar/combo/export yeni stored `retained_total_usd/_try` alanlarini toplar -> Full Set == supplier grand_total kurusuna esit (unknown-route haric; o ayri listelenir, RFQ uretmez). JS `_renderCostKpis`/`_planCombos` + `_server_combo` retained okur (kolon/isim degisikligi YOK); rebuild oncesi eski planlarda sifir-guard ile satir toplami fallback'i (Recalculate ile gecer).
- Dogrulama: `scratch/test_po_cents.py` 9/9 YESIL (zincir/paylasimli/istege-bagli-cocuk/phantom/sifir-net-ebeveyn/mm-yuvarlama/make-top/derin-want/stoklu-zincir; kart==PO kurusuna); `py_compile` (model+export) + `node --check` OK; TR-tarama temiz (sadece pre-existing UoM map). Degisen: models/matia_procurement_plan.py (+~280: 4 helper + faz-2 + 2 field + summary retained_kits/total + tree item alani), controllers/procurement_export.py (_server_combo), static/.../procurement_plan.js (kart+combo). Plan: `plans/production_plan_supplier_equality.md`.
- Deploy: Python var -> Git Deploy + restart (mesai disi + backup) + modul Upgrade (yeni stored alanlar icin SART) + plan Recalculate + Ctrl+F5. Commit/push YOK (kullanici onayi bekleniyor).

## STAGING KESINTISI: Deploy-Upgrade Sirasi Atlama (2026-10-08, COZULDU)

- Olay: staging Git Deploy + restart sonrasi TOTAL kilit (login dahil). Hata: UndefinedColumn res_users.matia_capacity_targets. Yeni kod yuklenmis (registry alani biliyor) ama modul Upgrade calismamis -> kolon DB'de yok. Stored alan + eksik kolon = modelin HER okumasi coker (display_name/name_get zinciri).
- Teshis notu: MCP search_records domain'i YOK SAYAR (iliskili alan dahil) - supheli sonucu ham xmlrpc + domain ile dogrula. ir.model.fields'te model related oldugundan domain icin model_id.model kullan.
- Kurtarma: arayuz + XML-RPC auth bile coktukten sonra uzaktan upgrade IMKANSIZ (auth yolu res.users._read'e dokunur). 91f787e revert edildi (4905308); duz Deploy + restart yeter (kolon DB'de orphan kalir, zararsiz).
- Onlem: scripts/smoke_after_deploy.py (read-only, stdlib; modul state + REQUIRED_FIELDS + res.users display_name probu; exit 2 = drift). KURAL: her Deploy sonrasi once smoke YESIL, sonra kullaniciya haber ver. Upgrade gerektiren degisiklikte manifest ersion bump yap (Apps'te gorunur). Yan etki (upgrade/write) oncesi ODOO_URL'yi yazdirip instance teyit et (prod/staging karismasi yasanmistir).

## Capacity Sheet Popup Birlesmesi (2026-10-08, uygulandi - commit/push YOK)

- Kapsam: Prices CSV haric TUM Excel butonlari ayni popup (export_popup.js); 3. kart Device Capacity (mpp-exp-cap, fa-tachometer); onExport 4. parametre withCapacity; imza degisikligi 3 cagiriciya isledi (plan/cost/capacity).
- Server: main.py writer ortak helper`a cikti (controllers/capacity_sheet.py: write_capacity_sheet + capacity_csv_lines, saf stdlib, odoo import YOK); procurement_export.py`de _live_capacity (BOM-kapali ust-seviye + standart sutunlar) + _resolve_capacity (ekran payload`u varsa aynen yazar, is_sub filtresi YOK) + _append_capacity_sheet/csv (en sonda) + capacity_only modu (Device_Capacity_<tarih>.xlsx). Sheet sirasi: Cost -> Products -> Suppliers -> Device Capacity.
- Icerik kurali (karar 5): Capacity sayfasi yalnizca-Capacity = ekran aynasi (acik sub-BOM dahil, _buildCapacityPayload aynen post`lanir); Plan/Cost`tan Capacity = live hesap + BOM kapali + standart sutunlar. Bayrak disi dosya adlari byte-identical (test kanitli: main csv parity + legacy tree name).
- Yetki: export_xlsx mod-bazli kapi - capacity_only group_user`a acik, diger modlar group_system; get_slot_list`e can_export_admin bayragi (caller env _mpp_can_create_docs, sudo DEGIL); non-admin popup`ta yalniz Capacity karti gorur. get_slot_list non-admin`e ACL ile acik (csv satir 9) - dogrulandi.
- SAPMA (karar 3): get_my_capacity_targets kodda YOK (revert 4905308, STAGING KESINTISI girdisine bak); live yol payload`daki opsiyonel capacity_targets listesini ayni sanitize ile alir (pozitif int, max 3), yoksa standart sutunlar. Server-side kayitli sutun yeniden istenirse once staging`de Upgrade-sonrasi smoke SART (res.users alani TOTAL kilit yapmisti).
- Dogrulama: scratch/test_capacity_popup_export.py 35/35 (donusum, sira, dosya adi, iki icerik yolu, gate) + test_combined_export.py 34/34; py_compile + node --check OK; diff TR-karakter temiz. Manifest 15.0.2.7.0.
- Deploy: Python VAR -> Git Deploy + restart (mesai disi + oncesi backup) + modul Upgrade + Ctrl+F5. Commit/push YOK (kullanici onayi bekleniyor).

## Export Popup Slot Kurali (2026-10-09, commit YOK)

- Sikayet: Capacity sayfasinda Cost+Capacity birlikte slot sarti cikariyordu; Cost slot-bagimsiz sayfa oldugu icin istenmiyordu.
- Cozum (static-only, Python YOK): Capacity cagiricisinda slot sarti yalniz Suppliers`a kaldi (uyari metni de oyle); Cost(+Capacity) slotsuzken live cost_only (+live capacity) post`lanir (server destegi onceki committe vardi). Popup`a supplierNeedsSlot notu eklendi (Capacity + Cost sayfasi gonderir; Plan sayfasi gondermez cunku orada slotsuz supplier = aktif planin supplier`i, gecerli). Slot 0 popup`ta global filtrelenir (export_popup.js tek yer, 3 cagirici etkilenir; server kabulu aynen).
- Kural: slot-bagimli veri (supplier) ile slot-bagimsiz sayfa verisi (cost/capacity) ayni popup kosuluna baglanmaz. Deploy: static-only -> modul Upgrade yeterli, restart gerekmez; sonrasi Ctrl+F5.

## Web Quote v1 (2026-10-09, kodlandi - deploy BEKLIYOR)

- Yeni `controllers/web_quote.py` (`matia_stock_planning` icinde) + `controllers/__init__.py` tek satir import; manifest `data` degisikligi YOK (plan: `plans/web_quote_justcloud.md`).
- Iki `auth='public'` GET route: `/web_quote` (inline HTML, key kontrolu YOK - sayfa veri tasimaz) + `/web_quote/quote?qty=N&key=...` (key'siz/yanlis -> 403 fail-closed, qty 1..10000 disi -> 400).
- Key `ir.config_parameter` `web_quote.key`'de tutulur (kodda/repoda ASLA yok; staging+prod'a manuel girilir; kayit yoksa 403). Rotate restart gerektirmez.
- Hesap (salt-okunur, write metodu YOK): `matia.product.cost.get_cost_tree()` (combos.full + unit_map) + `matia.stock.planning.get_capacity_planning_data(include_tr=True, include_usa=True, dynamic_targets=[N])` (dynamic_needs[str(N)].val); brut=fullxN, net=SUM(top-level need_units x unit_usd). `fields_get` iki modelde de bos doner (AbstractModel, normal) - imzalar dosyadan dogrulandi; `web_quote.key` prod'da henuz yok (beklenen).
- Dogrulama: `py_compile` OK; ORM write/create/unlink cagrisi YOK (grep temiz); secret taramasi temiz.
- Deploy: Python VAR -> staging Git Deploy + restart (mesai disi + backup) + modul Upgrade; capraz kontrol (100 adet: brut=fullx100, net<=brut, Capacity dynamic_needs ile); prod SADECE staging yesil + kullanici onayi. Faz-2 (slot-write/gizleme) YAPILMADI.

## Web Quote 500 duzeltmesi (2026-10-09, commit 2772a59 - staging deploy BEKLIYOR)

- Belirti: `/web_quote` aciliyor ama Calculate -> "Request failed"; `/web_quote/quote` dogrudan HTML "Internal Server Error".
- Kok neden (BENIM hatam, 15.0 kaynagindan dogrulandi): Odoo 15 `HttpRequest.make_response(data, headers, cookies)` imzasinda `status` parametresi YOK. `status=` vermek her JSON cevabinda TypeError'a yol aciyordu (basari yolu da dahil - try icinde patlayip except'teki ikinci `_json_response` disarida patliyordu) -> Odoo HTML 500. Kapasite sayfasi calistigi icin hesap saglamdi.
- Cozum: response nesnesi donup `response.status_code = status` atanir (tum surumlerde gecerli desen). Dogrulama: py_compile OK; push main'e yapildi.
- Deploy: controller-only Python degisikligi -> Git Deploy + restart YETERLI (modul Upgrade gerekmez); sonrasi staging'de qty=50 + key ile tekrar dene.

## RFQ Eksik @api.model — Ilk Argumanin ID Olarak Yutulmasi (2026-10-12, cozuldu-kodlandi, deploy BEKLIYOR)

- Belirti (staging slot 5 / plan 30, canli teyitli): Tab 2 Suppliers'da TR/US RFQ butonlari "Plan not found." veriyor; supplier satirina tiklayinca alt urunler acilmiyordu (ikincisi bayat JS bundle' imis, Ctrl+F5 ile duzeldi).
- Kok neden: `matia_procurement_plan_rfq.py`'deki 3 RPC giris metodunda (`get_rfq_preview`, `action_create_draft_rfqs`, `action_create_supplier_rfq`) `@api.model` YOKTU. Odoo 15 `call_kw` dekoratorsuz metodu recordset-stili sayip `args[0]`'i kayit ID'si olarak tuketir (`_call_kw_multi`: browse(args[0]), kalan argumanla cagir). Sonuclar: `get_rfq_preview([30])` -> `TypeError: missing plan_id` (canli fault); browser `action_create_supplier_rfq([30, seller=941, ...])` -> plan_id=seller (941) olur, `browse(941)` bos -> 'Plan not found.' (TEDARIKCI id'si plan id saniliyor!). Moduldeki diger TUM RPC metodlarinda `@api.model` vardi; sadece bu 3'u unutulmus (`ensure_one` yoklugu biliniyordu ama dekorator kacmis).
- Canni kanit: ayni plumbing ile `get_supplier_summary([30])` (`@api.model` var) staging+prod'da OK donerken `get_rfq_preview([30])` iki instance'ta da ayni TypeError'u verdi.
- Cozum: 3 metoda `@api.model` eklendi (3 satir, `py_compile` OK). `get_rfq_preview`/`action_create_draft_rfqs`'un su an cagiricisi YOK (olu kod yolu) ama ayni siniftan oldugu icin onlar da duzeltildi. TEHLIKE NOTU: seller id plan id ile cakisirsa YANLIS plana RFQ uretilebilirdi (mevcut ID'lerde cakisma yok: seller 941+, plan 1-30).
- Kural: `(model, method, args)` formunda JS'ten cagrilan ve args[0]'i is-id'si olan HER metoda `@api.model` sart; `ensure_one` yoklugu yetmez, dekorator taramasi da yap (`dec=YOK` taramasi). Deploy: Python var -> Git Deploy + restart (mesai disi + backup) + modul Upgrade + Ctrl+F5; sonrasi slot 5'te TR RFQ ile teyit. Commit/push kullanici onayiyla.

## RFQ Chatter Ust-Urun Kullanim Kirilimi (2026-10-12, kodlandi - push/deploy BEKLIYOR)

- Istek: RFQ chatter'inda hammadde satirinda "bu miktar nereye gidiyor" kirilimi (orn. lama 3500mm -> "200mm x 10 adet = 2000mm"). Mevcut chatter TERS yondeydi (siparis urununun ALT bilesenlerini aciyordu).
- Yontem (NET bazli, kullanici tercihi): `edge_json` ({parent: {child: qty}}, miktar cocuk UoM'inde) tersine cevrilir; ilk satirli ata `edge qty x order_qty` ile listelenir. Satirsiz atalar (phantom kit) faktor biriktirilerek gecilir, net-sifir ustler atlanir, satir basi en buyuk 10 ust + tasi note. Toplam siparise degil ust-suruculu talebe esittir (cocuk stogu farki kapatir) - plan 30 canli verisiyle simule edildi (orn. M1MGRN15: 5 ust, katki toplami 375 vs brut 825).
- Kod: `_rfq_usage_map` + `_rfq_usage_lines` + `_rfq_bom_chatter` genisletmesi (asagiya dogru BOM listesi korunur, alta "uses: ..." satirlari eklenir). py_compile OK + gercek veri simulasyonu OK. Deploy: Git Deploy + restart + Upgrade (Python).

## RFQ Satir Aciklamasi Standartlasmasi (2026-10-12, kodlandi - push/deploy BEKLIYOR)

- Istek: modül PO satir `name`'ine `[plan] urun` yazmasin; standart satin alma aciklamasi gelsin.
- Cozum: `_rfq_std_line_name` helper (stok purchase onchange aynasi: tedarikci dilinde `display_name` + varsa `description_purchase`, partner context dahil). Iki RFQ uretim blogundaki `[%s] %s` kaldirildi. `description_purchase` fields_get ile dogrulandi. py_compile OK.

## Iptal RFQ Suppliers'ta Gizleme (2026-10-12, kodlandi - push/deploy BEKLIYOR)

- Belirti (staging canli teyitli): iptal edilen `PO/26-00055` (state cancel, origin MPP) supplier satirinda gorunmeye devam ediyor.
- Cozum: `get_supplier_summary` (po_by_seller + rfq_count + production satirindaki po), `get_rfq_preview` (existing_*), `_plan_summary` override (rfqs + rfq_count) artik `state == 'cancel'` PO'lari atliyor. Yeniden olusturma mantigi zaten sadece `draft`'a baktigi icin iptal sonrasi tekrar RFQ acilabiliyor (degismedi). Slot-bar `rfq_count` ve stored `rfq_count` tarihce oldugu icin ELLEMEDI (overwrite uyarisi guvenli tarafta kalsin). py_compile OK.
- JS-only: supplier satirindaki RFQ durumunda ham kod yerine rozet (`_rfqStateBadge`: Taslak mavi / Gonderildi+Onay Bekliyor turuncu / Onaylandi yesil; node --check OK). Deploy: Upgrade + Ctrl+F5 yeterli (Python yok).

## RFQ Satir Kapsama (Line Coverage) (2026-10-12, kodlandi - push/deploy BEKLIYOR)

- Istek (YILMAZER ornegi): para-birimi split'i normal (USD satir ayri RFQ); ama iptal RFQ'daki urun manuel baska RFQ'ya tasininca / RFQ'da miktar dusurulunce / RFQ->PO sonrasi iptal olunca sayfa algilamali; tum ihtiyac RFQ/PO'daysa buton cikmamali.
- Kapsam karari (kullanici): URUN bazinda, plana bagli TUM RFQ/PO'lar (seller/company fark etmez); sifirdan manuel PO sayilmaz.
- Yontem: `_rfq_coverage_map` (plan.py, @api.model) plana bagli iptal-disi PO satirlarini urun bazinda havuzlar (satir UoM'una `_compute_quantity`, cevrim-hatasi skip = guvenli yon; ayni urun cok satirdaysa havuz id-sirasiyla paylasilir, cift sayim yok); satir basi {covered, remaining}. `_rfq_groups` sadece remaining>eps satirlari alir, PO qty/subtotal/preview/chatter kalan uzerinden (top-up RFQ); `skipped`'e 'covered' sayaci. `get_supplier_summary` satira covered/remaining, supplier'a open/covered count ekler (toplamlar DEGISTIRILMEDI). JS: open==0 -> buton yerine yesil "Covered" rozeti; kismi -> buton + "x/y covered" notu; alt-satirda "covered"/"open N" mini bilgi (6 kolon hizasi korunur, Ingilizce plain).
- Dogrulama: `scratch/test_rfq_coverage.py` GERCEK metodu AST-exec ile kosar, 11/11 PASS (tam/kismi/iptal/manuel-tasima/miktar-dusumu/onayli-PO/UoM-cevrim/UoM-mismatch/havuz-paylasimi/not-satiri). odoo-reviewer: approve-with-nits (tek nit uygulandi: `display_type` sadelestirmesi — 15'te sadece False/section/note). `py_compile` + `node --check` OK.
- Kural: kapsama her zaman plan-linkli dokumanlardan hesaplanir (M2M); manuel PO plana baglanmadikca gorunmez. Deploy: Python var -> Git Deploy + restart (mesai disi + backup) + modul Upgrade + Ctrl+F5.
- GENISLETME (2026-10-12, m0143): yukaridaki "manuel PO gorunmez" kurali KALDIRILDI. `_rfq_coverage_map` artik iki kaynagi birlestirir: plana bagli PO'lar (tarih sinirsiz) + sifirdan manuel PO'lar (`purchase.order.line` global `search_read`: `order_id.date_order >= plan.create_date`, state != cancel, display_section/note haric; UoM'lar toplu browse). Tarih siniri sart: plan oncesi dokumanlar plan netting'ini ilgilendirmez, yoksa eski PO'lar ihtiyaci kapatir. Cift sayim engeli: globalde bagli PO id'leri atlanir. Satir `covered_by` (max 3   dokuman adi) tasir, JS "covered" notunda tooltip olur. Sim 15/15 PASS (manuel-po, covered-by, no-double, create_date-yok guard). Deploy degisikligi yok (ayni pencere).
 - TAKIP GORUNURLUGU (2026-10-12, m0153): tooltip YETMEDI; kapsayan dokumanlar alt-satir RFQs hucresinde dogrudan listelenir ("in: PO/26-00055, PO/MAN-1" + "+N more", tam liste title'da). Server `covered_docs [{id,name}]` (max 5) + `covered_total` doner (`covered_by` string kaldirildi); tiklama `_onOpenPo` ile PO formunu yeni sekmede acar (product_cost `_onOpenProduct` deseni). Isimler JS'te escape'li (reviewer notu). Sim covered-docs seklini dogrular, ALL PASS; `node --check` OK.
- RFQ BUTONU SAYFAYI YUKARI ATIYOR (2026-10-12, m0179, kodlandi - push BEKLIYOR): `_preserveSupScroll` vardi ama ETKISIZDI. Kok neden: widget root'un kendisi kaydirici (`overflow-y:auto`), fakat `_supScrollers` sadece `this.$(...)` (DESCENDANT arar) ile bakiyordu; class `$el`'in ustunde oldugu icin liste BOS kaliyor, gercek kaydirici hic kaydedilmiyordu. Cozum: `add(this.$el[0])` eklendi. Kemer+askı: Chrome scroll-anchor, tiklanan satir DOM'dan silinince basa sarmasın diye `.mpp-sup-body/.mpp-prod-body/.mpp-sup-cards`'a `overflow-anchor:none` (SCSS). SADECE static (JS+SCSS): `node --check` OK, scss brace-dengesi OK. Deploy: modul Upgrade + Ctrl+F5 yeterli, restart GEREKMEZ.

## Tedarikci Satir Acma Scroll-Jump (2026-10-12, kodlandi - push/deploy BEKLIYOR)

- Belirti: Uretim Plani Tedarikciler sekmesinde tedarikci satirina tiklayinca alt urunler aciliyor ama sayfa en uste kayiyor; kullanici elle asagi inmek zorunda kaliyor.
- Kok neden (2 katmanli): (1) `_onSupToggle` her tiklamada `_renderSuppliers` ile TUM tabloyu `html()` ile yeniden basiyordu -> tiklanan buton DOM'dan siliniyor, focus kayboluyor, tarayici basa zıpliyor; (2) `_preserveSupScroll` yalnizca widget koku + window'u sakliyordu, oysa Odoo 15'te gercek kaydrici `.o_content` (mobilde kok non-scrolling) -> koruma bosa gidiyordu.
- Cozum (JS/SCSS only): yerinde expand/collapse (tiklanan satirin altina `.mpp-sup-sub-row` ekle/kaldir, tam render YOK; satir bulunamazsa korumali tam-render fallback); `_supScrollers` (kok + closest `.o_content` + global `.o_action_manager .o_content` dedupe + window, scrollTop+Left); `_keepSupRowVisible` (`scrollIntoView` block:nearest = gorunurde no-op); focus `preventScroll` ile butonda kalir. a11y: `aria-expanded`/label senkronu (`_setSupRowOpen` + satir sablonu), tek tab-stop (klavye native button'da, isim span'i sadece mouse-click; onceki role=button denemesi cift-fokus diye geri alindi). SCSS: hover rengi, focus-visible cercevesi, `.mpp-sup-open` satir vurgusu.
- odoo-reviewer: blocker yok. TAKIP BORCU (yeni vektor degil, eski borc): supplier satir html'lerinde seller_name/currency/route/note kacissiz basiliyor -> `_.escape` genellestirmesi; yeni gorunen stringlerde `_()` yok (dosya borcu). `var self` hoisting + scrollLeft + aria-label Show/Hide senkronu uygulandi.
- Dogrulama: `node --check` OK, eklenen satirlarda TR-karakter 0 (case-sensitive tarama; eski tarama case-insensitive oldugu icin ASCII `i`'yi `İ/ı` sanip 92 yanlis-pozitif vermisti). Deploy: Python yok -> Upgrade + Ctrl+F5 yeterli.

## RFQ Update-Existing (2026-10-12, kodlandi - push/deploy BEKLIYOR)

- Istek: Suppliers sekmesinde eksik icin yeni RFQ yerine mevcut draft RFQ guncellensin (urun varsa qty artar, yoksa satir acilir).
- Eslesme anahtari grup anahtariyla birebir: `(seller, company, currency)` (`_rfq_find_updatable`); para birimi/sirket tutmazsa merge Odoo'da mumkun degil (PO basligi tek partner+currency+company) -> o grup icin yeni RFQ. Sadece `state == 'draft'` guncellenir; sent/onayli belgeye dokunulmaz, o gruplar yeni RFQ acar.
- Fiyat politikasi: mevcut PO satir `price_unit` KORUNUR (manuel pazarlik ezilmez), yeni satirlar plan snapshot'indan; UoM cevrim basarisizsa ham adet + warning log. `purchase_order_id/purchase_line_id` uzerine yazma cift sayim yapmaz (coverage urun-bazli okur).
- RPC geriye uyumlu: `mode` 5. pozisyonel arguman (default 'create'); `needs_confirm` + `updatable [{id,name,currency}]`, donus `updated + created`; preview'da grup bazinda `updatable_po`. JS'te Update RFQ (primary) + Create new (secondary); `pendingRfqUpdatable` state.
- Dogrulama: `py_compile` + `node --check` OK, yeni kod ASCII-temiz; odoo-reviewer kritik yok (2 dusuk oneri uygulandi: title escape, UoM log). Plan: `plans/rfq_update_existing.md`. Deploy: Python var -> Git Deploy + restart (mesai disi + backup) + Upgrade + Ctrl+F5. Manifest 15.0.2.8.0. Commit/push kullanici onayiyla.

## Supplier Sekmesi Iptal-Gorunurluk + Refresh Kaldirma (2026-10-12, kodlandi - push/deploy BEKLIYOR)

- Sikayet: RFQ iptal edilince Suppliers sekmesinde Rebuild/Refresh'e basilsa da iptal gorunmuyor, F5 gerekiyor.
- Kok neden: `_onRebuild`/`_onReload` basarisi `_applySummary` (supSummary=null) + `_renderTree` yapiyor ama `get_supplier_summary`'yi yeniden cekmiyordu; sekme 2'deyken `_renderSup` eski/bos veriyle kaliyordu. Sekme degisimi zaten lazy-fetch yapiyordu (`_onNavTab`), o yuzden F5 duzeltiyordu.
- Cozum (JS only): Rebuild basarisinda `activeTab === 2` ise once `_renderSup` (Loading) + `_fetchSupSummary` (slot save/load ile ayni desen). Server tarafi zaten iptali disliyordu (summary/coverage'da cancel skip) -> iptal sonrasi RFQ listeden duser, acik yeniden acilir, Create RFQ butonu doner.
- Refresh kaldirildi (kullanici karari): XML buton + events binding + `_onReload` silindi; repo capinda `mpp-btn-reload`/`_onReload` 0 hit. `_fetchStartup` oksuz degil (willStart kullaniyor). Rebuild tek buton; kirli-uyari kaybi yok (Rebuild zaten confirm'li). Bilinen onceki davranis (degismedi): `_onSlotChange` kirli needMap'i confirm'siz atar.
- Dogrulama: `node --check` + XML parse OK, yeni satirlar ASCII-temiz; odoo-reviewer kritik yok. Deploy: static-only -> modul Upgrade + Ctrl+F5 yeterli. Commit/push kullanici onayiyla.

## RFQ UoM Karisikligi — PO/26-00106 (2026-10-12, staging canli teyitli)

- Sikayet: LAPP RFQ'da 1 satir `m`, 6 satir `mm` (ekran goruntusu); neden hepsi ayni birim degil.
- Olcu: RFQ staging'de draft, origin=MPP (plan uretimi). 6 urunde kart `uom_id=mm` + `uom_po_id=m`; E1CBRN03'te ikisi de `m`. Tedarikci fiyatlari (supplierinfo) 7 urunde de `m` basina (0.23-2.13 EUR/m).
- Kok neden: plan satirlari stok UoM'unda calisir (`uom_id`, plan.py satir-build); RFQ uretimi PO satir birimi olarak plan satir birimini alir (`matia_procurement_plan_rfq.py` `_rfq_add_lines` + 2 uretim blogu: `line.uom_id.id if line.uom_id else ...uom_po_id`), `uom_po_id`'ye bakmaz. Stok birimi `m` olan tek urun tesadufen dogru cikar, `mm` olanlar mm satir acar -> karisik tablo + mm miktarlar (58090 mm = 58.09 m).
- Yan belirti: mm satirlarda `price_unit=0.00` (snapshot `_rfq_line_eff` plan-UoM'una cevrilir; RFQ acilirken last-buy henuz bos idiyse 0 yazilir ve mevcut satir fiyati korunur). Subtotal de 0 gorunur.
- Fix yonu (ONAYSIZ): RFQ satir acilirken urunun `uom_po_id`'si kullanilip miktar `_compute_quantity` ile cevrilmeli (ya da plan satir birimi satinalma birimine cekilmeli). Odoo standardi da PO satirinda `uom_po_id`'dir. Etkilenen mevcut RFQ'lar manuel duzeltilmeli (miktar/1000 + birim m + fiyat teyidi).
 - FIX UYGULANDI (2026-10-12, kullanici onayli, kodlandi - push/deploy BEKLIYOR): yeni helper `_rfq_po_line_vals(line, qty, price)` (`matia_procurement_plan_rfq.py`): PO satir birimi urun `uom_po_id`'si (yoksa satir/stok UoM), miktar + fiyat birlikte cevrilir (satir toplami degismez: 58090 mm x 0.00023 = 58.09 m x 0.23). Cevrim hatasinda eski davranisa fallback + warning log. 3 uretim noktasi (`_rfq_add_lines`, `action_create_draft_rfqs`, `action_create_supplier_rfq`) + preview'a `po_qty/po_uom(_id)/po_price` eklendi. Bump yolu degisiklige gerek duymaz (hedef UoM'a genel cevrim zaten vardi). Chatter plan-UoM'unda kaldi (BOM patlatmasi stok birimleriyle tutarli). Dogrulama: `py_compile` OK, `scratch/test_rfq_po_uom.py` 9/9 PASS (gercek fonksiyon AST-exec), odoo-reviewer APPROVE-WITH-NITS (2 nit uygulandi: preview UoM adi + `prod.uom_id` son fallback; kalan notlar: m yuvarlamasinda kurus kaymasi mumkun, grup subtotal plan-UoM bazinda kalir). Deploy: Python var -> Git Deploy + restart (mesai disi + backup) + modul Upgrade + Ctrl+F5. MEVCUT RFQ'lar (PO/26-00106 dahil) duzelmez - manuel duzeltme gerekir (miktar/1000, birim m, fiyat teyidi).

## RFQ/MO Sonrasi Rebuild Guvenligi + M1TRTN02 Olcumu (2026-10-12, canli teyitli, kod DEGIL)

- Draft RFQ/MO reserve yapmaz (Odoo 15 standardi): draft PO `stock.move` yaratmaz, draft MO confirm edilmeden bilesen ayirmaz. JS kaniti: `_onCreateRfq` sadece `supplier_summary` tazeler + `_renderSup` (`procurement_plan.js:2595`), Plan sekmesi agacina dokunmaz. Suppliers'taki "dusus" stok degil coverage top-up'idir (`remaining`).
- M1TRTN02 (id 1837, M4 Brass Insert): canli 17B lokasyonda 313 adet, her yerde reserved 0; plan satiri 7618 (gross 400, avail 313, net/order 19, subcontract, GUNES MAKINA, PO/MO linksiz); plan 1'de bagli PO/MO yok (`rfq_count` 0); tek PO satiri 2024'teki PO/24-00298 (200 adet) `plan.create_date` (2026-10-09) oncesi oldugu icin coverage tarafindan dogru sekilde yok sayilir. Son hareket 2026-05-06 sayim cikisi (4 adet). Snapshot == canli, su an sapma yok.
- Rebuild RFQ tarafi guvenli: coverage urun-bazli + `purchase_order_ids` M2M satir-unlink'ten sag cikar; top-up eslesmesi (seller, company, currency) korunur. MO tarafi GUVENSIZ: `action_create_mos` sadece `line.mo_id`'ye bakar, rebuild satirlari silip yeniden yaratir -> link kaybolur -> mukerrer MO riski. Cozum yonu: rebuild'de link snapshot + recreate sonrasi product bazinda geri yazma; MO yaratmadan once `origin=plan.name` + product ile mevcut draft/confirmed MO arama. Sayfa dondurma (freeze) onerilmez: kok sebebi cozmez, cok kullanicili/stale riski tasir.
- Prosedur: RFQ uretimi bitmeden Rebuild yok; Needed netlessin, tek Rebuild, sonra RFQ.

## Suppliers MO Bilesensiz + Cancel Olu (2026-10-12, staging WHTR/MO/26-00014, FIX kodlandi - deploy BEKLIYOR)

- Belirti: Suppliers sayfasindan MO acildi; staging MO-3411 (E2CBAN02, qty 31, BOM 1199, confirmed) `move_raw_ids=[]`, `move_finished_ids=[]`; Confirm sonrasi Cancel butonu hicbir sey yapmiyor.
- Kok neden: `action_create_mos` (matia_procurement_plan.py:4578) sadece header ile `mrp.production.create()` eder. Odoo 15 `create()` move uretmez (sadece `import_file` contextinde onchange cagirir); `action_confirm()` MEVCUT movelari confirmler, BOM'dan uretmez. `_action_cancel` moveless MO'da bosa duser (sondaki `state=done` write'i sadece `consumption == 'flexible'` BOM'da; 1199 `strict`), `_compute_state` moveless confirmed MO'da dal tutmaz -> state confirmed kalir (Cancel olu gorunur). Yani iki semptomun tek kok nedeni: API-create onchange'siz MO.
- Fix: create sonrasi `mo._onchange_move_raw()` + `mo._onchange_move_finished()` + `mo._onchange_workorder_ids()` (Odoo'nun kendi import_file deseni); MO draft kalir, kullanici Confirm eder. `py_compile` OK.
- Bozuk kayit onarimi (staging, MCP guard notlari): `state` ve `picking_type_id` readonly -> direkt write YOK; `execute_method` (orn. `_action_confirm`) unreviewed side-effect diye bloklu. Cozum: saglikli manufacture MO (3178) deseninde 7 `stock.move` create (6 raw: 1383x15500mm, 1425x62, 1449x124, 1597x3720mm, 1632x62, 1633x62 + finished 1160x31; WHTR/Stock(8)<->Production(15), group 3214, make_to_stock, warehouse 1; move id 49434-49440, draft). Move'lar varken UI Cancel calisir -> kullanici Cancel eder; `action_create_mos` cancel MO'yu "already linked" saymaz, deploy sonrasi ayni satirdan saglikli MO yeniden uretilir.
- Kural: API ile uretim belgesi acan her kod (MO/PO) UI onchange'lerini server-side tekrar cagirmali; move'suz confirmed MO hem uretilemez hem iptal edilemez. Deploy: Python var -> Git Deploy + restart (mesai disi + backup) + modul Upgrade + Ctrl+F5.

## Suppliers RFQ/MO Scroll-to-Top Fix (2026-10-12, kodlandi - deploy BEKLIYOR)

- Sikayet: Suppliers sekmesinde RFQ/MO tiklayinca sayfa en uste kayiyordu; onceki response-time `_preserveSupScroll` tutmadi. Butonlar `type="button"` (anchor degil), saga-ust popup mekanik sebep degil ama gozu yukari cekiyordu.
- Kok neden: RPC gidis-donus saniyeler surer + re-render tiklanan butonu yok eder; response aninda kaydedilen konum artik kayip.
- Cozum (JS only, procurement_plan.js): `_snapshotSupScroll` tik aninda senkron kayit; 4 handler'da (`_onCreateRfq/_onConfirmRfq/_onUpdateRfq/_onCreateMo`) preventDefault+stopPropagation, response'ta `_renderSup` + `_restoreSupScroll`, layout/bildirim sonrasi `_restoreSupScrollSoon` (rAF + isDestroyed guard); basari toast'lari kaldirildi (inline liste zaten gosterir), Forbidden/Already-exists/Skipped uyari + hata toast'lari duruyor. Denetim bulgusu (cift-tik mukerrer belge riski): tiklanan buton RPC bitene kadar `_lockSupBtn` ile kilitli, hata yolunda `_unlockSupBtn` acar; `_preserveSupScroll` try/finally.
- Dogrulama: `node --check` OK. Deploy: static-only -> modul Upgrade + Ctrl+F5.

## Plan Tek-Buton Release (2026-10-12, kodlandi - deploy BEKLIYOR)

- Kapsam: `matia.procurement.plan` `_inherit` + mail.thread (`models/matia_procurement_plan_release.py`); `release_state` draft/released/closed + `release_snapshot` (JSON: rev/user/rfq_ids/mo_ids/line_ids/ts) + `released_rev` + `needs_revision`; Release wizard (RFQ tarafi pure hesap, MO tarafi widget-secimli) -> `action_create_draft_rfqs` + `action_create_mos` cagirir; Takip wizard (TransientModel satirlar, attention badge, secili draft RFQ confirm, Yenile).
- Kilit: `write()` guard target_json'u released/closed planda engeller; Action: set hedefleri dener -> plan "revize icin acildi" sonuc karti + `action_unrelease` (RFQ/MO silinmez). PO iptal/silme watcher (`purchase_order_mpp_watcher.py`, best-effort flag + chatter, engelleme yok) -> needs_revision.
- MO dedup: ayni origin+product+company'de iptal-olmayan MO varsa `action_create_mos` yeniden uretmek yerine relink eder (`relinked` key; eski satirda `_rfq_coverage_map` rebuild sonrasi link kaybi = mukerrer MO riski vardi). JS sayac `created+relinked`.
- Pure helperlar stdlib-only `models/mpp_release_common.py` (line_tracking_status + snapshot builder); reviewer uyarilari kapatildi (view'da release_state readonly, chatter USER-env, confirm= yikici butonlarda).
- Deploy: Python var -> Git Deploy + servis restart (mesai disi + öncesi backup) + modul Upgrade. Version 15.0.2.9.0.

## Release Staging 500 + _name Hotfix (2026-10-12, staging, cozuldu - v15.0.2.9.1)

- Belirti: CloudPepper update+restart sonrasi staging Internal Server Error; /xmlrpc/2/common version + TUM /object cagrilari 500 (canli saglikliydi).
- Kok neden: `MatiaProcurementPlanRelease` sinifi `_name` OLMADAN liste-form `_inherit` (['matia.procurement.plan','mail.thread']) kullaniyordu; Odoo sinif adinda golge (shadow) yeni model kurup tum stored alanlari (purchase_order_ids M2M, relation matia_proc_plan_po_rel) aynen kopyaladi -> ayni tablo+kolon carpismasi -> registry hic kurulamadi (traceback setup_models/setup_nonrelated asamasi). KURAL: liste-form `_inherit` kullanan her sinifa explicit `_name = 'matia.procurement.plan'` yaz (tek satirlik _inherit string formu bu riske girmez).
- Duzeltme: explicit _name + NOTE comment + manifest 15.0.2.9.1; commit 655b359 push'landi; DB kirlenmesi YOK (hata memory registry fazinda, upgrade DB yazamadi). Ilk push denemesi GitHub 'fatal error in commit_refs' verdi, retry tuttu.
- Teshis sirasi: MCP config saglam mi (list_instances/health_check) -> canli saglikli mi (evetse sorun hedefe ozel) -> panel logundaki traceback'i TAM oku.

## Release E2E Staging (2026-10-12, plan 30, 17/17 PASS - v15.0.2.9.1)

- Script `scratch/e2e_release.py --staging --apply` (stdlib xmlrpc): T0 deploy+baseline, T1 wizard preview (399 acik satir) + confirm -> rev2 (34 RFQ + 119 MO), snapshot==belge eslesmesi, chatter yazar dogru; T6 cift-tik engelli; T3 rebuild kilitli; T5 cancel -> needs_revision + chatter; T4 sever+re-release rev3 relink (WHTR/MO/26-00017, newMO yok); tracking probe 960 satir/193 attention; cleanup: 35 test PO cancel+unlink, 119 test MO unlink -> plan 30 bazinda (62 PO, 3 MO, draft, rev=3 sayaci kaldi - zararsiz).
- Odoo quirk (bizim kod DEGIL): standart `purchase.order button_cancel` None doner -> odoobulut XML-RPC 'cannot marshal None' Fault verir; Fault response'ta olur, cancel COMMIT olur. Test: Fault tolerate et + state re-read ile dogrula.
- Script dersleri: execute_kw'de args/kwargs POZISYONEL (`[ids]` tek katman; cift katman 'unhashable list'); transient `create(vals)` default_get'i BYPASS eder -> wizard'lari `[{}]` + `{'context': {'default_plan_id': ..}}` ile ac; snapshot created/updated/relinked girdileri dict (id+name+...) -> karsilastirmada id cikar.
- Bilinen aciklar (plana gore): released'da eski satir-butonlar gizlenmiyor (sadece yeni butonlarda attrs); §2.3 revizyon-delta akisi yok (unrelease duz kilit-acma); §2.7 gelismis takip kodlari yok (sadece baz status); 2 bos-body mail.message (sebebi belirsiz, minor).

## Release Upgrade ParseError + Stale-View Cleanup (2026-10-12, staging, cozuldu - v15.0.2.10.1)

- Belirti: staging Upgrade (`button_immediate_upgrade`) ParseError: `procurement_plan_views.xml` yuklenirken combined-arch'ta `action_open_release_wizard is not a valid action`. Lokal dosyada o buton YOK (77 satir, temiz) + repo grep temiz -> sorun DB'deki bayat kayit.
- Kok neden: silinen `procurement_plan_release_views.xml`'in 4 view'u (form_release inherit + tree_release inherit + 2 wizard formu) staging DB'de duruyordu; base form view reload'da `_inverse_arch` combined-arch'i bayat inherit ile birlestirip silinen metoda takildi. Odoo silinen dosya kayitlarini upgrade SONUNDA temizler, o faza gelinemedi. Basarisiz upgrade transactional -> DB kirlenmesi YOK (modul eski versiyonda kaldi).
- Duzeltme: `views/procurement_plan_release_cleanup.xml` (search-tabanli 4x `<delete>`, fresh install'da no-op) manifest data sirasinda view dosyasindan ONCE; commit a55f299. KURAL: inherit view iceren XML dosyasi silinirse, ayni upgrade'te once `<delete>` cleanup sart (dosya silmek yetmez).
- Not: CloudPepper checkout dizinindeki `6ab5064b9c4d3` bizim git SHA degil (ic dusum isimlendirme); icerik fb8d495 ile eslesiyor (metod yok + dosya yok).

## Release Upgrade KeyError + Orphan-Selection SQL Cleanup (2026-10-12, staging, duzeltme push'landi - v15.0.2.10.2)

- Belirti: view fixinden sonraki Upgrade `_process_end` fazinda `KeyError: 'matia.procurement.plan.tracking.line'` (`ir_model.py _process_ondelete` -> `self.env[selection.field_id.model]`).
- Kok neden: silinen 4 transient modelin `ir.model.fields.selection` satirlari DB'de kalmis; GC onlari ORM ile unlink etmeye kalkinca registry'de olmayan modeli cozup patladi. `<delete>` ayni sebeple ise yaramazdi (o da ORM unlink kullanir).
- Duzeltme: cleanup XML'e `<function model="matia.procurement.plan" name="_cleanup_release_transient_selection_rows"/>` + helper raw-SQL DELETE (JOIN ir_model_fields, 4 model adi sabit liste; fresh install'da 0 satir). KURAL: registry'den silinen modele ait DB satiri ORM ile silinemez -> once SQL ile kir, sonra upgrade GC'si devam eder.
- Kaynak dogrulama: `github_search_code` ile odoo/odoo `ir_model.py::_process_ondelete` ("Process the 'ondelete' of the given selection values") teyit edildi.

## Release Dashboard Contract Bug (2026-10-12, lokal duzeltme - push/deploy BEKLIYOR)

- Belirti: staging'de Release sekmesi "Draft RFQs (0) / No open supplier lines" gosterdi, oysa ayni planda `get_release_preview(30)` 81 grup + 846 satir donuyordu (MCP kaniti). Kullanici "bir sey olmadi" sandi.
- Kok neden: JS-RPC sozlesme uyusmazligi. JS `_releasePreviewHtml` `p.groups[]` (name/line_count/total_usd/action) + `p.mo_eligible[]` bekliyordu; server `group_count` + flat `lines[]` donuyor, `groups`/`mo_eligible` hic kurmuyordu -> `|| []` ile hep bos render. Ayni sinif hata tracking'de: JS `plan_state`/`product`/`po_name` okuyor, server `release_state`/`product_name`/`rfq_name` donuyordu (urun kolonu bos, RFQ belgesi '-', closed "Released" gorunuyordu).
- Duzeltme: server `get_release_preview` `_rfq_groups` + `_rfq_find_updatable` ile `groups[]` (name: seller (currency/company), line_count, total_usd: grup parabiriminden USD'ye `_convert` + try/except fallback, action: create/update) ve `mo_eligible[]` kuruyor; JS tracking anahtarlari `release_state`/`product||product_name`/`po_name||rfq_name` fallback'li + preview ozet satiri (`p.summary`) eklendi. KURAL: her yeni dashboard RPC'te JS'in okudugu anahtarlarla server'in dondugu anahtarlar birebir karsilastirilir (unit test yok, sozlesme gozle tutulur).

## Capacity Denetim Paketi (2026-10-12, branch fix/capacity-audit-2026-10-12, 3 commit - deploy BEKLIYOR)

- §0 sayi-kaniti (staging, salt-okunur): E2CBAN03 (product 1901) -> TR 5/0 (WHTR/Stock/OTS 21B), US 0, NCR 0 => avail 5+0=5 (A1/A2). Plan 30 (released rev 6) satir 112753: make, order 39, MO 3820 (origin MPP, qty 39) bagli, PO yok (A3/A6; coverage'da make satiri PO uretmez - A4). Snapshot rev 6: user/date + rfq{created 81 PO, skipped make:125/zero:109}/mo{created 120} (A5/A7). A8 no_need server'da dogru.
- Kararlar: group_user ACL 1,0,0,0 guvenli (JS'te direkt ORM write/create/unlink YOK, tum akislar sudo'lu metoda gider); watcher closed'u da izler (closed'dan unrelease acilabiliyor); copy() slot'u -1'e ceker (slot cakismasi yok); A6 dedup anahtarina UoM eklenmedi (satir UoM'u zaten stok UoM'una normalize); A7 yari-release (snapshot write try disinda) kodla kapatilmadi - savepoint ister, raporun "atlanan" hanesinde.
- KURAL: `_t()`'ye asla degisken gecirme (hasatci statik string ister) - label map'leri switch+literal yaz; release kilit mantigi `_isLockedState` tek kaynagi; sudo kayit uzerinden message_post YASAK (user-env browse deseni).
- Ek tarama (2026-10-12, ayni branch): `_avail_total` total yoksa TR+US toplar (once yalniz TR'ye dusuyordu, US sessiz kayboluyordu); form `line_ids` kilitli planda readonly (satir bypass'i kapandi); 6 tooltip `_t()`'ye alindi (parcali-birlestirmeli 4 tooltip + product_cost.js kapsama disi birakildi).
- Kapanis kararlari (2026-10-12, kullanici onayli): A7 yari-release (RFQ/MO olusur, kilit write'i patlarsa belgeler ortada kalir) kodla kapatilmadi - write 3 kucuk alan yaziyor, patlama olasiligi dusuk; **bilinen risk** olarak birakildi, savepoint tasarimi ayri is. C6 kapatildi: kilit mantigi `_isLockedState` tek kaynaginda, 3 sekmedeki sunum bilerek ayri (tek-bar birlestirme regresyon riski > gorsel kazanc). product_cost.js'ye dokunulmadi: dosyadaki `no _t` yorumu (satir 16-17) bilerek konmus proje karari (kisa kelimeler core cevirilerle cakisiyor); tooltip sarmak bu karara aykiri olurdu.
- Bug taramasi (2026-10-12, push sonrasi): B5 (group_user read-only) non-admin PO iptalinde watcher flag'ini sessizce olduruyordu (try/except yuttugu icin crash yok ama `needs_revision` hic yazilmiyordu; satin almacilar genelde admin degildir). Cozum: watcher flag write + chatter'i sudo browse uzerinden yapar, yazar yine islemi yapan kullanici kalir (sudo env.user'i degistirmez). RFQ/plan `line.write` akislari admin-guard'li veya sudo'lu oldugu icin B5'ten etkilenmez; fiyat override'lari sudo'lu. KURAL: ACL kisitladiginda tum user-env write'larini tara (watcher/observer sinifi RPC disi tetiklenir, guard'siz calisir).
- Taze-goz taramasi (2026-10-12): web_quote anon hata cevabinda exception metni sizdiriyordu (SQL/yol izi) -> log'a yazilir, API'ye genel mesaj doner. Revise dialogu sebep almazdi (B10 server'da vardi, UI'da yoktu) -> metin kutulu Dialog eklendi, chatter'a duser. Temiz: tracking kodlari (11 kod) <-> JS etiket map'i birebir eslesir; export route'lar auth=user+POST; manifest sira dogru; Odoo 15 yasak desen (env.sudo/list/privilege_id/Constraint/bare-except) yok; export_popup jQuery .text() ile XSS-guvenli.

## Plan 3 Kart-Toplam Farki: Satirsiz Phantom Top Sizintisi (2026-10-13, canli salt-okunur)

- Sikayet: plan 3 kartlar retained_total_usd=136714.14 vs supplier grand_total_usd=138241.99 (fark +1527.85 supplier lehine).
- Teshis (scratch/diag_plan3_diff.py + 4 takip sorgusu, sifir write - plan write_date 06:17:05 tum cagrilar oncesi/sonrasi ayni): 959 satir (855 siparisli), 970 override, unknown=0, make(order>0)=123 (grand disi, dogru), duplicate product 0, satir/override staleness 0 (plan sonrasi write yok), built_target_json==target_json (get_tree_with_cost cached dal, rebuild YOK).
- Kok neden STRUCTURAL (stale degil): girilmis top N2PGAN02 Packaging Kits (pid 1244, want=55) plan satiri OLMAYAN tek hedef/edge urunu; BOM 1715 phantom (yaninda 1600 normal de var). 6 cocugu (N1PGRN08/02/07/26/27 + N1FTTR05, hepsi tek-ebeveynli yaprak) netlerini _mpp_net_costs dongusunde yukari iter; 1244 satirsiz oldugu icin retained hicbir satira yazilmaz, ebeveyni de yok (edge kok) ve dagitilacak pushed pay bosa duser - 6 cocugun tam neti (supplier toplami 1527.90) kart disinda kalir. Kodun cent-esitlik iddiasi (_mpp_net_costs docstring) satirsiz top durumunda YANLIS.
- 5 cent artik: get_supplier_summary grand tutari tedarikci-basina roundlanmis ara toplamlardan toplar (kod satir 4460 + 4524) - tedarikci basina +-0.5c kayma; 1527.90-1527.85=0.05 buradan gelir.
- KURAL: hedef girilen her urunun plan satiri olmali; satirsiz top (ozellikle phantom) kart toplami disinda sessiz deger birakir. Fix yonu: _compute_rollup satirsiz pid payini No-line grubuna raporlamali veya hedef toplara satir acilmasini sart kosmali. Gecici cozum (ONAYLI ISLEM GEREKIR, staging yok): N2PGAN02 hedeften cikarilip cocuklari dogrudan girilirse kartlar grand ile esitlenir.

## N2PGAN02 OK Rozeti + Location-BOM Fix (2026-10-13, lokal duzeltme - push/deploy BEKLIYOR)

- Sikayet: N2PGAN02 satiri TR=0 US=0 Producible=0 Needed=55 iken Planned hucrede yesil OK rozeti; ayrica urunun Prices location'i US iken 2 BOM'dan hangisinin kullanildigi belirsizdi.
- Duzeltme 1: `get_tree_with_cost` satir dict'inde `net` satirsiz toplarda 0.0 gidiyordu -> JS `_rowNet` 0 alip OK basiyordu. Fix: satirsiz top `net = max(0.0, need - avail)` (ustteki `planned` ile ayni ifade; `get_full_tree` fallback niyetiyle tutarli). JS degisikligi YOK; N2PGAN02 artik Planned=55 gosterir, alt-BOM acilimi da 55 uzerinden calisir.
- Duzeltme 2: yeni `_mpp_resolve_bom(env_sudo, pid, tmpl_id, overrides, cache)` yardimcisi. Location'suz pid'lerde eski sorgular birebir (siralama eklenmedi, sifir davranis degisikligi); location'li pid'de once variant+company sonra sablon+company (`order='id'`; sablon aramasi `product_id=False` filtreli, kardes varyant BOM'u karisamaz), bulunamazsa eski sorguya duser. 9 noktada SADECE location eslesmezliginde devreye girer: explode, `_mpp_net_costs`, `_bom_of`, `get_sub_bom_cost`, `get_full_tree`/`search_tree` `_kids_bom`, `get_price_overview` BFS, `_mpp_search_kit_forest`, product_cost `_mpc_explode`. Degismeyenler: 4 sabit kit BOM, has_bom boolean'lari, MO `_normal_bom`, kit-siniflandirma, stock_planning.py.
- Canli teyit (2026-10-13, salt-okunur): 1715 VE 1600 ikisi de phantom + template-level (product_id=False), sadece company farkli (1715=US/2, 1600=TR/1). Onceki girdideki "1600 normal" notu YANLIS - duzeltildi. 1244 override location='us' oldugundan helper sablon+company ile 1715'i deterministik secer (eski sans-sirasi da fiilen 1715 donduruyordu -> plan sayilari degismez).
- Reviewer: KRITIK yok (deploy proseduru haric: Git Deploy/restart + backup, mesai disi); 4 DUSUK nottan biri uygulandi (sablon+company `product_id=False` filtresi), digerleri kenar-durum bilgi notu.
- KURAL: ayni sablonun birden fazla company-BOM'u varsa secim location'suz durumda DB sansina kalir; Prices location'i olan urunlerde `_mpp_resolve_bom` deterministik company-BOM secer. Yeni BOM-secimi yazan her yere helper kullanilir, cift `search limit=1` kopyalanmaz.

## Satirsiz Phantom Top: Karti Esitleyen Satir Fix'i (2026-10-13, lokal duzeltme - push/deploy BEKLIYOR)

- Onceki girdideki "No-line grubu veya hedef topa satir sarti" kararinin uygulamasi: kullanici "cocuk maliyetleri base'e eklensin + N2PGAN02 Est. USD dolsun" istedi; cozum satir acmak oldu (ayri grup gerekmedi).
- Fix A (explode, phantom dali): `pid in targets` ise need'e yazilir -> satir acilir; ara phantom'lar eski yolda (satirsiz, pass-through). Fix B (`_mpp_net_costs`): `phantom and p not in want` ise want_w=0, yoksa want (hedef+component uclusu vida ornegiyle ayni exact-partition). Ek: `_mpp_need_per_top` tooltip hedef-phantom'a self-entry (`N2PGAN02x55`).
- Neden base'e otomatik duser: `_plan_summary` satirlari `_kit_of` ile toplar; 1244 sabit kit BOM'unun dogrudan satiri oldugundan base grubuna +1527.90 isler, kart 138242.04 ~= grand 138241.99 olur.
- Guvenlik matrisi (canli salt-okunur teyitli): 1244 route Manufacture(6)+purchase_ok=false -> satir make; make own_usd HER ZAMAN 0 (override bile reddedilir) -> supplier cift sayim YOK (ayrica PO gecmisi 0 -> last_price 0). MO: normal-BOM yok (1715+1600 ikisi de phantom) -> `mo_creatable=False` + toplu uretimde `No normal-type BOM found` skip, exception YOK. Simulasyon: retain(152790,want=55,push=0)=(152790,0) - kokte eski kural da ayni sonucu verirdi (tot=0 -> retain-all); sizinti satir yoklugundandi (`_compute_rollup` 2519-2543 sadece `line_by_pid`'e yazar), Fix B uclu durumu duzeltir.
- Reviewer: KRITIK yok; DUSUK 1 (tooltip onarildi). py_compile temiz. Deploy: Git Deploy/restart + backup, mesai disi (button_immediate_upgrade Python yuklemez).

## RFQ Liste JS Race (2026-10-14, purchase.order tree view 1745)

- Belirti: action 572 (Requests for Quotation, context quotation_only=True, zorunlu view 1745 purchase_order_kpis_tree) listesinde sayfalar arasi dolasirken `FieldWrapper.updateModifiersValue: Cannot set properties of null (setting 'props')` (_applyModifiers/_registerModifiers zinciri).
- Teshis (salt-okunur): tree'de custom inherit YOK, ir.ui.view.custom 0, Studio kurulu degil (customization/dashboard/reporting_studio uninstalled); view stok Odoo. Supheli agir widget'lar: date_order remaining_days + cift invisible (attrs state'e bagli + invisible not quotation_only), activity_ids list_activity, user_id avatar, state badge. purchase 15.0.1.2 kurulu, server 15.0-20240109.
- Kok neden adayi: hizli sayfa degisiminde satir yeniden render'i onceki bitmeden modifiers uygulamasi (Odoo PR #101419 sinifi race; 15.0'da bu view'da raporlanmaya devam ediyor). DB/veri sorunu DEGIL, frontend render yarisi.
- Gecici cozum: sayfa tam yuklenmeden Sonraki/Onceki'ye basma; liste sutun seciciden Activity + avatar sutunlarini gizle; Ctrl+F5 + gizli pencerede test; RFQ-disi Purchase listesinde karsilastir. Kaliciysa odoobulut minor update (mesai disi + backup).

## Capacity Modulu — RFQ Liste Hatasi Elendi + Tek Sizinti (2026-10-14)

- Suphe: RFQ liste JS race'i capacity modulunden mi geliyor. Testler: `node --check` 4/4 OK, `py_compile` 8/8 OK; JS'te ListRenderer/FieldWrapper/ActionManager `.include/.extend/patch` YOK (dashboard'lar kendi tag'li `AbstractAction.extend`, event'ler widget kokune scoped; `export_popup.js` sadece cagrilinca calisir); `views/`'ta purchase inherit YOK (sadece kendi plan formunda `purchase_order_ids` M2M + satirda `purchase_order_id`); canlida purchase tree inherit 0 (uc stok tree 1744/1745/1746); `purchase_order_mpp_watcher.py` field eklemez (sadece `button_cancel`/`unlink` sonrasi best-effort flag) -> liste read/render'ina dokunamaz. Yetim `purchase.order.limit_200` (id 4302, xml_id'siz, form order_line limit=200) bizim modulden degil, liste degil form etkiler -> elendi.
- TEK GERCEK SIZINTI: `stock_planning.scss:7-29` kok disi global CSS (`.o_action_manager/.o_main_content/.o_action/.o_view_controller` overflow/touch-action `!important`, mobilde `overflow:visible/height:auto`) `web.assets_backend` ile HER sayfaya (RFQ listesi dahil) yuklenir. FieldWrapper `props` null hatasini aciklayamaz (CSS, JS props'a yazmaz) ama modulun satinalma sayfasina uygulanan tek kodudur. Fix yonu (ONAYSIZ): blogu `.o_matia_stock_planning/.o_matia_procurement_plan/.o_matia_product_cost` altina scope'la; static-only -> modul Upgrade + Ctrl+F5.
- Dolayli vektor: workers=2 + agir plan RPC'leri (Expand All/export) sunucuyu yavaslatir, hizli sayfa tiklamada race'i tetikler. Gecici: buyuk plan islemi bitmeden RFQ listesinde hizli sayfa degistirme.


## TR Stok Sayim Listesi Patlatmasi (2026-10-15)
- 4 kit BOM (1766/1736/1737/1738) 125 direkt satir; variant-oncelikli BFS depth<=10 ile 960 tekil urun (467 ebeveyn alt-BOM'lu). TR Stock ID 8 alti 149 internal lokasyon (NCR 333 + Subcont 19 ve alt agaclari haric), qty>0 olan 525 urun, 529 quant satiri. Cikti: scratch/tr_stock_exploded.json + scratch/tr_stock_print.html (A4 landscape, kod/urun/depo/miktar). Script: scratch/explode_tr_stock.py (toplu BOM yukleme, yerelde patlatma).
- US esdegeri (2026-10-15): ayni 960 patlatma; WHUS/Stock ID 26 alti sadece 2 internal lokasyon (26 + Spare 331; NCR 332 haric, US'te subcontract lokasyonu yok), qty>0 olan 166 urun, 287 quant satiri. Cikti: scratch/us_stock_exploded.json + scratch/us_stock_print.html. Script: scratch/explode_us_stock.py.

## Capacity Sayfasi — Sayim Listesi Butonlari (2026-10-15)
- Refresh yanina 2 buton (TR Sayim Listesi / US Count List); tiklayinca yeni sekmede yazdirilabilir HTML + Print/Excel butonlari. Veri: `matia.stock.planning.get_count_sheet('tr'/'us')` — kit bulma `_mpp_find_kit_boms`, patlatma variant-oncelikli BFS depth<=10 (variant BOM cache pid-anahtarli, template BOM tmpl-anahtarli), stok `stock.quant` read_group grup `[product_id, location_id]` (seri/lot quant'lari lokasyonda birlesir, qty>0), sira depo>kod>ad. Lokasyon: WHTR/Stock* / WHUS/Stock* internal, NCR + adinda Subcontract gecen haric. TR: Units->Adet; US: aynen.
- Route'lar (auth=user, salt-okunur): GET `/matia_stock_planning/count_sheet/<tr|us>` (QWeb `views/count_sheet_templates.xml`) + GET `.../<tr|us>/xlsx` (xlsxwriter varsa .xlsx yoksa BOM'lu CSV). Dosyalar: `controllers/count_sheet.py`, manifest version 15.0.2.10.7.
- Kapsam notu: stoku olan ara montajlar da listelenir (scratch 525/166 sayimlariyla ayni kural); basliktaki "en alt seviye" patlatma derinligini ifade eder, yaprak-only DEGIL.
- Deploy: Python degisikligi -> `button_immediate_upgrade` YUKLEMEZ; odoobulut Git Deploy + servis restart, mesai disi + oncesi backup. Once staging-matia'da dene.

## RFQ Birlestirme 138+139+140 -> PO/26-00142 (2026-10-15)
- 139'daki 4 urun 138'de de vardi (farkli miktar): rev2 update-modu manuel PO'yu (138) guncelleyemeyip yeni RFQ (139) acmis. Toplamlar 35'e tamamliyordu (29+6, 5+30, 5+30, 25+10). Birlestirme = ayni (urun,uom,fiyat,vergi) grubunda TOPLAMA; fiyat/vergi/aciklama farki olsaydi ayri satir kalacakti (script abort kurali). 140'taki M3MTMN05x34 138'de yoktu, aynen eklendi.
- Sonuc: PO/26-00142 (draft, Matia Demo placeholder, 149 satir); kaynaklar 138/139/140 cancel (silinmedi). Chatter'da birlesme + Murat Gunes earmark notu (1771x34). Dusus (trim) taslak uzerinde UI'dan.
- XML-RPC gotchalari (scratch/mpp_merge_pos.py): message_post [[id]] + kwarg body ister (dict pozisyonel Fault verir); button_cancel None doner -> marshal Fault'a ragmen cancel UYGULANIR, state search_read ile teyit et; --finish=<id> modu yarim kalan isi tamamlar.

## RFQ Chatter Eski->Yeni Miktar Notu (2026-10-16)
- Istek: update-modunda RFQ'ya eklenen/artan her parca icin PO chatter'ina eski->yeni bilgisi. Mevzubahis `_rfq_bom_chatter` zaten 3 noktada cagriliyordu (update `_rfq_add_lines` + 2 create-path) ama sadece delta miktari yaziyordu.
- Cozum (commitlenmedi, local): `_rfq_add_lines` `_qty_info {plan_line: (old|None, new, po_uom)}` toplar (bump'ta write-oncesi `_old_po`; yeni satirda `_po_line.product_uom.name`); `_rfq_bom_chatter(..., qty_info=None)` bump'ta `(was 6, now 40 Units)`, yeni satirda `(new: 34 Units)` basar. Create-path cagrilari qty_info gecmez -> ciktisi degismez. odoo-reviewer: kritik bulgu yok. py_compile OK.
- Deploy: Python degisikligi -> Git Deploy + restart (mesai disi + backup); `button_immediate_upgrade` YUKLEMEZ.

## Bootstrap Sadelestirme (2026-10-18)

- Silinenler: scripts/start-opencode.ps1, scripts/launch_opencode_desktop.ps1, scripts/setup_new_machine.ps1 (V2 + makine tasima tamamlandi, Desktop User env MATIA_* dogrudan goruyor).
- Kalan: load_env.ps1 (terminal .py failover ODOO_* icin), check_mem0.ps1, lint_error_log.ps1. .env/.env.example ODOO_* semasinda kaldi (MCP artik MATIA_* User env kullaniyor).
- Kural: yeni baslatma/yeni-makine scripti ekleme; referanslar AGENTS.md/AI.md/rules.md/check_mem0/load_env/.env.example'dan temizlendi.

## MATIA_* Env Birlesmesi (2026-10-18)

- ODOO_*/ODOO_STAGING_* artik kullanilmiyor; her sey MATIA_ODOO_*/MATIA_ODOO_STAGING_* (User env, 11 anahtar). .py helper'lar (smoke_after_deploy, trigger_module_upgrade) MATIA_* okur.
- Silinen: scripts/load_env.ps1 (.env yukleyiciye gerek kalmadi). .env/.env.example anahtarlari MATIA_*'a cevrilidi (.env git-ignored yerel yedek).
- opencode.json'daki ODOO_URL/ODOO_DB/... KEY'ler odoo-mcp paketinin bekledigi girdi adlaridir, DEGISTIRME (value'lar {env:MATIA_*} ile eslenir).

## Mail Giden/Gelen Teshisi (2026-10-19, salt-okunur)

- Giden: tek server `odoogmail` (id 6, smtp.gmail.com:587 STARTTLS, user enes@matiamobility.com) `use_google_gmail_service=True` ile OAuth kullaniyor. `mail.mail`: exception 104 / sent 3 / outgoing 0. Son 30 exception dagilimi: 17x TR + 4x EN access-token hatasi + 9x "Connection unexpectedly closed" — Gmail OAuth refresh kirik, fallback SMTP de tutmuyor.
- Gelen: `fetchmail.server` 0 kayit — gelen kutusu yapilandirilmamis. Cron "Mail: Fetchmail Service" aktif ama islevsiz. Catchall domain matiamobility.com + alias reply-odoo + bounce bounce + default.from notifications mevcut.
- Cron "Mail: Email Queue Manager" 1 saate ayarlı — kuyruk cok yavas bosalir, mailler gecikmis gorunur. Oneri: OAuth'u Google Cloud Console'da teyit edip yeniden yetkilendir (veya App Password'e gec), Queue Manager araligini dusur, gelen icin fetchmail kaydi ac. Secret token'lar loglanmadi.

## Mail Cozumu Teyidi (2026-10-19, canli)

- Giden OAuth 11:11'de yenilendi (expiration ileriye alindi), test maili gitti.
- Gelen `fetchmail.server` id 7 `gmailgelen` (imap.gmail.com, enes@matiamobility.com) kuruldu, state done, son cekme 11:17:41. Reply `mail.message` 80876 (11:13:27, res.partner 1118, email tipi) chatter'a dustu.
- Ders: gelen maili `partner_ids` domain'iyle arama YANILTIR (email tipi partner_ids tasimayabilir); dogru sorgu `model + res_id` (ornek: res.partner 1118).

## PO Torna Paketi Tasima 142->146 (2026-10-20, canli, uygulandi)

- PO/26-00142 (id 537, 149 satir, Matia Demo) -> PO/26-00146 (id 541, MAKSAN CNC, bostu): Excel listesindeki 70 satirdan 66'si tasindi (adet 142'den, fiyat Excel'den; M3S2TN04=85; 142'de olmayan M3L2TN23/M3T2TN05/M3U2TN01 atlandi). 146: 66 satir, 275680 TRY + KDV 330816; 142: 83 satir kaldi (693674.35 total). Chatter notu iki PO'ya dusuldu.
- Kural: prod `odoo_matia` MCP write kapali (`ODOO_MCP_ENABLE_WRITES=1` yok) -> tasima direk XML-RPC ile (`scratch/po_move_142_146.py`, dry-run + --apply; once create+dogrula, sonra unlink+dogrula). Sira: uyumsuzluk raporu + kullanici karari (dup fiyat, atlanan 3 kod, fiyat=Excel) -> ic test (validate/preview) -> onay -> uygula -> MCP ile capraz dogrula.

## PO Freze Paketi Tasima 142->147 (2026-10-20, canli, uygulandi)

- PO/26-00142 (83 satir kalmisti) -> PO/26-00147 (id 542, Uzmanlar Kalip, bostu/draft): UZMANLAR KALIP.xlsx 46 satir, liste TEMIZ (cift yok, eksik yok, 46/46 142'de; hepsi Units + %20 KDV). 147: 46 satir, 836805 TRY + KDV 1004166; 142: 37 satir kaldi (252621.55 total). Betik `scratch/po_move_142_147.py` (onceki 146 betiginin 147 uyarlamasi). NOT: M3MTMN05 142 chatter'inda Murat Gunes'e ayrilmisti, bu tasimayla Uzmanlar'a gecti (chatter notuna yazildi).

## Purchase Form FieldWrapper Crash (2026-10-20, aralikli)

- Hata: `purchase.order` formda `FieldWrapper.updateModifiersValue → Cannot set properties of null (setting 'props')` (field_wrapper.js: `this.componentRef.comp.props = this.props`, comp=null = ic Owl field henuz mount olmamis / destroy edilmisken modifier uygulanmis; Odoo 15 core race, `_registerModifiers` yolu).
- Tetikleyiciler: UI view `purchase.order.limit_200` (ID 4302, 2024-11-01, xml_id yok, `order_line/tree limit=200`) + cok-satirli PO'lar (PO/26-00138 148 satir cancel, PO/26-00142 83 satir merge-kokenli, PO/26-00146 67 satir; 15-20 Eki 2026) + debug assets modu + sunucu bellek baskisi (%70-85, workers=2).
- `matia_stock_planning` DISLANdi: purchase view inherit YOK, JS core patch YOK (sadece 3 action_registry kaydi), watcher backend-only (button_cancel/unlink). Buyuk PO'lar `bsi_merge_any_purchase` merge kokenli (origin `Merge of ...`), plan RFQ degil.
- Kalici mitigasyon (refresh degil): gunluk calismada `?debug=assets` birak; limit_200 deaktif edip Odoo default 40+pager'a don (tek tik, reversible).

## Staging A/B A-fazi NEGATIF (2026-10-20)

- Staging `PO/26-00351` (id 746, 150 satir, RACE-TEST, draft) limit_200 AKTIFKEN browser'da cokmedi. 150 satir tek basina her sunucuda yetmiyor.
- Prod `purchase.order`'da custom `x_` field YOK (82 field, tamami standart); base form 83 field, 14 attrs'li (order_line + satir field'lari dahil).
- Kalan hipotezler: (1) timing/yuk — prod yavas (mem %70-85, workers=2, debug assets) staging hizli; (2) veri-bagimli — crash belirli state/partner/kur kombinasyonunda; test PO'su duz draft'ti; (3) uzun-acik-sekme oturumu. Sonraki adim: crash anındaki PO id'si + debug modu not edilecek.

## Count Sheet Bos Sayfa — read_group lazy Bug (2026-10-21, kok neden bulundu + fix kodlandi, deploy BEKLIYOR)

- Sikayet: `/matia_stock_planning/count_sheet/us` (TR de ayni) bos cikiyor. Modul canlida guncel (15.0.2.10.7), route + QWeb template saglam; `get_count_sheet` her iki sirket icin `Products: 0` donuyor.
- Kok neden: `get_count_sheet` (stock_planning.py) `stock.quant`'i `['product_id','location_id']` cift groupby ile okuyor ama `lazy=False` vermiyordu. Odoo 15'te `read_group` default `lazy=True` ile SADECE ilk groupby'yi doner (`location_id` satirda YOK, `__context.group_by=['location_id']` dusulur); kod `rg.get('location_id')` bos olunca `continue` ile TUM satirlari atliyor -> `prod_locs={}` -> bos sayfa. Canli veriyle teyit: ayni domain `lazy:true`'da satirlarda `location_id` anahtari yok, `lazy:false`'ta var (WHUS/Stock 327 quant, 23155 adet mevcut).
- Moduldeki diger 6 `read_group` tek groupby'li (`['product_id']`) oldugu icin saglam; cift groupby kullanan TEK cagri buydu.
- Fix (commit BEKLIYOR): ayni cagriya `lazy=False` eklendi (`py_compile` OK). Kural: 2+ groupby'li her `read_group`'a `lazy=False` yaz; tek groupby'da default yeterli.
- Deploy: Python degisikligi -> odoobulut Git Deploy + servis restart (mesai disi + backup) + modul Upgrade; sonrasi `/us` ve `/xlsx` ile teyit.

## Count Sheet Type Sutunu (2026-10-21, kodlandi + pushlandi 1d5828c, deploy BEKLIYOR)

- Istek: Main/Sub ayrimi + `Main > location > code` siralama, baslik Type.
- `get_count_sheet` urun basina en sig patlatma seviyesini tutar (`pid_level`, min-seviye; birden fazla kit/seviyede gecen urun en sig seviyeyle Main kalir): seviye 0 = `Main Part`, digerleri `Sub Part` (`is_main` + `type_label`). Siralama `(main-once, location, code, name)`.
- Sutun Adi/Urun arasina geldi: TR baslik `Tür`, US baslik `Type` (TR sayfa Turkce kuralina uyuldu). HTML + xlsx + CSV 3 cikti da tasir (xlsx genislik 12).
- Manifest 15.0.2.10.7->15.0.2.10.8. Dogrulama: `py_compile` + XML parse + siralama simulasyonu OK.
- Deploy: Python var -> Git Deploy + restart (mesai disi + backup) + Upgrade.

## Count Sheet 4 Sekme + Lot Sutunu (2026-10-21, kodlandi + pushlandi 07228af, deploy BEKLIYOR)

- Sekmeler: Stok TekRMD (4 BOM, Main/Sub + siralama aynen) / Stok Diger (stokta ama 4 BOM disi) / NCR (sirketin NCR'i, BOM-bagimsiz) / Spare (sirketin spare'i, BOM-bagimsiz). Sekmede sayac, yazdirma gorunen sekmeyi basar, Excel butonu aktif sekmeyi indirir (`/xlsx/<scope>`, eski `/xlsx` tekrmd'ye gider).
- Spare isimle eslesir (`'Spare' in cname`): tasma oncesi Stock/ altinda da sonrasi kardes konumda da calisir, hicbir durumda stock kapsamına girmez (cift sayim yok).
- Lot/Seri sutunu 4 listede var (virgulle ayrık, kucuk punto `.lot`): tek `read_group(product,location,lot, lazy=False)` + qty>0 filtresi; satir basi distinct lot adlari.
- Lokasyon taramasi (2026-10-21 canli): Stock/NCR/Spare disinda tek internal konum `Physical Locations/Subcontracting Location` (TR, 208 quant, ~212k adet, fasoncu stoku - bilerek disarida). Arsiv disi tum internal konumlar Stock agacinda; kapsanmayan stok yok.
- Manifest 15.0.2.10.8->15.0.2.10.9. Dogrulama: `py_compile` + XML parse + kapsam/lot simulasyonu OK.

## Count Sheet Lazy Lot Hatasi (2026-10-21, canli 500, fix pushlandi a77ba4e, deploy BEKLIYOR)

- Hata: upgrade sonrasi butonda Internal Server Error. Canli traceback: `get_count_sheet stock_planning.py:928 lot_text join -> TypeError: sequence item 0: expected str instance, lazy found`.
- Kok neden: `read_group` `lot_id` adi lazy ceviri nesnesi donebiliyor; `', '.join` str ister. Diger groupby adlari (`product_id/location_id`) yalniz `[0]` ile okundugu icin etkilenmedi.
- Fix: lot adlari toplanirken `str(lot[1])`. Kural: `read_group`'tan gelen m2o display adini join/sort'ta kullanmadan once `str()`'e cevir.
- `py_compile` OK. Deploy: Python var -> Git Deploy + restart + Upgrade.

## Count Sheet Lot Miktar + US Ingilizce UoM (2026-10-21, pushlandi 4c30779, deploy BEKLIYOR)

- Lot sutunu: `LOT (miktar)` formatinda satir-bazli lot toplamlari; miktar 1 ise parantez yok (`LOT-A (8), LOT-B, LOT-C (2.5)`); birim yazilmaz (Quantity sutununda var). `_disp_qty` helper (tam sayi->int, degilse 2 ondalik) toplam + lot icin ortak.
- US sayfalarinda `Adet` sizintisi bitti: US'te `_UOM_NAME_MAP` ile EN'e cevrilir (Adet->Units, Takim->Set...), TR davranisi aynen (Units->Adet).
- Dogrulama: `py_compile` + format simulasyonu OK.

## Upgrade "Updating"de Takilma (2026-10-21, canli olcu)

- Sikayet: upgrade updating'de kaldi. Olcu: `ir.module.module` state=`installed`, installed=latest=`15.0.2.10.8`; `get_count_sheet` eski sekilsiz (lists yok) ama 166 US satir donuyor (lazy fix canlida calisiyor).
- Yorum: DB yari-upgrade'de DEGIL; sunucudaki kod henuz .10.8 (4-sekme .10.9 deploy'u panele ulasmamis veya restart suruyor). UI'daki "updating" muhtemelen deploy/restart sirasinda tetiklenen upgrade cagrisi.
- Kural: state `installed` iken tekrar tekrar Upgrade'e basma (paralel upgrade kilitlenir); once panelde Git Deploy durumunu bekle, sonra tek Upgrade. 166 satir eski kodun saglikli calistigini gosterir.

## PO Murat Gunes Paketi Tasima 142->149 (2026-10-22, canli, uygulandi)

- PO/26-00142 (37 satir kalmisti) -> PO/26-00149 (id 544, Murat Gunes, bostu/draft): MURAT GUNES listesi 34 satir, TEMIZ (cift yok, eksik yok, 34/34 142'de; hepsi Units + %20 KDV). 149: 34 satir, 1047850 TRY + KDV 1257420; 142: 3 satir kaldi (M3T2TN04, M1TRTN01, M3U2MN08; 3081.77 total). Betik `scratch/po_move_142_149.py`.
- DERS: toplam onayi icin el-hesabi qty dict ASLA kullanma (2 adet hatasi 1149550 vs dogrusu 1047850 verdi: M3E2MN08 77 degil 38, M3C2MN06 76 degil 34); her zaman canli `search_read` qty ile hesapla + tutmazsa uygulamadan once farki bul ve kullaniciya duzelt.

## PO Subcontract Auto-Register (2026-10-26, kodlandi - deploy BEKLIYOR)

- Sorun: PO/26-00146 (Maksan 1299, 68 satir) onayda fason MO/resupply uretmedi; tek receipt Vendors->Stock. Kok neden TEK: 67 subcontract BOM'da `subcontractor_ids`=[1088,1240], 1299 yok. Bilesen rotalari tamam (42/42 `[5,9]`); bitmis-urun rotasi iddiasi YANLISTI (fason akista rota komponentte olur, plans/ + Route-vs-BOM girdisine bak).
- Cozum: `models/purchase_subcontract_auto.py` (`purchase.order` inherit): `button_confirm` `super()` ONCESI `_msp_ensure_subcontract_vendors` calisir; fason BOM'lu satirlarda tedarikci `[(4, vendor)]` ile eklenir (mevcut korunur, variant BOM `product_id` filtresi var). Best-effort: hata purchase akisini bloklamaz (warning log). Manifest 15.0.2.10.10. Plan: `plans/subcontract_auto_add.md`.
- Kural: Odoo fason BOM secimini onay aninda yapar; onay-sonrasi automation ayni PO'yu kurtaramaz. Eski PO'lar (146 dahil) icin backfill + iptal/yeniden olusturma gerekir.
- Deploy: Python var -> Git Deploy + restart (mesai disi + backup) + modul Upgrade. Commit/push kullanici onayiyla.

## PO 146 Fason Onarimi (2026-10-26, canli, BASARILI)

- Yontem (kullanici uyguladi): PO/26-00146 button_cancel -> button_draft -> button_confirm.
- Sonuc: eski receipt 4121 cancel, yeni receipt 4123 assigned; 67/67 BOM'a 1299 eklendi (otomasyon `button_confirm` oncesi calisti); 67 fason MO (WHTR/SBC/..., confirmed, picking_type Subcontracting); 67 resupply teslimat (WHTR/RES/..., Stock -> Subcontracting Location). 1869 M1TRTN01'de BOM YOK -> dogru sekilde MO'suz normal alim satiri.
- Kural teyidi: bitmis-urun rotasi fason akisi etkilemez (40 urunde [5] olmasina ragmen MO uredi); belirleyici olan BOM `subcontractor_ids` eslesmesi + komponent route 9.
- Kapsam: 056+ onayli PO'larda baska bozuk yok (tarama: 50 PO + taslaklar). 045 (Maksan, Mayis) teslimatlari done oldugu icin kapsam disi birakildi.
- Script: `scratch/po146_subcontract_fix.py` (kuru-kontrol + --apply, Fault-tolerant).

## Batch Belge No Otomatik Kopyalama (2026-10-26, staging kuruldu + test PASS)

- Sorun: RES transferleri (Resupply Subcontractor, sequence RES, orn. WHTR/RES/..)
  `document_number` bossa dogrulamada "belge no giriniz" uyarisi; batch'teki Studio
  alani `x_docno` (modules bos, Doc No) elle Actions > "Belge No Kopyala" (id 1243,
  TUM pickinglere yazar) ile kopyalaniyordu (2 tik).
- Cozum Adim 1 (Studio, deploy'suz): `base.automation` id 10
  "Batch Belge No -> Hazir Transferler" (staging): on_write, model
  stock.picking.batch (1901), filter `[('x_docno','!=',False)]`, state code.
  `x_docno` strip edilip SADECE `assigned` pickinglere `document_number` yazilir
  (dolu uzerine yazilir, kullanici karari); bos docno sessiz gecilir. Plain dongu
  (safe_eval'de lambda yok). Tek `base.automation` create yeterli (delegate ile
  server action otomatik acilir); MCP sirasi preview -> validate -> execute
  (direkt execute token-hatasi verir).
- Test (staging BATCH/00002, Validate YOK): 4357 assigned -> `document_number`
  "asfdasd" doldu; 4358/4356 confirmed bos kaldi (PASS). Batch'te 2 confirmed
  varken Dogrula zaten cekirdek "waiting for goods" hatasi verir (availability
  oncelikli); once Check Availability + confirmed temizligi gerekir.
- Revizyon (2026-10-26, kullanici istegi): Dogrula tum RES'lerin belgesini
  kontrol ettigi icin kapsam genisletildi: `assigned` yerine `done`/`cancel`
  haric TUM pickingler (dolu uzerine yazilir). BATCH/00002'de 3/3 doldu (PASS).
- Teshis notu: "hic miktar rezerve/yapilmamis" hatasi belgesiz transferden DEGIL,
  satirsiz transferden gelir (`button_validate`: `move_line_ids` bos veya sifir
  olan picking patlar). Ornek: 4357'de 1 satir vardi (625 rezerve, 300 done
  girilmis - dogru), 4356/4358'de HIC satir yoktu (confirmed, rezerve hic
  olusmamis -> satir olusmaz -> done girilecek yer de yok). Cozum: bekleyenleri
  batch'ten cikarip sadece hazirlari dogrula (stok yoksa Check Availability de
  ise yaramaz).
- Adim 2 (KODLANDI + review OK 2026-10-26, commit/deploy BEKLIYOR,
  `plans/batch_docno_autocopy.md`): `models/stock_picking_batch_docno.py`
  (`action_done` override + `_msp_copy_docno_to_pickings`, `_fields` guard'li,
  best-effort + `_logger.exception`); manifest 15.0.2.10.11 + depends
  `stock_picking_batch`; `py_compile` OK; odoo-reviewer KRITIK YOK.
  Deploy sonrasi Studio otomasyonu pasiflestirilir (cift yazim onlenir).
- Prod'a tasima: Studio UI'dan birebir kayit (ID ortama ozel olabilir).
