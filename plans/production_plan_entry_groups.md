# Plan: Production Plan Tab 1 — Gruplu Miktar Girişi + Grup Bazında Auto-Fill

Tarih: 2026-10-06 | Kapsam: SADECE `static/` (JS + QWeb XML), Python değişikliği YOK

## İstek (kullanıcı)

1. Tab 1 "Enter quantities" Capacity Plan'daki gibi 4 gruba ayrılsın:
   Base, Outdoor Parts, Seat Parts, Common Screws — görsel birebir aynı uyumda.
2. `Kit` sütunu kaldırılsın.
3. `On-Hand Base` sütunu kaldırılsın (TR+USA toplamı zaten biliniyor).
4. `Fill to N` tek input yerine grup başına ayrı input olsun
   (örn. Base→100, Outdoor→50 girilebilsin).
5. "Fill to N" yerine daha görsel + daha net metin/görsel.

## Mevcut durum

- `get_entry_products` flat `items` döner; her item'da `kit_key`
  (`base|outdoor|seat|screws`), `avail_tr`, `stock_usa`, `fill_base` var.
- Tab 1 satırları `procurement_plan.js::_renderEntry` ile düz tabloya basılır:
  Code, Product, Kit badge, TR Avail., USA Stock, On-Hand Base, Qty.
- Tek global `.mpp-fill-n` + `_onFill`: `qty = max(0, N − fill_base)`.
- Capacity Plan grup başlığı görseli: `tr.group-row.group-<key>` içinde
  `div.group-title-badge` (ikon + başlık + `(N Parts)` + `BOM:` adı +
  Show/Hide butonu). Procurement Tab 2 (`_renderTree`) AYNI class'ları
  kullanıyor — Tab 1'de de aynı class'lar kullanılacak.
- Grup meta (sıra + başlık + ikon):
  base→"Base", outdoor→"Outdoor Parts", seat→"Seat Parts",
  screws→"Common Screws" (capacity KPI kartlarındaki isimler).
  İkonlar: `_groupIcon` map'i zaten var (cube/sun-o/wheelchair/wrench).

## Değişiklik

### `static/src/xml/procurement_plan.xml` (Tab 1)

- Başlık: "Enter quantities by group (TR+USA on-hand shown)".
- Toolbar: global Fill kaldır; `Clear` + `Calculate tree + cost` kalır.
  Kısa bilgi notu: auto-fill her grup başlığındadır.
- thead: Code, Product, TR Avail., USA Stock, Qty (5 sütun).
  `tbody.mpp-entry-body` JS tarafından doldurulmaya devam eder.

### `static/src/js/procurement_plan.js`

- `ENTRY_GROUPS` meta: sıra `[base, outdoor, seat, screws]`, başlıklar yukarıdaki.
- `this.fillN`: sayı → grup-key'li obje `{base:50, outdoor:50, seat:50, screws:50}`
  (her grubun son girdiği değer hatırlanır).
- `this.collapsedEntry = {}`: grup başlığındaki Show/Hide için
  (Tab 2'deki `collapsedGroups` deseninin aynısı).
- `_renderEntry`: item'ları `kit_key`'e göre grupla; her grup için Tab 2 ile
  AYNI başlık HTML'i (`group-row` + `group-title-badge` + ikon + `(N Parts)` +
  `(N Parts)` + Show/Hide; `BOM:` adı YOK — entry payload'unda bom adı
  gelmiyor, JS'e ürün adı hardcode edilmedi). Başlığın sağına grup içi
  auto-fill kontrolü:
  `[magic-icon] Base'i otomatik doldur: [___] [Apply]` + tooltip
  "Qty = hedef − (TR on-hand + USA on-hand), rezervler yok sayılır".
  Bilinmeyen `kit_key` gelirse sona ayrı grup olarak basılır (çökme yok).
- Satır HTML'i: Kit badge hücresi + On-Hand Base hücresi silinir (5 sütun).
- `_onFill`: tıklanan butonun `data-group`'una göre SADECE o grubun
  satırlarına uygular; `qty = max(0, ceil(N − fill_base))` formülü aynı.
- Metinler `_t()` ile sarmalanır (mevcut JS i18n deseni).
- Uyarı mesajındaki "(or use Fill to N)" ifadesi
  "(or use a group auto-fill)" olarak güncellenir.

## Python değişikliği

YOK. Gruplama client-side (`kit_key` zaten `get_entry_products` çıktısında var).
Server `tree_groups` başlıklarına dokunulmaz.

## Doğrulama

1. `node --check` (yoksa `python` ile basit syntax gözden geçirme) + QWeb XML
   `xml.dom` parse kontrolü (scratch'te, geçici).
2. Gruplama mantığının saf-JS simülasyonu: 4 grup sırası, bilinmeyen key,
   boş grup, per-group fill matematiği (rezerv hariç).
3. Odoo 15 kuralı: legacy `odoo.define` + `AbstractAction` deseni korunur,
   yeni OWL2/`list`/`privilege_id` YOK; `msp-`/`group-` CSS class'ları aynen
   reuse edilir (yeni SCSS gerekmez).

## Deploy notu

`static/` değişikliği de Git Deploy ister; browser'da `?debug=assets` /
sert yenileme gerekebilir. Mesai dışı + backup kuralı aynen geçerli.
