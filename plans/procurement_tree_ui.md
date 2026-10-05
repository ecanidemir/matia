# Procurement Tree UI — Capacity kopyası (2026-10-05)

## İstek (kullanıcı)
- Staging'deki sayfa görüldü ama anlamlı değil.
- Capacity plan gibi tam ağaç: 4 BOM, seviye girinti, expand/collapse, sub-BOM satırları.
- Sütunlar: rezerve edilmemiş stok (avail), planlanan üretim, her ana ürün için ayrı üretilecek miktar, her ana ürün son hareketlerden TL maliyet, o günkü kurdan USD hali, USD'ye çevrilen tarih (kısa).
- Adet girişi: her ana ürüne ~120 adet girilebilir; üstte "50'ye tamamla" → avail'i 50'ye tamamlayacak qty otomatik dolar.

## Kararlar
- TR-only netleme korunur (`WHTR/Stock%`, NCR hariç, `avail=max(0,onhand-reserved)`).
- Capacity sayfasına DOKUNULMAZ. Sadece `matia_procurement_plan*` + `procurement_plan.js/xml/scss` + export.
- Tek ekran akış: Adım 1 (giriş) + Adım 2 (ağaç+maliyet) aynı sayfada; Adım 3 (supplier/RFQ) altta kalır.
- 120 ayrı sütun YOK (tablo patlar). "Ana ürün kırılımı" satır tooltip + `top_breakdown` (`{top_code: qty}`) olarak verilir; ana tabloda tek `Planned (gross)` kolonu.
- TL maliyet: `rolled_try` (birim) + `rolled_total_try` (gross×birim) yeni stored field'lar; USD karşılığı mevcut `rolled_usd` ile yan yana. Tarih `Mon YYYY` kısa format (mevcut `_mpp_month_year`).

## Backend (matia_procurement_plan.py, Odoo 15-safe)
1. `matia.procurement.plan.line`: + `rolled_try`, `rolled_total_try` (Float, digits 16,4 / 16,2).
2. `_compute_rollup` → hem USD hem TRY: `_own_usd=last_price_usd`, `_own_try=last_price'i TRY'ye last_date kuruyla çevir (yoksa unit_price fallback)`. Çocuklar `edge_json` üzerinden toplanır. Kit toplamları + grand total her iki kurda.
3. Yeni `get_tree_with_cost(plan_id)`:
   - `action_explode_and_net` + `action_assign_suppliers`'ı içten çağırır (kayıt yazımı aynı, tekrar çalışabilir).
   - Dönüş: `groups` capacity şeklinde (4 kit, `items` level=0, `has_bom`, `bom_qty=1` üstte), her item'da: `stock_tr,reserved_tr,avail_tr,gross,net,order_qty,planned,producible,seller,last_price,last_currency,last_usd,last_date_short,rolled_try,rolled_total_try,rolled_usd,rolled_total_usd,subtotal,uom,route,top_breakdown,incoming_info,open_mo_info`.
   - `need_per_top`: patlatma sırasında `pid->{top_pid: katkısı}` biriktirilir, özet cümle `TOPCODE×qty` olarak kısaltılır.
4. Yeni `get_sub_bom_cost(product_id, parent_bom_qty, plan_id)`:
   - `matia.stock.planning.get_sub_bom_details` mantığı kopyası (TR-only) + aynı satır maliyet snapshot'ı (son alım + USD + TRY çeviri + kısa tarih). Sınırsız derinlik (özyinelemeli frontend).
5. `_plan_summary` → tree gruplarını da içerir (`tree_groups`), mevcut `groups` (route) + `suppliers` bozulmaz (RFQ/export aynen çalışır).

## Frontend (procurement_plan.js/xml/scss)
- Capacity'den kopya: header, arama, Expand All / Collapse All, grup başlıkları (4 kit, BOM adı, parça sayısı, Hide/Show), level rozeti (L0..), girintili sub-satırlar, sortable başlıklar, `mpp-` prefix (msp'ye dokunmaz).
- Kolonlar (tek tablo): Part | Usage | Unreserved | Planned | Net/Order | Seller | Cost TL | USD | Date | Rolled TRY | Rolled USD | Subtotal.
- Giriş tablosu üstüne: `N input (default 50)` + `Fill to N` butonu → `qty_input=max(0,N-avail_tr)`; `Clear` butonu. Satırda avail rozeti.
- Hesapla tek buton: `create_plan → get_tree_with_cost` zinciri; sonuç ağaçta. Eski Adım 2/3 sekme tabloları altta "Supplier / RFQ" bölümü olarak kalır (RFQ akışı bozulmaz).
- Excel: mevcut supplier export korunur + yeni `Export Tree` (görünen ağaç, girintili) aynı route'a `mode=tree` ile.

## Verify
- `python -m py_compile` models/controllers, `node --check` JS, XML parse.
- Staging: Git Deploy + Upgrade, admin ile `Capacity Plan > Procurement & Production Plan (Preview)` kontrol: 4 grup, expand, 50'ye tamamla, TL/USD/tarih kolonları.
- Prod'a deploy YOK (bu faz staging-only).

## Açık nokta (V2)
- "Her ana ürün için ayrı sütun" gerçekten 120 sütun istenirse pivot/Excel'e taşınır; ekranda tooltip kalır.
