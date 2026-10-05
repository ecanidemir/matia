# Proje Kurallari (Project Rules) — Matia Odoo Hub

Bu projede (Odoo 15, `matia.odoobulut.com`, XML-RPC, SSH yok) calisirken asagidaki kurallara **kesinlikle** uymalisin.

## 0. Discovery Dosyasi (ZORUNLU)

- **HER SEANS BASINDA** `docs/discovery.md` dosyasini oku. Bu dosyada sunucu hakkinda kalici bilgiler, bilinen hata desenleri ve cozumleri bulunur.
- Yeni bir sey kesfettiginde (yapi, hata, cozum), dosyanin sonuna ekle. Format: kisa baslik + tarih + bulgu/cozum.
- Bu kurali kullaniciya hatirlatma. AI kendisi uygulayacak.

## 1. Baglanti ve Sorgulama

- **MCP once**: Tum Odoo sorgulamalari icin `odoo_matia_*` MCP araclarini kullan. Transport XML-RPC'dir (`ODOO_TRANSPORT=xmlrpc`). JSON-2'den asla bahsetme (Odoo 19 ile gelmistir).
- **MCP baglanti hatasi teşhis proseduru** (ASLA "sunucu kapali" diye varsayim yapma) — sirayla uygula:
  1. Hata mesajinin TAMAMINI oku. `WinError 10061` / "connection refused" genelde MCP server'in localhost portuna baglanamadigini gosterir, hedef Odoo'nun degil.
  2. `odoo_matia_list_instances` cagir. Donen `url`/`db` bos ise → **config/env sorunu**, hedef sunucu sorunu degildir.
  3. `odoo_matia_health_check` cagir; `instance_count` ve `default_instance` alanlarina bak.
  4. Bos env suphesi varsa: `powershell -ExecutionPolicy Bypass -File scripts/start-opencode.ps1` ile baslatilmis mi kontrol et (workspace `.env` OTOMATIK yuklenmez; opencode.json `{env:...}` yalnizca proses env'inden okur).
  5. **OpenCode her zaman proje kokunde calistirilmali** (`C:\Users\TKA\Desktop\antigravity\odoo\odoo_matia`). Disinda calistirilirsa opencode.json bulunamaz, MCP'ler baslamaz.
- **Failover**: MCP araci basarisiz olursa, ayni isi `scripts/` altindaki XML-RPC helper ile dene. Hata mesajini kullaniciya goster.
- **Tek instance**: Staging yok, tek canli DB var (`matia.odoobulut.com`). Tum sorgular once salt-okunur (`search_read`/`read`) ile teyit edilir.

## 2. Kodlama Standartlari (`matia_stock_planning` + deneme scriptleri)

- **Python Docstring**: Her model, method ve wizard class'i docstring icermeli. `@param`, `@return` ve methodun amaci aciklanmali.
- **Hardcoded Deger Yasagi**: URL, DB adi, kullanici adi, sifre/API anahtari koda gomulmez. `.env` dosyasindan okunur (`ODOO_URL`, `ODOO_DB`, `ODOO_USERNAME`, `ODOO_PASSWORD`).
- **Hata Yonetimi**: XML-RPC cagrilari ve Odoo `write`/`create`/`copy` islemleri `try-except` icine alinmali. Hatada kullaniciya net mesaj ver.
- **`_(...)` Kullanimi**: Tum kullanici-yonelik string'ler `_("...")` ile sarmalanmali (translation destegi).
- **`@api.depends` Tamligi**: Computed field'lar icin `@api.depends` listesi OKUNAN tum field'lari icermeli. Eksik depends -> stale stored field.
- **Odoo 15 kopyalama deseni**: `copy()` cagrisinda varsayilan degerler `{'default': {'field': value}}` olarak gecilir, flat `default_field=value` DEGIL (bkz. `docs/discovery.md` Multi-Company BOM Kopyalama).
- **`sudo()` deseni**: Odoo 15'te `Environment` nesnesinin `.sudo()` metodu YOKTUR. Dogru desen recordset uzerinden:
  ```python
  env_sudo = self.with_context(allowed_company_ids=all_ids, active_test=False).sudo().env
  ```

## 3. Kritik Dosyalar ve Modul Yapisi

- **`matia_stock_planning/`**: Kapasite/planlama moduludur. Standart layout korunur: `__init__.py` -> `models/` (+`__init__.py` import) -> `views/` -> `data/` -> `security/ir.model.access.csv` -> `controllers/`, `static/`.
- **Manifest `data` sirasi**: `security/ir.model.access.csv` -> `security/*_security.xml` -> `views/*` -> `data/*`. ACL view'lardan once yuklenmeli. Yeni dosya eklenirse once manifest guncellenir (manifest yukleme sirasinin tek gercegidir).
- **Python degisikligi deploy gerektirir**: Moduldaki Python kodu XML-RPC `button_immediate_upgrade` ile bellege YUKLENEMEZ; odoobulut panelinden Git Deploy veya servis restart gerekir. Mesai disi + oncesi backup.
- **`noupdate="1"` kayitlari**: Degisiklik upgrade'te uygulanmaz; manuel duzeltme gerekir.
- **Computed field'lar** (`stored=True`): Guncellenmiyorsa Server Action/teknik ekrandan `modified()` tetikle.

## 4. Guvenlik

- **Hassas Veriler**: Sifre/API anahtari asla koda gomulmez, `.env` dosyasindan okunur. `.env` `.gitignore`'da, `opencode.json` duzenlemesi `.env`'i hedef almaz (edit deny).
- **Loglama**: Debug log'larinda `ODOO_PASSWORD` degeri ASLA yazdirilma. Secret suphesi push'u bloklar (`scripts/lint_error_log.ps1`).
- **Canli DB write kurali (KRITIK — staging yok)**: Bu projede MCP write tool'lari ACIKTIR, teknik engel yoktur; engel PROSEDURELDUR:
  1. Once ilgili kaydi `search_read` ile oku ve kullanıcıya goster.
  2. Kucuk duzeltme disindaki her write (modul kur/kaldir, toplu update, config degisikligi) ONCESI kullaniciya sor.
  3. Mumkunse `preview`/`dry-run` ciktisini paylas, sonra uygula.
- **Yikici islem onayi**: Veri silme, modul kurma/kaldirma, yapilandirma degisikligi oncesi sor.

## 5. Script Yazimi

- **Script Klasoru**: Tekrar kullanilabilir audit/sorgu script'leri `scripts/` icinde. Tek seferlik denemeler `scratch/` altinda (git-ignored). Kok dizine koyma.
- **Env Okuma**: Script'ler `.env`'i `scripts/load_env.ps1` (PowerShell) deseniyle yukler. `python-dotenv` gibi harici bagimlilik ekleme; stdlib (`xmlrpc.client`) yeter.
- **Default salt-okunur**: Script default'u read-only calismali. Write gerekiyorsa explicit flag (`--apply`) + onaya baglanmali.
- **Gecici Dosya Temizligi**: Isi biten debug script'i sil veya `scratch/`'e tasi. `scripts/`'de cop birikmesin.

## 6. Odoo 15 Kisitlari (Odoo 19 kaliplarini KOPYALAMA)

- **Surum**: Odoo 15.0 (20250101), Python 3.10, Ubuntu 22.04 (odoobulut). CE/EE ayrimi icin once kurulu modullerden teyit et (`l10n_tr_*`, `studio` var mi bak); emin degilsen EE-only iddia etme.
- **Odoo 19'da kaldirilan ama 15'te GECERLI olanlar**: `tree` view tipi, `res.groups` `category_id`, `ir.cron` `numbercall`/`doall`. Bunlari "kaldirilmis" diye duzeltmeye kalkma.
- **Odoo 15'te YOK**: JSON-2 transport (XML-RPC kullan), `models.Constraint`/`models.Index` modern API'leri (`_sql_constraints` kullanilir), yeni OWL2 hook'lari (OWL1 deseni gecerli).
- **Studio**: Yalnizca EE'de uygulama olarak vardir; CE'de tum ozellestirme Developer Mode -> Technical Settings veya Python/XML ile yapilir.
- **Supheli API/alan**: Ezberden alan/metod adi yazmak YASAK. Her sorgu/yazim oncesi `fields_get` veya kucuk `search_read` ile dogrula.

## 7. Kullanici Iletisimi

- Teknik terimleri aciklarken net, kisa dil kullan. Uzun girisler yerine bulgu -> neden -> cozum sirasi izle.
- "Bilgim yok" / "Yapamam" demek yerine "Su model/ayar uzerinden sorgulayarak cozum uretebilirim" seklinde proaktif ol.
- Bir islemin Odoo 15'te mumkun olup olmadigindan emin degilsen, once `fields_get`/dokuman kontrol et, sonra cevapla.

## 8. Veri Butunlugu ve Dosya Yonetimi (KRITIK)

- **Overwrite Yasagi**: `docs/discovery.md`, `README.md`, log dosyalari gibi kumulatif dosyalara ASLA overwrite yap. Once oku, sonra sonuna ekle.
- **Atil Dosya Temizligi**: Bir yontemden vazgecildiginde o yontem icin uretilmis eski script'leri ANINDA sil. Projede cop dosya birakma.
- **Gereksiz dosya birakma**: Deneme script'leri `scratch/` altinda kalir, proje koku temiz tutulur.

## 9. Dokumantasyon ve Kayit Tutma

- **Discovery guncelle**: Kalici bulgu (yapi, hata, cozum) `docs/discovery.md` sonuna eklenir. Gecici notlar `scratch/`'te kalir.
- **Plans**: Kapsamli is (modul degisikligi, goc hazirligi) oncesi `plans/` altina plan yazilir.
- **Hata Hafizasi (ZORUNLU, atlanamaz)**: Her duzeltilen dev hatasi (kod, MCP, yapistirilan traceback dahil) icin:
  1. Once `search_memories` ile parmakizini ara + `.agents/memory/HOT.md`'yi oku.
  2. Sonra tek satir yaz: `.agents/memory/errors-log.md`'ye ekle + `add_memory` (scope `project`). Max 1-2 satir: `[O15] parmakizi | kok neden -> cozum`. `[O15]` oneki, Mem0 user_id ayrimina (`odoo-matia` vs `odoo-hub`) ek olarak gozle gorunur surum etiketi saglar; hub tarafi `[O19]` yazar. Secret ASLA yazma. Tercihen `log_error` tool'u (`/log-error`) ile cift yaz (formati sabitler).
  3. 3+ tekrar eden hata `HOT.md`'ye terfi eder (<=30 satir, 30 gun).
  4. Push oncesi `powershell -File scripts/lint_error_log.ps1` temiz olmali (format + secret + [auto] birikimi).
  Detay icin global `error-memory` skill'ini yukle. Mem0 default scope `project`'tir.
- **Mem0 401 Triyaji (ZORUNLU sira, ezberden anahtar suclama YASAK)**:
  1. `powershell -File scripts/check_mem0.ps1` calistir (read-only, secret yazdirmaz).
  2. Exit 2 = opencode process'te env yok -> `scripts/start-opencode.ps1` ile baslat (dogrudan `opencode` komutu `.env` yuklemez).
  3. Exit 1 = anahtar gercekten gecersiz -> dashboard'dan rotate et (sadece bu durumda).
  4. El yazimi Mem0 REST cagrilarinda trailing slash sart (`/v1/memories/search/`); slash'siz path 301'de auth header'i dusurup sahte 401 uretir.
- **Secretli Komut Kurali**: `$env:SECRET` iceren komut ASLA cift tirnakli `-Command "..."` icine gomulmez (dis shell once genisletir, hata ciktisina duser). Test icin `cmd /c "(set VAR= && ...)"` kalibi kullan. Sizan anahtar aninda rotate edilir.
- **Skill-First Yazim (ZORUNLU, atlanamaz)**: Odoo Python/XML yazmadan ONCE ilgili skill'i yukle + supheli her alan/yapi icin `fields_get` veya kucuk `search_read` ile dogrula. Ezberden API/alan adi yazmak YASAK. Her oturum basinda `.agents/memory/HOT.md`'yi oku; ihlal canli DB'ye dokunmadan once local `py_compile`/XML parse ile yakalanmali.
