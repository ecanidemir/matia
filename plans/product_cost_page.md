# Product Cost Sayfasi Plani (2026-10-07)

## Kararlar (kullanici onayli)
- Menu: "Product Cost", Capacity Plan app altinda, `base.group_system` (sadece admin), sequence 30.
- Template + renkler capacity ile ortak (`msp-*` siniflari, ayni SCSS scope).
- 4 BOM grubu: Base / Outdoor / Seat / Screws (capacity'deki `bom_configs` aynen).
- Cost sutunlari: Part name & code, Usage qty (ham satir miktari, Per-Parent), BOM Cost (bottom-up rolled USD).
- Grup toplami = **1 cihaz set maliyeti** (ust seviye satirlarin `rolled_unit x usage` toplami).
- 3 kombinasyon kutusu (screws her zaman base'e dahil): full=base+outdoor+seat / base+outdoor / base+seat.
- Fiyat kaynagi: corrected (global override tablosu) varsa o, yoksa CANLI son-alim USD (UoM factor dahil). Plan snapshot kullanilmaz.
- Prices sekmesi Production Plan'dan TAMAMEN tasinir (tek dogruluk kaynagi Product Cost).
- Reset: secili satirlarda confirm ile corrected uzerine yazar.
- Cost sekmesi acilista otomatik hesaplar (butonsuz).
- Filtre yok: TR/USA secimi, hedef adet sutunlari yok.

## Mimari
- Yeni dashboard action `matia_product_cost.dashboard` (tek sayfa, 2 tab: Cost + Prices).
- Server: yeni dosya `models/matia_product_cost.py` (`matia.product.cost` AbstractModel):
  - `get_cost_tree()` — 4 kit patlatma (capacity `bom_configs` ID/sira aynen) + canli `_mpp_last_buys` + `_mpp_price_overrides` + bottom-up rolled (`_compute_rollup` ile ayni formül: own = corrected > 0 ? corrected : last_usd x uom_factor; make/kit own=0). Plan satiri yazmaz, salt-okunur.
  - `get_sub_bom_cost()` — capacity'deki expand deseni, satir: usage + rolled.
  - `get_prices_overview()` — mevcut Prices metodunun plan-bagimsiz hali (plan=None yolu zaten var; `line_by_pid` bos -> canli last-buy fallback). Mevcut metodu `plan_id=False` ile cagiran ince wrapper tercih edilir, kod kopyalama yok.
  - `reset_prices_to_usd(product_ids)` — confirm sonrasi corrected = hesaplanan USD (mevcut `save_price_override` toplu cagrisi; make/kit satirlari atlanir, ayni kural).
  - Tekil save/clear: mevcut `save_price_override` / `clear_price_overrides` aynen yeniden kullanilir.
- Client: yeni `static/src/js/product_cost.js` + `static/src/xml/product_cost.xml` (+ gerekirse `product_cost.scss`, yoksa scope'a kok eklenir). Cost tab capacity render desenini kopyalar (grup rozeti, expand, KPI accent); Prices tab mevcut procurement Prices tab JS/XML'i tasinir.
- Plan sayfasindan Prices tab'i kaldirilir (JS tab butonu + XML panel + ilgili SCSS; server metodu silinmez, wrapper kullanir).
- Menu: `views/product_cost_menus.xml` (sequence 30, groups system) + client action XML; manifest'e yeni dosyalar eklenir (data sirasi: access csv -> security -> views).

## Odoo 15 kurallari
- `tree` view (list yok), `_sql_constraints`, OWL1, recordset `.sudo()` deseni.
- Ezber alan yok: yeni alan/metod `fields_get` + kucuk `search_read` ile dogrulanir.
- Skill-first: kod yazmadan once `odoo-15` skill yuklenir.

## Test / deploy
- `py_compile` + `node --check` + TR-karakter taramasi (`Select-String -CaseSensitive`).
- Python degisikligi var -> staging Git Deploy + Upgrade/restart (mesai disi + backup); MEVCUT planlara dokunulmaz, Recalculate gerekmez.
- Canli dogrulama: bir grubun set toplami, Production Plan Recalculate sonrasi ayni grubun rolled toplami ile karsilastirilir.
