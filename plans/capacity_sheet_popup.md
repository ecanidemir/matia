# Plan: Tek Popup Excel (Capacity dahil birleşme)

Tarih: 2026-10-08 | Durum: UYGULANDI (commit yok, push yok — kullanici push'lar) | Kapsam: popup export
(`export_popup.js` + 3 çağırıcı) ve `procurement_export.py` + `main.py`.

Uygulama notu (2026-10-08): adimlar aynen uygulandi (capacity_sheet.py helper,
live capacity + capacity_only + mod-bazli kapi, popup 3. kart + preselect +
canExportAdmin, 3 cagirici, manifest 15.0.2.7.0). Test:
scratch/test_capacity_popup_export.py 35/35 YESIL + test_combined_export.py
34/34 regresyon temiz; py_compile + node --check OK. Tek sapma: karar 3'teki
`get_my_capacity_targets()` kodda YOK (revert 4905308, staging outage) —
live yol opsiyonel `capacity_targets` payload listesini ayni sanitize
kuraliyla alir, varsayilan standart sutunlardir (detay kodda _live_capacity
NOTE + docs/discovery.md "Capacity Sheet Popup" girdisi).

Hedef: Prices CSV'si hariç TÜM Excel butonları aynı popup'ı açar, aynı
işi yapar. Capacity sayfasının Excel butonu da popup'a dönüşür; bugünkü
doğrudan indirme davranışı sıfır regresyonla korunur.

## Kullanıcı kararları (soruldu, onaylandı)

1. **Kapsam:** slot'lardan bağımsız **tek global Capacity sheet**
   (Cost sheet gibi; stok anlık değerdir, slot'a göre değişmez).
2. **İçerik:** Capacity sayfasının **birebir aynası** — grup başlıkları
   (Base/Outdoor/Seat/Screws), Part Code/Name, On Hand, Producible,
   20 Devices Needed kolonları.
3. **Dinamik sütunlar:** export'u alan kullanıcının **kayıtlı hedef-cihaz
   sütunları** sheet'e dahil (`get_my_capacity_targets`).
4. **Birleşme (sonradan onaylandı):** Capacity sayfasındaki Excel butonu
   doğrudan indirme yerine **aynı popup'ı açar**. Hiçbir şey seçilmeden
   Export'a basılırsa bugünkü dosyanın aynısı iner (sıfır regresyon).
   Prices sayfası kapsam DIŞI (CSV export olarak kalır).
5. **İçerik bağlama göre değişir (sonradan onaylandı):**
   - Capacity sayfasından YALNIZCA Capacity seçildiyse → ekranda ne
     görülüyorsa o (birebir ayna: açık sub-BOM'lar dahil, **şuandaki gibi**).
   - Plan sayfasından popup açılıp Capacity istenirse → BOM'lar kapalı
     (yalnızca üst seviye) + standart sütunlar + o kullanıcının kayıtlı
     hedef-cihaz sütunları (live server hesabı).

## Mevcut desen (aynen tekrar kullanılacak)

- Cost sheet akışı: `_live_cost()` (server-side live veri) →
  `_append_cost_sheet(workbook, data)` → sheet sırası Cost önde →
  CSV fallback'te `_prepend_cost_csv`. `cost_slots` modu slot sheet'lerini
  toplar, Cost opsiyoneldir; `cost_only` modu tek sheet indirir.
- Popup: `export_popup.js` paylaşımlı picker (Suppliers + Product Cost
  kartları + slot listesi); `onExport(sel, withSup, withCost)` imzası.
  İki çağırıcı var: `procurement_plan.js:1665` (plan sayfası) ve
  `product_cost.js:903` (Cost sayfası).
- Capacity sayfası export'u (`main.py::export_xlsx`): client
  `stock_planning.js::_onExportExcel` `{headers, groups:[{cells}]}` post'lar;
  server bu şekli yazar (grup renkleri, OK/need/number/text hücre tipleri,
  sub-BOM seviye girintisi).

## Uygulama adımları

### 1. Capacity sheet writer'ını paylaşılır hale getir (server)

- `main.py`'daki sheet yazan blok (satır ~117-260: başlık + grup +
  hücre döngüsü) **ortak helper'a çıkarılacak**. Öneri: yeni küçük modül
  `controllers/capacity_sheet.py` içinde
  `write_capacity_sheet(workbook, ws, headers, groups, filter_info)` —
  hem `main.py` hem `procurement_export.py` import eder.
  (`main.py`'dan import da olur ama yön bağımlılığı temiz tutmak için
  ayrı modül önerilir.)
- CSV karşılığı: `main.py`'daki `csv_lines` bloğu aynı şekilde
  `capacity_csv_lines(headers, groups)` olarak çıkarılacak
  (xlsxwriter yoksa fallback için).

### 2. `procurement_export.py`: live capacity + sheet ekleme

- `_live_capacity()` (mirrors `_live_cost`):
  ```python
  cap = request.env['matia.stock.planning']
  targets = cap.get_my_capacity_targets()   # export'u alan kullanıcının sütunları
  data = cap.get_capacity_planning_data(dynamic_targets=targets)
  ```
  `get_capacity_planning_data` zaten `dynamic_targets` parametresi alıyor
  ve item başına `dynamic_needs` üretiyor — popup tarafında ek hesap YOK.
- Server verisini writer şekline çevir: `headers` =
  `['Part Code', 'Part Name', (Usage?), 'On Hand...', ..., 'Producible Devices',
  '20 Devices Needed', '<t> Devices Needed'...]` + `groups` =
  `[{key, title, items:[{cells:[{val,type}], is_sub, level}]}]`.
   Dönüşüm için client'taki `_buildExportCells` mantığı server'a taşınır
   (OK/need/number/text tipleriyle).
- **İçerik kuralı (bağlama göre, kullanıcı kararı):**
  - **Ekran yolu (Capacity sayfası, yalnızca Capacity):** client mevcut
    ekran payload'unu post'lar, server **olduğu gibi yazar** — açık
    sub-BOM satırları DAHİL, `is_sub` filtresi YOK (bugünkü davranışın
    aynısı, aynı writer).
  - **Live yol (Plan veya Cost sayfasından Capacity):** server live hesaplar
    (`_live_capacity`), sub-BOM'ları ASLA genişletmez (yalnızca üst seviye
    = BOM'lar kapalı hali) + export'u alan kullanıcının kayıtlı hedef-cihaz
    sütunları. Standart sütunlar.
  Ortak writer `level` parametresini desteklemeye devam eder — ekran yolunda
  girintiler korunur, live yolda level hep 0 gelir.
- `_append_capacity_sheet(workbook, data)` (mirrors `_append_cost_sheet`),
  sheet adı: `'Device Capacity'` (adı planda sabitlendi; istenirse değişir).
- Sheet sırası: **Product Cost → Products → Suppliers → Device Capacity
  (en sonda)**. Gerekçe: mevcut sıralamaya dokunmaz, ek en az sürprizlidir.
- `_capacity_suffix(data)` dosya adına `_Capacity` ekler
  (mirrors `_cost_suffix`).
- CSV fallback: `_prepend/append_capacity_csv` (mirrors `_prepend_cost_csv`).
- `cost_slots` akışı: `withCapacity` bayrağı slot toplama döngüsüne girer;
  slot sheet'leri + Cost + Suppliers aynen kalır, Capacity en sonda eklenir.
- **Yetki (birleşme için ŞART):** bugün `export_xlsx`
  (`procurement_export.py`) blanket `base.group_system` istiyor, oysa
  Capacity sayfası herkese açık (`main.py`: sadece `auth='user'`). Plan:
  **mod-bazlı kapı** — `capacity_only` modu `base.group_user`'a açık
  (salt-okunur capacity verisi zaten herkese görünür); diğer tüm modlar
  `group_system` istemeye devam eder. Slot/Cost/Suppliers verisi
  non-admin'e sızmaz.
- **Capacity-only modu (ekran-aynalı):** Capacity sayfası popup'tan
  `mode='capacity_only'` post'lar ve yanına **mevcut ekran payload'unu**
  ekler (`{headers, groups, filter_info}` — bugünkü `_onExportExcel`
  payload'unun aynısı: arama filtresi, gizli gruplar, toggle'lar,
  kayıtlı dinamik sütunlar, AÇIK sub-BOM satırları dahil). Server bunu
  ortak writer ile tek `Device Capacity` sheet'i olarak **olduğu gibi**
  yazar — `is_sub` filtresi uygulanmaz. Böylece seçim yapılmadan
  Export = bugünkü dosya (birebir aynı writer, aynı payload).
  Dosya adı `Device_Capacity_<tarih>.xlsx` (CSV fallback aynı adla .csv).
- **Payload'suz `capacity_only` (diğer sayfalar):** Plan veya Cost
  sayfasından slot'suz + yalnız-Capacity gelirse ekran payload'u yoktur;
  server live hesaplar (yukarıdaki live yol: üst-seviye + kayıtlı
  sütunlar). Aynı mod adı, iki giriş — ayrım payload varlığına göre.

### 3. Capacity sayfası butonu popup'a dönüşür (`stock_planning.js`)

- `_onExportExcel` doğrudan POST yerine önce slot listesini okuyup
  `ExportPopup.openExportPopup` açar (çağırıcı deseni `product_cost.js:901`
  ile aynı; `get_slot_list` RPC'si — non-admin okuyabilir mi uygulama
  sırasında doğrulanacak, okunamazsa boş slot listesiyle devam edilir).
- Popup'ta **Capacity kartı öntanımlı seçili** gelir (bu sayfanın bağlamı).
- `onExport` seçime göre post'lar:
  - Yalnızca Capacity (slot yok) → `mode='capacity_only'` + ekran payload'u.
  - Slot da seçildiyse (admin) → `mode='cost_slots'` + `withCapacity` +
    ekran payload'u (Capacity sheet ekrandaki haliyle, slot sheet'leri
    server'dan).
- **Admin kartı gizleme:** non-admin popup'ta Suppliers/Cost/slot kartlarını
  görmemeli (server zaten reddeder ama boş kart kafa karıştırır). Desen
  hazır: `can_create_docs` bayrağı gibi, slot-listesi RPC'sine veya küçük
  bir `get_export_caps` çağrısına `can_export_admin`
  (caller env `has_group('base.group_system')`) eklenir; popup `opts`
  ile kartları gizler. Server guard yine de mod-bazlı kalır (client
  gizlemesi güvenlik değildir).

### 4. Popup UI (`export_popup.js`, paylaşımlı — tek yer)

- Üçüncü kart: `'Device Capacity', 'Live capacity sheet as a separate sheet'`
  (ikon önerisi `fa fa-battery-three-quarters` veya `fa fa-tachometer`;
  class `mpp-exp-cap`).
- `opts.preselectCapacity` eklenecek: Capacity sayfasından açılışta Capacity
  kartı öntanımlı seçili gelir; diğer iki sayfada seçisiz (bugünkü davranış).
- `opts.canExportAdmin === false` ise Suppliers/Cost/slot bölümü
  gösterilmez (yalnızca Capacity kartı + Export).
- `onExport(sel, withSup, withCost, withCapacity)` — imza 4. parametreyle genişler
  (üç çağırıcı da güncelleniyor; geriye uyumluluk sorunu yok).

### 5. Üç çağırıcı (`procurement_plan.js`, `product_cost.js`, `stock_planning.js`)

- `onExport` callback'leri 4. parametreyi alıp payload'a
  `withCapacity: withCap` ekler.
- `product_cost.js:908-924` validasyon güncellemesi:
  `if (!sel.length && !withSup && !withCost && !withCap) return;`
   slot'suz + yalnız-Capacity → `mode='capacity_only'` post'lar
   (**payload'suz varyant**: Cost sayfasında ekran payload'u yok, server
   live hesaplar — karar 5, live yol; mevcut `withSup` uyarısı +
   `_onExportExcel` legacy dalı korunur).
- Plan sayfası çağırıcısında aynı validasyonun karşılığı kontrol edilir
  (slot'suz + yalnız-Capacity aynı `capacity_only` moduna gider —
  bu durumda ekran payload'u plan sayfasında olmadığı için server
  capacity'yi live hesaplar + o kullanıcının kayıtlı sütunlarıyla;
  yine yalnızca üst-seviye satırlar, sub-BOM genişletme yok).
- `stock_planning.js`: bkz. Adım 3 (buton → popup, ekran payload'lu post).

### 6. Doğrulama (uygulama sonrası)

- `py_compile` (3 controller dosyası) + `node --check` (3 JS).
- Scratch testi (desen: `test_combined_export.py` gibi stub-odoo ile gerçek
  modülü yükleme): writer-şekil dönüşümü (server item → cells tipleri),
  sheet sırası, `capacity_only` dosya adı, CSV fallback satır sayısı.
  Hedef: tam yeşil olmadan commit yok.
- Manuel: popup'ta Capacity kutusu → 4 sheet'li dosya; Capacity-only →
  tek sheet; başka kullanıcı (farklı kayıtlı sütun) → kendi sütunları;
  Capacity sayfasında sub-BOM AÇIKKEN yalnızca-Capacity export → sub
  satırlar DOSYADA VAR (ekran aynası); Plan sayfasından Capacity →
  sub satır YOK (BOM-kapalı live yol).

## Deploy

- **Python değişikliği VAR** → Git Deploy + **restart (mesai dışı + öncesi
  backup)** + modül Upgrade + Ctrl+F5. Commit/push kullanıcı onayıyla.

## Riskler / açık noktalar

1. **Writer çıkarma riski (ana risk):** `main.py` bloğunun ortak helper'a
   taşınması Capacity sayfası export'unu da etkiler — imza aynı şekli
   aldığı için davranış değişmemeli; scratch test + manuel Capacity export
   kontrolü şart.
2. **Performans:** `get_capacity_planning_data` tam orman okur (mevcut
   Capacity sayfası zaten her açılışta çağırıyor); popup export'ta +1 çağrı
   kabul edilebilir. Üst-seviye satır sınırlaması (BOM-kapalı kuralı) yükü
   zaten düşürür.
3. **Yetki (birleşme kapısı):** `export_xlsx`'e **mod-bazlı kapı** konur —
   `capacity_only` `base.group_user`'a açık, diğer tüm modlar `group_system`
   istemeye devam eder. Non-admin'in admin kartlarını görmemesi için
   `can_export_admin` bayrağı eklenir (client gizlemesi destektir, güvenlik
   server guard'dadır). `get_slot_list` RPC'sinin non-admin erişimi
   uygulama sırasında doğrulanacak.
4. Tahmini büyüklük: **küçük-orta (yarım–1 gün)**; desenin tamamı mevcut,
   yeni icat yok.
