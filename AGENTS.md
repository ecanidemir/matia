# AGENTS.md - Matia Odoo Hub

> **ÖNEMLİ: Bu proje Odoo 15 kullanmaktadır.**
> Odoo 15 Community Edition (CE) veya Enterprise (EE) olabilir. Hangi sürüm olduğundan emin değilsen, `odoo_matia_list_instances` veya `odoo_matia_search_modules` ile kontrol et.
> Odoo 19'a özgü özelliklerden, Odoo 16+ API değişikliklerinden bahsetme.

## Purpose

Bu projenin amacı, `matia.odoobulut.com` (Odoo 15) sunucusundaki **yapılandırma sorularını** ve **alınan hataları** AI yardımıyla çözmektir.

**Kapsam:**
- Odoo yapılandırma ayarlarını sorgulama ve açıklama
- Modül kurulumu / kaldırılması
- Hata mesajlarını analiz etme (kullanıcının sağladığı log/hata metni + DB sorgusu ile)
- Odoo içindeki verileri sorgulama (fiyat listeleri, stok, ürün, sipariş, rapor vs.)
- Workflow, automation, email ayarları, yerelleştirme, muhasebe yapılandırması

**Kapsam DIŞI (şimdilik):**
- Özel modül geliştirme / Python kodu yazma
- Sunucu dosya sistemine erişim (SSH yok)
- Odoo log dosyalarını okuma (sadece kullanıcının sağladığı log metni ile çalış)

## MCP Servers

Bu projede tanımlı MCP server:

| Server | Amaç | Kullanım |
|--------|------|----------|
| `odoo_matia` | Odoo 15 XML-RPC bağlantısı | `odoo_matia_*` tool'ları ile DB sorgulama, okuma, yapılandırma değişiklikleri |

### Kullanım Kuralları

1. **`odoo_matia` MCP tool'ları** ile Odoo'ya bağlan:
   - `odoo_matia_list_instances` - Bağlantıyı test et
   - `odoo_matia_search_model` / `odoo_matia_read_model` - Veri okuma
   - `odoo_matia_search_modules` - Modülleri listele
   - Odoo 15 olduğu için **xmlrpc** transport kullanılır. `ODOO_TRANSPORT` env'i buna ayarlıdır.

2. **Yıkıcı işlemlerden önce kullanıcıya sor:**
   - Modül kurma/kaldırma
   - Veri silme/güncelleme (küçük düzeltmeler hariç)
   - Yapılandırma değişiklikleri

3. **Credential'ları asla loglama** - `ODOO_PASSWORD` değerini çıktıya dahil etme.

4. **MCP bağlantı hatası teşhisi:**
   - `odoo_matia_list_instances` çağır. Boş dönerse → .env/config sorunu.
   - `odoo_matia_health_check` çağır, yanıta bak.

## Environment

- **Credential'lar:** `.env` dosyasında saklanır (git-ignored)
- **Odoo 15** - XML-RPC transport
- **Bağlantı:** https://matia.odoobulut.com

## Common Tasks

### Bağlantı Testi
```python
odoo_matia_list_instances
```

### Modülleri Listeleme
```python
odoo_matia_search_modules
```

### Model Verisi Okuma
```python
odoo_matia_search_model(model="res.company")
odoo_matia_read_model(model="res.config.settings")
```

## Odoo 15 Notes

- Odoo 15'te **JSON-2 transport yoktur** (Odoo 19 ile gelmiştir), XML-RPC kullanılır.
- Odoo 15 CE/EE arasındaki farklar: EE'de `account_accountant`, `stock_enterprise`, `sale_enterprise` gibi modüller vardır.
- Odoo 15'te **studio** yoktur (16+'da gelmiştir).
- Odoo 15 Python sürümü: 3.8 veya 3.9
- Odoo 15 API key desteği: 15.0 sonrası sürümlerde eklenmiştir. API key çalışmazsa kullanıcı adı/şifre ile dene.

## Bilgi Deposu (Discovery - KRITIK)

- **`docs/discovery.md`**: Bu dosya, `matia.odoobulut.com` sunucusu hakkında keşfedilen KALICI bilgileri içerir.
- **KURAL:** AI her seansta bu dosyayı OKUR ve yeni keşfedilen önemli bilgileri dosyanın SONUNA ekler.
- **Nedir bu bilgiler?** Yapılandırma detayları, hata sebepleri ve çözümleri, model ilişkileri, çoklu-şirket ayarları, özel modüller, tespit edilen tutarsızlıklar.
- **Ne DEĞİLDİR?** Geçici notlar, denemeler, script çıktıları. Bunlar `scratch/` altında kalır.
- **Kullanıcı hatırlatmayacak.** AI bu kuralı kendisi uygulayacak. Her seansta:
  1. `docs/discovery.md` varsa oku
  2. Soruyu yanıtlarken oradaki bilgileri kullan
  3. Yeni bir şey keşfettiysen dosyaya ekle

## Data Butunlugu

- **Overwrite yasa**: Mevcut dosyalara asla içerik silme/yeniden yazma. Önce oku, gerekiyorsa sonuna ekle.
- **Gereksiz dosya bırakma**: Deneme amaçlı script'leri `scratch/` altına koy, proje kökünde bırakma.
