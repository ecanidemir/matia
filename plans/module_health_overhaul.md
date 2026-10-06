# Module Health Overhaul — matia_stock_planning (Odoo 15)

Tam kapsamlı tek seferlik sağlık revizyonu. Hedef: bug = 0, ölü kod = 0,
sade + stabil + hızlı modül. Süre sınırı yok, detay öncelikli.
Çalışma `chore/module-health-overhaul` branch'inde, faz başına commit.
Push YOK, canlı DB'ye write YOK, staging/deploy aksiyonu YOK
(bunlar insan adımı olarak raporlanır).

## Faz 0 — Hazırlık (okuma, dokunma yok)

1. `AGENTS.md`, `.agents/rules.md`, `.agents/memory/HOT.md`,
   `docs/discovery.md` dosyalarını oku.
2. Skill yükle: `odoo-15` (zorunlu, tüm fazlarda referans).
3. Envanter çıkar: dosya listesi + satır sayısı + her Python
   metodunun imzası + her JS metodunun listesi + tüm RPC
   çağrılarının iki yönlü tablosu (JS metodu -> Python metodu,
   argüman sırası dahil).
4. `git checkout -b chore/module-health-overhaul` (main güncel
   kabul edilir, pull/rebase YOK — insan onaylı base).

## Faz 1 — Bug avı (skill: systematic-debugging + odoo-15)

Her dosya satır satır, her bulgu dosya:satır not edilir:

- Python: `None`/False/0 kenar durumları, `search` limit'siz
  sorgular, `browse` sonrası `exists()` kontrolü, `read()` ile
  dönen `False` ilişkiler (`x[0]` patlar), tarih/saat naive vs aware,
  `round()` yerine `res.currency` yuvarlaması, `math.ceil` öncesi
  float gürültüsü, `ensure_one` eksikleri, `UserError` yerine ham
  exception sızıntısı, `sudo` kapsamı (gereksiz sudo = yetki deliği,
  eksik sudo = erişim hatası), `_sql_constraints`/`@api.constrains`
  tutarlılığı, `copy()`/`write()` sözlük anahtarları.
- Odoo 15 yasakları: `list` view, `privilege_id`,
  `models.Constraint/Index`, OWL2, `env.sudo()`, JSON-2 — hiçbiri
  olmamalı; `tree`/`category_id`/`_sql_constraints`/OWL1 doğrulanır.
- Her şüpheli alan/metod adı `fields_get` veya küçük `search_read`
  ile canlıdan doğrulanır (salt-okunur, write tool'ları YASAK).
- JS: RPC argüman sırası Python ile birebir mi, `undefined`/`null`
  girişler, `parseFloat(NaN)` yolları, olay delegasyonu
  sızıntıları, sıralama/filtre durum tutarlılığı, template'e
  yazılan her değişkenin JS'te tanımlı olması (ve tersi).
- XML: parse + template ID çakışması (capacity ile `msp-` vs
  procurement `mpp-` prefix ayrımı), `groups` kısıtları, menu/action
  referans bütünlüğü, manifest `data` sırası
  (csv -> security xml -> views -> data).
- Bulunan her bug systematic-debugging akışıyla (hipotez ->
  kanıt -> düzeltme -> doğrulama) kapatılır; düzeltilen dev hatası
  `log_error` ile kaydedilir.

## Faz 2 — Ölü kod + sadeleştirme (skill: odoo-15)

- Kullanılmayan metot/değişken/import/parametre (JS'te çağrılmayan
  Python metodu dahil), yoruma gömülmüş kod blokları, çift
  yazılmış mantık (örn. TRY/USD rollup tekrarı, RFQ gruplama
  tekrarı, export/UI kolon listesi tekrarı) tek yardımcı metoda
  indirgenir. Davranış değişikliği YOK, sadece temizlik.
- `_(...)` çeviri kapsaması: kullanıcıya görünen her string
  sarılır; Türkçe karakterli ham string kalmaz.
- Sabit değerler (şirket ID, lokasyon ID, oran) adlandırılmış
  sabite taşınır, açıklaması yazılır.
- Faz sonunda modül satır sayısı ve tekrar oranı raporlanır.

## Faz 3 — Stabilite (skill: test-driven-development uyarlanmış)

- Çalışan Odoo runtime'ı yok; onun yerine her public metod için
  `plans/module_health_overhaul.md` Ek-A'ya sözleşme tablosu
  yazılır: girdi -> beklenen çıktı -> kenar durum davranışı.
  Her satır koddan doğrulanır, varsayım yazılmaz.
- RPC sözleşme tablosu (Faz 0) JS ve Python'a karşı son kez
  doğrulanır; uyumsuzluk bug sayılır (Faz 1'e döner).
- `ir.model.access.csv` denetimi: her modele gereken minimum
  yetki, fazlası kısılır.
- Hata mesajları kullanıcı dilinde netleştirilir (teknik traceback
  kullanıcıya sızmaz, log'a düşer; `print`/`console.log` kalmaz).

## Faz 4 — Performans

- Her Python metodunun DB tur sayısı statik olarak sayılır;
  döngü içi `search/read` (N+1) toplu okumaya çevrilir,
  `read_group`/`search_read` tercih edilir, gereksiz `search([])`
  kaldırılır.
- JS: ağaç render tek string + tek DOM yazımı korunur, arama
  input'una debounce, gereksiz RPC zinciri kısaltılır.
- Asset kontrolü: kullanılmayan scss/xml parçası bundle'dan düşer.
- Beklenen kazanç her değişiklikte not edilir (tur sayısı
  önce/sonra).

## Faz 5 — Doğrulama + kapanış (skill: verification-before-completion,
  git-workflow, error-memory)

1. `python -m py_compile` (tüm py), `node --check` (tüm js),
   XML parse (tüm xml), manifest import sırası gözden geçirme.
2. `@odoo-reviewer` subagent ile salt-okunur final denetim;
   bulguları kapatılmadan bitirme.
3. Faz başına conventional-commit (`chore(stock-planning): ...`),
   push YOK.
4. `powershell -File scripts/lint_error_log.ps1` temiz olmalı;
   kalıcı bulgular `docs/discovery.md` sonuna eklenir.
5. Rapor: `plans/module_health_report.md` — düzeltilen bug listesi
   (dosya:satır + kök neden), silinen ölü kod, sadeleştirme,
   performans kazançları, İNSAN ADIMLARI (staging deploy, upgrade,
   canlı test senaryoları, push kararı).

## Ek-A — Sözleşme tablosu şablonu

`| Metod | Girdi | Beklenen çıktı | Kenar durum | Doğrulandı |`

## Ek-A (dolduruldu — Faz 3)

Tüm satırlar kod okumasıyla doğrulandı; Capacity satırları salt-okunur
(`stock_planning.*` dosyasına dokunulmadı).

| Metod | Girdi | Beklenen çıktı | Kenar durum | Doğrulandı |
|---|---|---|---|---|
| `matia.procurement.plan.get_entry_products()` | — | Entry ürün listesi (product, code, hedef adet) | Kayıt yoksa `[]` | Faz 0 kod okuma |
| `create_plan(items)` | `[{product_id, target_qty}]` | Yeni plan id | Boş/geçersiz items → UserError | Faz 0 kod okuma |
| `action_explode_and_net(plan_id)` | plan id | BOM patlatma + net ihtiyaç satırları | Cycle/phantom → guard ile durur, clamp ≥ 0 | Faz 1 kod okuma |
| `action_assign_suppliers(plan_id)` | plan id | Seller + fiyat + UoM ataması | Kur yok → ürün-adlı UserError (Faz 3 helper); fiyat yok → 0 + uyarı | Faz 2-4 edit + gözden geçirme |
| `get_tree_with_cost(plan_id)` | plan id | USD/TRY rollup'lu ağaç (satırlar hedeflerle aynıysa önbellekten: yeniden patlatma yok, RFQ/MO izleri korunur) | TRY kuru yok → satır 0.0 + log warning | Faz 1 + Faz 3 log + performans paketi |
| `get_sub_bom_cost(product_id, parent_qty, plan_id=False)` | ürün, üst adet, opsiyonel plan | Alt-BOM maliyet kırılımı | BOM'suz ürün → alt satırsız kendi satırı | Faz 0 kod okuma |
| `get_supplier_summary(plan_id)` | plan id | Tedarikçi grupları + TR/US toplamlar | Atanmamış satırlar ayrı listelenir | Faz 0 kod okuma |
| `action_create_supplier_rfq(plan_id, seller_id, company_id, confirm)` | plan, seller, company, onay | PO listesi veya `needs_confirm` | Mevcut draft + onaysız → `needs_confirm`; uygun satır yoksa UserError | Faz 0 (rfq dosyası okuma) |
| `get_rfq_preview(plan_id)` | plan id | Oluşacak RFQ grupları önizlemesi | UI'dan çağrılmıyor (public API korunuyor); yanlış state → UserError | Faz 0/2 |
| `action_create_draft_rfqs(plan_id, confirm)` | plan id, onay | Tüm tedarikçilere draft RFQ veya `needs_confirm` | UI'dan çağrılmıyor (public API korunuyor); yanlış state → UserError | Faz 0/2 |
| `action_create_mos(plan_id, line_ids=None)` | plan id, opsiyonel satırlar | Oluşan MO listesi | Uygun make satırı yoksa UserError | Faz 0 kod okuma |
| `stock.planning.get_capacity_planning_data(...)` | company bayrakları + dynamic_targets | Grup/item listesi (Capacity) | DOKUNULMAZ — sözleşme bilgisi amaçlı | Faz 0 kod okuma |
| `get_sub_bom_details(...)` | ürün + üst adet + bayraklar | Alt-BOM detay satırları (Capacity) | DOKUNULMAZ | Faz 0 kod okuma |
| procurement `export_xlsx` | `type=tree\|suppliers` + payload | xlsx/csv dosyası | Yetkisiz → erişim hatası; boş payload → boş dosya | Faz 2 edit + grep |
| capacity `export_xlsx` (main.py) | client verisi | xlsx/csv dosyası | DOKUNULMAZ (auth=user, client-verisi only) | Faz 0 kod okuma |

### ACL denetimi (Faz 3)

`security/ir.model.access.csv`: procurement modelleri yalnız
`base.group_system` (sistem yöneticisi). Menü `groups` + export route
yetki kontrolüyle tutarlı — tasarım gereği admin-only, kısılacak fazla
yetki yok, değişiklik yapılmadı.
