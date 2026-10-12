# RFQ Update-Existing (Suppliers sayfasi)

## Istek
Suppliers sekmesinde eksik miktar icin yeni RFQ acmak yerine, ayni
(seller, company, currency) grubundaki mevcut **draft** RFQ'yu guncelle:
urun varsa `product_qty += eksik`, yoksa yeni satir ac.

## Tasarim kararlari
- Sadece `state == 'draft'` PO'lar guncellenir. `sent / to approve /
  purchase / done` belgelere dokunulmaz (tedarikciye gitmis / onaylanmis
  belgeyi sessizce buyutmek ticari risk); o gruplar icin yeni RFQ acilir.
- Eslesme anahtari grup anahtariyla birebir: `(seller, company, currency)`.
  Para birimi / sirket tutmazsa merge Odoo'da mumkun degil (PO basligi tek
  partner + tek currency + tek company tasir) -> o grup icin yeni RFQ.
- Fiyat politikasi (v1): mevcut PO satirinin `price_unit`'i KORUNUR (manuel
  duzeltmeler ezilmez); yeni satirlar plan snapshot'indan (`_rfq_line_eff`)
  acilir. Chatter delta notu planin guncel snapshot fiyatini tasir.
- Adet cevrim: plan satir UoM -> PO satir UoM `_compute_quantity` ile;
  basarisizsa ham eklenir (coverage map ile ayni muhafazakar desen).
- Izlenebilirlik: islem goren plan satiri `purchase_order_id /
  purchase_line_id` ile guncellenen belgeye baglanir (eski davranista
  oldugu gibi uzerine yazilir; coverage map urun-bazli oldugu icin
  cift sayim olmaz).
- Iptal (`cancel`) belgeler yok sayilir (mevcut kural aynen).

## Server (`models/matia_procurement_plan_rfq.py`)
- `_rfq_find_updatable(plan, seller_id, company_id, currency_id)`:
  plana bagli, draft, eslesen PO'yu doner (yoksa False).
- `_rfq_add_lines(env_sudo, plan, po, grp, usd, overrides)`:
  grubun `qty_map` kalanlarini PO'ya ekler; donus
  `{added, bumped, amount}` + chatter delta notu.
- `action_create_supplier_rfq(..., confirm=False, mode='create')`:
  `mode='update'` + confirm ile grup grup bul-guncelle / yoksa-yeni-ac.
  `needs_confirm` yaniti `updatable: [{id, name, currency}]` tasir.
  Donus: `updated + created + skipped + supplier_summary`.
- `action_create_draft_rfqs(..., confirm=False, mode='create')`: toplu
  yolda ayni `mode` destegi (bul-guncelle / yoksa-yeni-ac).
- `get_rfq_preview`: grup bazinda `updatable_po: {id, name} / False`.
- RPC imzasi geriye uyumlu: `mode` 5. pozisyonel arguman, default 'create'.

## Client (`static/src/js/procurement_plan.js`)
- `needs_confirm` sonrasi uyari kutusunda iki buton: `Update RFQ`
  (primary, `mpp-btn-update-rfq`) + `Create new` (secondary, mevcut
  `mpp-btn-confirm-rfq`). Update butonu yalniz server `updatable`
  listesi bos degilse gosterilir.
- `_onUpdateRfq`: `[plan, seller, company, true, 'update']` cagrisi;
  basarida `pendingRfqSeller` temizlenir, `supplier_summary` render edilir.
- `pendingRfqUpdatable`: needs_confirm ile saklanan liste; plan
  degisince sifirlanir (mevcut `pendingRfqSeller` ile ayni omur).

## Dogrulama
- `py_compile` (2 py) + `node --check` (JS) + ASCII taramasi (yeni kod).
- `odoo-reviewer` salt-okunur denetim.
- Staging: ayni supplier+company'de draft RFQ varken eksik icin Create'e
  bas -> Update RFQ onerilir; onayda satir adedi artar, yeni PO acilmaz.
  `sent` PO varken Update -> yeni RFQ acilir (sent'e dokunulmaz).

## Deploy
- Python var -> Git Deploy + servis restart (mesai disi + backup) +
  modul Upgrade + Ctrl+F5. Manifest 15.0.2.7.0 -> 15.0.2.8.0.
- Commit/push kullanici onayiyla.
