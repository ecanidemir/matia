# Plan: Sayım Listesi Butonları (TR/US) — Capacity sayfası

Tarih: 2026-10-15 | Durum: uygulamada

## İstek
TekRMD Device Capacity & Stock Plan sayfasında Refresh yanına 2 buton
(TR Sayım Listesi / US Count List). Tıklayınca yeni sekmede yazdırılabilir
HTML sayfa açılsın; sayfada Print + Excel butonları olsun.

## Tasarım (mevcut kalıpları yeniden kullan)
- Veri: `matia.stock.planning` üzerine yeni `@api.model get_count_sheet(company)`
  metodu. `tr`/`us` dışına `UserError`.
  - Lokasyon sınıflandırma = `get_capacity_planning_data` ile aynı
    (`WHTR/Stock*` / `WHUS/Stock*`, internal, NCR hariç) + ek: adında
    `Subcontract` geçen TR lokasyonu hariç (scratch listesindeki kapsam).
  - Kit bulma = `_mpp_find_kit_boms` (ID-öncelikli, isim-fallback).
  - Patlatma = variant-öncelikli BFS, depth ≤ 10, path-cycle guard
    (price-overview yürüyüşüyle aynı kural).
  - Stok = `stock.quant` read_group grup `[product_id, location_id]`
    (seri/lot quant'ları lokasyonda otomatik toplanır = çift yazım yok),
    sadece toplam `quantity > 0`.
  - TR: `Units` → `Adet`, diğer birimler aynen. US: aynen (`Units`).
  - Sıra: önce depo (lokasyon adları), sonra kod, sonra ad.
- Sunum: yeni `controllers/count_sheet.py`
  - `GET /matia_stock_planning/count_sheet/<tr|us>` (auth=user) →
    QWeb sayfa (`views/count_sheet_templates.xml`): 4 sütun
    (Kod/Product / Depo-Location / Miktar-Quantity), Print + Excel butonları.
  - `GET .../count_sheet/<tr|us>/xlsx` → xlsxwriter varsa .xlsx,
    yoksa BOM'lu CSV (main.py'deki fallback ile aynı).
  - Dil sabit: TR sayfa Türkçe, US sayfa İngilizce (kullanıcı dilinden bağımsız).
- Butonlar: `stock_planning.xml` `.msp-actions` içine 2 buton +
  `stock_planning.js` events + `window.open(url, '_blank')`.
- Manifest: `views/count_sheet_templates.xml` data sonuna + version bump.

## Erişim
Sayfa menüsü gibi `base.group_user`; veri okuma mevcut sudo kalıbıyla
(`allowed_company_ids` + `active_test=False`). Sadece okuma, write yok.

## Doğrulama
`py_compile` (py) + XML parse + `node --check` (js) + TR-karakter taraması
(sadece TR template değerlerinde; kod/ident_ascii). Sonra `@odoo-reviewer`.

## Deploy (Python değişikliği!)
`button_immediate_upgrade` YÜKLEMEZ → odoobulut Git Deploy + servis restart
gerekir. Mesai dışı + öncesi backup. Önce staging-matia'da dene.
