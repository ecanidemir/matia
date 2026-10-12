# Plan: Tek-Buton Release Sistemi (RFQ + MO, snapshot'lı, hata-g geçirmez)

Tarih: 2026-10-12 | Kaynak vaka: staging plan 30'da PO/26-00114 → MO onayları → rebuild → PO/26-00116 top-up sürprizi
Hedef: **eksik veya fazla satınalma** ve **mükerrer/eksik MO** oluşumunu prosedürle değil **yapıyla** engellemek.

## 1. Kök neden (kanıtlı)

- `action_explode_and_net` her rebuild'de satırları `unlink()` + canlı avail'den yeniden yaratır (`avail=max(0,oh-rs)`).
- PO onayı avail'e dokunmaz (sadece incoming move); **MO onayı** bileşenleri rezerve edip avail'i düşürür.
- RFQ ve MO butonları ayrı, sıra serbest, aralara rebuild girebiliyor → MO sonrası rebuild order'ları büyütüyor (staging'de 6/1/2/14 adet kanıtlandı).
- Rebuild satır-seviye bağları koparır (`line.purchase_order_id=False`, `mo_id` kaybı) → "Create MO" tekrarına basılırsa mükerrer MO.
- Plan RFQ iptali coverage'ı sessizce geri çeker (69 vakası) → ihtiyaç "hortlar".
- Mevcut doğru çalışan parça: `_rfq_coverage_map` (ürün-bazlı) + `_rfq_groups` (sadece remaining) + `_rfq_find_updatable` (sadece draft'a ekler). Bunlar korunacak.

## 2. Karar: tek "Yayınla (Release)" butonu + snapshot + state machine

Kullanıcı önerisi onaylandı — en sağlıklı yöntem budur. Gerekçe: hata, sıralama özgürlüğünden doğuyor;
özgürlük kalkınca hata sınıfı ortadan kalkar. Uyarı dialog'ları ikinci savunma hattıdır (kliklenip geçilir).

### 2.1 Plan state machine (`matia.procurement.plan`'a yeni alan)

- `release_state`: `draft` → `released` → `closed` (selection, `tracking=True`, default `draft`).
  - `draft`: bugünkü serbest çalışma (rebuild/RFQ/MO butonları aktif).
  - `released`: snapshot damgalı. Bireysel RFQ/MO butonları + Rebuild **kilitli** (yerine Revizyon akışı).
  - `closed`: tüm release belgeleri onaylı + mallar geldi (veya manuel kapatma). Salt görüntü.
- `release_snapshot`: `fields.Text` içinde JSON — release anındaki her ürün için
  `{product_id, gross, avail, reserved, order, covered, remaining}` + **önerilen belge satırları**
  (`proposed_rfqs: [{supplier, product, qty, currency}]`, `proposed_mos: [{product, qty}]`)
  + `release_date` + `released_by`.
  (Odoo 15'te JSON alanı yok; Text + `json` modülü yeter. Ayrı snapshot modeli ilk fazda GEREKSİZ — sade tut.
  Önerilen satırlar §2.7 Takip sayfasının "olması gereken" tarafıdır — manuel düzeltme/bölme sapması ancak bunlarla ölçülür.)
- `release_doc_ids`: many2many/computed ile release'te yaratılan PO + MO listesi (checklist için).

### 2.2 "Yayınla" wizard'ı (tek buton, `TransientModel`)

Buton: plan formunda `action_open_release_wizard`. Wizard adımları (tek ekranda önizleme + onayla):

1. Dahili taze rebuild (sessiz, snapshot amaçlı — kullanıcı rebuild'e basmaz, sistem basar).
2. Önizleme: tedarikçi × ürün × miktar tablosu (RFQ taslakları) + yaratılacak MO listesi (taslak).
   Kaynak: mevcut `get_supplier_summary` + `_rfq_groups` + `action_create_mos`'un hesap kısmı — YENİ hesap yazma, mevcutları çağır.
3. Onay → AYNI snapshot'tan: tüm RFQ'ları (draft) + tüm MO'ları (draft) yarat → snapshot'ı damgala →
   `release_state='released'` → plan chatter'a özet post et.
4. MO'lar bilinçli olarak **draft** yaratılır (shop-floor onayı insanda kalır); RFQ'lar draft (fiyat/pazarlık insanda).
   Eksik-onay riski checklist ile kapatılır (bkz 2.4), otomatik confirm YOK (muhasebe/üretim etkisi insansız verilmez).

### 2.3 Revizyon akışı (release sonrası değişiklik ihtiyacı)

`released` planda Rebuild/RFQ/MO butonları yerine tek buton: "Revizyon İste".
- Sistem canlı avail'den yeniden hesaplar, snapshot ile karşılaştırır, **delta + gerekçe kodu** gösterir:
  - `reservation` (planın kendi MO/RFQ rezervleri neden oldu — örn. 116'daki 6/1/2/14),
  - `demand` (hedef değişti), `stock` (sayım/giriş-çıkış), `coverage` (belge iptal/onay).
- Kullanıcı gerekçeyi görüp onaylarsa YENİ revizyon satırları + sadece delta için ek RFQ/MO taslağı yaratılır;
  sebep `reservation` ise ek uyarı: "114'ün malları gelmeden onaylama".
- Revizyon da snapshot'lanır (snapshot JSON'a `revisions: [...]` eklenir) — denetim izi tam olur.

### 2.4 Release checklist (eksik belge avcısı)

Plan formunda `released` iken checklist sekmesi: her release belgesi + durumu
(draft RFQ / purchase / done; draft MO / confirmed / done) + doğrudan link.
Plan, tüm belgeler `purchase|done` + `confirmed|done` olana kadar `released` kalır;
eksik onay varsa üstte uyarı bandı. Böylece "unutulan RFQ/MO" (eksik alım/üretim) ekranda bağırır.

### 2.5 MO dedup (mükerrer MO sigortası)

`action_create_mos`'a ekle: yaratmadan önce `mrp.production`'da
`origin == plan.name (+company)` ve `product_id` ile ara; varsa yaratma, mevcut MO'ya bağlan
(`line.mo_id` geri yaz). Bu, link kaybı (rebuild) durumunda bile çift MO'yu engeller.
Aynı koruma RFQ tarafında zaten var (`_rfq_find_updatable` + coverage skip) — dokunma.

### 2.6 RFQ iptal bekçisi

`purchase.order`'da plan-bağlı (`plan_id`/`purchase_order_ids` üzerinden) RFQ iptal/silme girişiminde:
engelleME (operasyonu kitleme), ama plan chatter'ına "coverage düştü, Revizyon gerekli" post et +
planı `released` → revizyon-bekler bayrağına düşür. Odoo 15: `button_cancel` override veya
`unlink` override + `message_post` (plan `mail.thread` ise — değilse ekle, bkz 3.3).

### 2.7 Takip sayfası (önerilen vs gerçekleşen — tedarikçi bazında sapma)

Plan formunda yeni sekme: "Takip". Her satır = tedarikçi × ürün; kolonlar:
`önerilen (snapshot) | RFQ'da yazan (draft+purchase PO satırları) | gelen (done receipt) | MO durumu | sapma + kodu`.
- **Manuel RFQ düzeltmesi görülür:** coverage haritası PO satırlarındaki GERÇEK `product_qty`'yi okuduğu için
  adet düşürme/artırma sayıya zaten yansır; Takip sayfası bunu `önerilen vs yazan` farkı olarak gösterir.
  Kodlar: `manual_minus` (bilinçli düşürme → açık ihtiyaç olarak kalır, Revizyon'da hatırlatılır),
  `manual_plus` (bilinçli artırma → fazla-alım uyarısı), `currency_split` (aynı ürün farklı para biriminde
  ikinci RFQ'da — `_rfq_find_updatable` zaten currency'e göre ayırır, coverage ürün-bazlı olduğu için güvenlidir,
  sadece görünürlük için işaretlenir).
- **MO bölme desteklenir:** plan-satır ↔ MO bağı bire-bir OLMAYACAK; eşleşme `origin + product` aramasıyla yapılır
  (bkz 2.5). Takip satırı şunu gösterir: "önerilen 1×152 → gerçekleşen 2 MO (100+52), toplam 152 ✓" veya
  toplam tutmazsa `mo_qty_mismatch` uyarısı. `line.mo_id` tekil alan olarak KALIR (ilk MO), fazlası origin aramasıyla bulunur.
- Sapma kodları renkli etiket (widget `badge`/`tag`) + filtreli tree — kullanıcı "nerede plandan saptım"ı tek bakışta görür.
- Hesap motoru: snapshot JSON + mevcut `_rfq_coverage_map` + `mrp.production` origin araması — YENİ netleme yazılmaz.

### 2.8 Slot/plan kilidi (release süresince hedef değişimi engeli)

Suppliers sayfasında Yayınla'ya basıldığında ilgili plan (ve bağlı slot/hedef seti) `locked_by_release` bayrağıyla kilitlenir:
plan sayfasındaki hedef/target alanları `attrs="{'readonly': [('release_state','=','released')]}"` + server-side
`write` override'da `ValidationError` (JS'yi atlayıp yazan olursa ikinci duvar).
Kilit varken hedef değiştirilemez → "ihtiyaç belirlendikten sonra planın kayması" sınıfı hatalar biter.
Kaçış kapağı (kilitlenip kalma YOK): "Release'i Geri Al" butonu (gerekçe zorunlu, chatter'a işlenir) →
`release_state='draft'`, snapshot revizyon arşivine kalkar, yaratılmış taslak belgeler yerinde durur
(kullanıcı siler veya Revizyon'la devam eder). Kilit asla onaysız açılmaz, asla gerekçesiz kapanmaz.

## 3. Odoo 15 uyum notları (skill: odoo-15 — ihlal YASAK)

- View'lar `<tree>` (asla `<list>`); yeni checklist sekmesi form + tree.
- Güvenlik: `category_id` tabanlı grup; yeni wizard (Transient) için `ir.model.access.csv` satırı;
  manifest `data` sırası: security → wizard → views.
- Kısıt: `_sql_constraints` (gerekirse release snapshot benzersizliği için); `models.Constraint` YOK.
- `sudo()`: recordset üzerinden (`self.sudo()` serbest; `self.env.sudo()` YASAK).
- `copy(default)`: düz dict; multi-company `allowed_company_ids` + TR=1/US=2 kapsamı korunacak.
- OWL1: JS tarafında yeni bileşen gerekirse 1.x API (`Component`, `useState`); tercihen wizard + standart butonla JS'siz çöz.
- Şüpheli her alan (`plan_id` PO'da var mı? `mo_id` tipi? chatter var mı?) implementasyonda `fields_get` ile doğrulanacak.

## 4. Test (staging — staging-matia.odoobulut.com)

1. Staging plan 30 klonu (veya yeni plan): Release → RFQ+MO taslakları snapshot'a eşit mi?
2. MO'ları onayla → Revizyon İste → delta'nın `reservation` koduyla 6/1/2/14 benzeri çıkması ve uyarı vermesi.
3. Rebuild kilidi: `released` planda eski butonların kapalı olduğu.
4. MO dedup: `mo_id`'yi elle sil → Release/Revizyon MO yaratımı mevcut MO'yu bulup bağlanıyor mu?
5. RFQ iptal → plan chatter mesajı + revizyon bayrağı.
6. RFQ butonuna çift basma idempotency (mevcut davranış korunmalı).
7. Manuel RFQ adet düşürme/artırma → Takip sayfasında `manual_minus`/`manual_plus` kodu doğru çıkıyor mu?
8. MO'yu 2'ye bölme → Takip satırı "2 MO, toplam tutuyor" gösteriyor mu?
9. Kilit testi: `released` planda hedef değiştirme denemesi `ValidationError` veriyor mu? "Release'i Geri Al" kilidi gerekçeyle açıyor mu?

## 5. Deploy (KRİTİK — proje gotcha)

- Python değişikliği `button_immediate_upgrade` ile yüklenEMEZ → odoobulut Git Deploy veya servis restart,
  **mesai dışı + öncesi backup**. Canlı DB'ye dokunmadan önce staging'de §4 tamamlanacak.
- Canlı write kuralı: önce `search_read` ile teyit + kullanıcı onayı (`.agents/rules.md` §4).

## 6. Faz dışı (şimdilik YOK)

- Otomatik MO/RFQ confirm; vendor'a otomatik mail; satınalma fiyat pazarlığı otomasyonu.
- Ayrı snapshot modeli (ihtiyaç kanıtlanırsa faz 2).
