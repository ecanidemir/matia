# AGENTS.md - Matia Odoo Hub

> **ÖNEMLİ: Bu proje Odoo 15.0 kullanmaktadır (`matia.odoobulut.com`).**
> Odoo 19'a özgü özelliklerden, Odoo 16+ API değişikliklerinden bahsetme:
> JSON-2 transport YOK (XML-RPC kullanılır), `list` view tipi YOK (`tree` geçerli),
> `res.groups` `privilege_id` YOK (`category_id` geçerli), `models.Constraint`/`models.Index` YOK.
> Şüpheli her API/alan adını `fields_get` veya küçük `search_read` ile doğrula.

## Purpose

Bu projenin amacı, `matia.odoobulut.com` (Odoo 15) sunucusundaki **yapılandırma sorularını**
ve **alınan hataları** AI yardımıyla çözmektir. Tek canlı instance vardır, staging yoktur, SSH yoktur.

**Kapsam:**
- Odoo yapılandırma ayarlarını sorgulama ve açıklama
- Hata mesajlarını analiz etme (kullanıcının sağladığı log/hata metni + DB sorgusu ile)
- Odoo içindeki verileri sorgulama (fiyat listeleri, stok, ürün, sipariş, rapor vs.)
- Workflow, automation, email ayarları, yerelleştirme, muhasebe yapılandırması
- `matia_stock_planning` modülünde sınırlı bakım (Python değişikliği deploy/restart gerektirir)

**Kapsam DIŞI (şimdilik):**
- Sıfırdan özel modül geliştirme
- Sunucu dosya sistemine erişim (SSH yok)
- Odoo log dosyalarını okuma (sadece kullanıcının sağladığı log metni ile çalış)

## Critical Workflow

- **Tani akisi:** Her soru/hata icin `.agents/workflows/diagnose_flow.md` adimlarini izle (netlestir -> recall -> salt-okunur sorgula -> analiz -> dokumante -> hafiza flush). TUI'da `/diagnose-flow` komutu ayni akisi calistirir.
- **Review:** modul degisikligi gerekiyorsa `@odoo-reviewer` subagent ile salt-okunur denetim iste.
- **Memory ritüeli (ZORUNLU):** hata ayıklamadan once `search_memories` + `.agents/memory/HOT.md`'yi oku; her düzeltilen hatayı `log_error` tool'u ile kaydet (dosya + Mem0 çift yazımı otomatik yapar; fallback: `.agents/memory/errors-log.md` + `add_memory`, scope `project`). TUI'da `/log-error <parmak-izi>` ayni kaydi yapar; oturum hataları `error-logger` plugin ile otomatik ham loglanır (`[auto]` satırları `/log-error` ile kürate edilir). Detay: `.agents/rules.md` §9 ve global `error-memory` skill. Secret asla loglama.
- **Discovery:** her seans basinda `docs/discovery.md` oku; kalici bulguyu sonuna ekle.

## Repository Structure

- **[matia_stock_planning](file:///C:/Users/TKA/Desktop/antigravity/odoo/odoo_matia/matia_stock_planning)**: Stok/kapasite planlama modülü ("Cihaz Kapasite Planı" ekranı). Standart layout: `models/` -> `views/` -> `data/` -> `security/` -> `controllers/`, `static/`.
- **[scripts](file:///C:/Users/TKA/Desktop/antigravity/odoo/odoo_matia/scripts)**: Tekrar kullanılabilir XML-RPC sorgu/audit script'leri + ortam script'leri (`start-opencode.ps1`, `load_env.ps1`, `check_mem0.ps1`, `lint_error_log.ps1`, `setup_new_machine.ps1`). Üretim Odoo modülü buraya konmaz.
- **[plans](file:///C:/Users/TKA/Desktop/antigravity/odoo/odoo_matia/plans)**: Kapsamlı işler (modül değişikliği, göç hazırlığı) öncesi plan dosyaları.
- **[docs](file:///C:/Users/TKA/Desktop/antigravity/odoo/odoo_matia/docs)**: `discovery.md` (kalıcı bilgi deposu, KRİTİK) + teknik notlar.
- **[scratch](file:///C:/Users/TKA/Desktop/antigravity/odoo/odoo_matia/scratch)**: Tek seferlik denemeler (git-ignored).
- `gas_client/`, `solidworks_macros/`: Entegrasyon referans kodları.

## High-Signal Patterns

- **Multi-company:** TR (ID 1) ve US (ID 2) bağımsız root şirkettir. `company_id=False` phantom BOM kopyasında "Uyumsuz şirket" hatası alınırsa `copy(id, {'default': {'company_id': 1}})` kullan.
- **`sudo()` deseni:** `self.env.sudo()` Odoo 15'te YOKTUR. `self.with_context(allowed_company_ids=..., active_test=False).sudo().env` kullan.
- **Net kapasite:** `avail_qty = stock_qty - reserved_qty` (`stock.quant` `quantity` + `reserved_quantity`); NCR lokasyonları (TR ID 333, US ID 332) net hesaba katılmaz.
- **Python değişikliği belleğe yüklenemez:** `button_immediate_upgrade` işe yaramaz; odoobulut Git Deploy veya servis restart gerekir (mesai dışı + öncesi backup).

## Skills (Odoo 15 uyumu — KRİTİK)

Skill yüklemeden ÖNCE bu listeye bak. Odoo 19 için yazılmış skill'ler 15'te patlayan kalıplar önerir.

**Kullan (Odoo 15-safe):**
- `odoo-15` — BU PROJENİN skill'i (`.opencode/skills/odoo-15/`): tree/category_id/_sql_constraints/OWL1/sudo deseni, 15→19 delta tablosu. Odoo 15 kodu yazmadan/incelemeden ÖNCE yükle.
- `odoo-dev` — genel modül conventions (Odoo 14-19, bu projeye uygun)
- `odoo-model-inspect`, `odoo-stock-inspect`, `odoo-system-inspect` — veri/model inceleme
- `odoo-code-review`, `odoo-code-tracer` — inceleme/izleme
- `odoo-migration` — 15→19 göç planlaması için (hedef sürüm kalıplarını 15'e uygulama)
- `brainstorming`, `code-review`, `mcp-builder` — genel amaçlı

**YASAK / kullanma:**
- `odoo-19` — 18 rehberlik dosyasının tamamı Odoo 19 API'si (`list` view, `privilege_id`, Constraint/Index, OWL2). 15'te karşılığı yok.
- `odoo-owl` — OWL2 hook/servisleri; 15'te OWL1 geçerli.
- `dtg-base`, `payment-integration`, `writing-skills` — bu projeyle ilgisiz (hub artığı).

Kural: skill önerisi ile `.agents/rules.md` §6 çelişirse §6 kazanır; şüpheli alanı `fields_get` ile doğrula.

## MCP Servers (Auto-Selection)

Bu projede tanımlı MCP server:

| Server | Amaç | Kullanım |
|--------|------|----------|
| `odoo_matia` | Odoo 15 XML-RPC bağlantısı (tek canlı instance) | `odoo_matia_*` tool'ları ile DB sorgulama, okuma, kontrollü yazma |

**Desteklenen IDE'ler (ayrı config dosyaları, AYNI mantık):**
- **OpenCode Desktop/TUI**: `opencode.json` (proje kökünde, otomatik yüklenir)

### Config Format Notu

JSON string'lerinde backslash escape sorunu nedeniyle config dosyalarında forward slash (`/`) kullanılır. Windows API ikisini de kabul eder.

### Kullanım Kuralları

1. **Tüm Odoo sorgulamaları** `odoo_matia_*` ile yapılır (failover: `scripts/` XML-RPC helper).
2. **Dokümantasyon gerektiğinde** global `context7` kullan; Odoo kaynağı için `/odoo/odoo` branch `15.0` seç (19 kalıplarını alma).
3. **MCP bağlantı hatası teşhis prosedürü** (ASLA "sunucu kapalı" diye varsayım yapma) — sırayla uygula:
   1. Hata mesajının TAMAMINI oku (`WinError 10061` genelde localhost MCP port sorunudur).
   2. `odoo_matia_list_instances` çağır; `url`/`db` boşsa → **config/env sorunu**.
   3. `odoo_matia_health_check` çağır; `instance_count` ve `default_instance` alanlarına bak.
   4. Boş env şüphesi varsa `scripts/start-opencode.ps1` ile başlatılıp başlatılmadığını kontrol et.
4. **OpenCode her zaman proje kökünde çalıştırılmalı.** Dışında çalıştırılırsa opencode.json bulunamaz, MCP'ler başlamaz.
5. **Yıkıcı işlemlerden önce onay al:** modül kur/kaldır, veri silme/toplu güncelleme, yapılandırma değişikliği. Staging yok — teknik engel değil prosedür engeli.
6. **Credential'ları asla loglama** — `ODOO_PASSWORD` değerini çıktıya dahil etme.

## Environment (SSH yok)

- **Credentials:** `.env` dosyasında saklanır (git-ignored). Şablon: `.env.example`.
- **Başlatma:** `powershell -ExecutionPolicy Bypass -File scripts/start-opencode.ps1` (workspace `.env`'i yükler, sonra opencode'u başlatır). Doğrudan `opencode` komutu `.env` yüklemez → MCP boş config ile kalkar.
- **Odoo 15** — XML-RPC transport (`ODOO_TRANSPORT=xmlrpc`)
- **Bağlantı:** https://matia.odoobulut.com (DB: `matia.odoobulut.com`)

## Verification & Auditing

- **Hafıza flush:** `/log-error` ile kayıt + `powershell -File scripts/lint_error_log.ps1` temizliği (format + secret + `[auto]` birikimi).
- **Mem0 triyaj:** `powershell -File scripts/check_mem0.ps1` (exit 2 = env yok, exit 1 = anahtar geçersiz).
- **Yeni makine:** `powershell -File scripts/setup_new_machine.ps1` (aletler, MEM0 key, plugin, skill, ritüel, `.env`).
- **Test:** otomatik test yok; doğrulama `search_read`/`fields_get` ve küçük `scratch/` script'leri ile yapılır.

## Operational Gotchas

- Python değişikliği XML-RPC upgrade ile yüklenemez (Git Deploy/restart gerekir).
- `company_id` değişikliği kullanılmış üründe Odoo tarafından engellenebilir (uyarı verir).
- Giden posta (SMTP/OAuth) bozuk olabilir — `mail.mail` exception sayısını kontrol et.
- 3745 negatif `stock.quant` biliniyor; sayım temizliği yapılmadan quant birebir taşınmaz (göç notu).
