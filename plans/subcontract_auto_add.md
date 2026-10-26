# Subcontract Auto-Register (PO onayında fason tedarikçi ekleme)

## Sorun
Fason (`type=subcontract`) BOM'larda `subcontractor_ids` içinde PO tedarikçisi yoksa
Odoo onayda eşleşen BOM bulamaz, normal receipt'e düşer; ham madde tedarik emri/MO oluşmaz.
Örnek: PO/26-00146 (Maksan 1299), 67 BOM'da sadece 1088/1240 vardı. Bileşen rotaları tamam
(42/42 `[5,9]`), tek eksik tedarikçi eşleşmesiydi.

## Karar
- `purchase.order button_confirm` override, `super()` ÖNCESİ çalışır (eşleşme onay anında yapılır).
- Kural: satır ürününün fason BOM'u varsa ve tedarikçi listede yoksa `[(4, vendor)]` ile ekle.
  Normal/phantom BOM, reçetesiz ürün, listedeki tedarikçi → dokunma.
- Mevcut `matia_stock_planning` modülüne ek (yeni modül yok): `models/purchase_subcontract_auto.py`.
- Başarısızlık purchase akışını bloklamaz (warning log + devam).

## Test
1. `py_compile` + manifest import sırası kontrolü.
2. Staging: yeni tedarikçili RFQ → onayla → BOM'da tedarikçi var mı, resupply/MO oluştu mu.
3. Eski PO'lar (146 dahil) bu koddan yararlanamaz → ayrı backfill + iptal/yeniden oluşturma.

## Deploy
Python değişikliği: Git Deploy + restart (mesai dışı + backup). `button_immediate_upgrade` yetmez.
