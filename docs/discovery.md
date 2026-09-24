# Discovery - Matia Odoo Hub Bilgi Deposu

> **Amaç:** Bu dosya, `matia.odoobulut.com` (Odoo 15) sunucusu hakkında keşfedilen KALICI bilgileri içerir.
> **KURAL:** AI her seansta bu dosyayı OKUR ve yeni keşfedilen önemli bilgileri dosyanın SONUNA ekler.
> **Nedir bu bilgiler?** Yapılandırma detayları, hata sebepleri ve çözümleri, model ilişkileri, çoklu-şirket ayarları, özel modüller, tespit edilen tutarsızlıklar.
> **Ne DEĞİLDİR?** Geçici notlar, denemeler, script çıktıları. Bunlar `scratch/` altında kalır.

---

## Bağlantı Bilgileri

| Parametre | Değer |
|-----------|-------|
| URL | https://matia.odoobulut.com |
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
