# Bottom-up Producible (Production Plan, 2026-10-06)

## Problem
Production `Producible` sütunu dal-bazında kendi stokunu gösteriyordu:
üst satırlar `floor(avail_TR/1.0)` (bom_qty sabit 1.0 kodlu), alt satırlar
`floor(avail/bqty)`. Capacity `floor(max(0,onhand-reserved)/bom_qty)` TR+USA
canlı hesaplıyor. Üç fark: kapsam (TR-only vs TR+USA), bölme (bölmeme vs
bom_qty), zaman (snapshot vs canlı). Kullanıcı E2CBAN02 örneğiyle bottom-up
mantığı önerdi, doğrulandı.

## Karar verilen formül (display-only, satınalma matematiğine dokunmaz)
- `pool(X) = own(X) + min_C floor(pay(C->X) / kullanim(X,C))`
- `pay(C->P) = pool(C) * katki[P->C] / toplam_girdi(C)`
- `katki[P->C]` = P'nin NET cascade değeri × kullanım (cascade zaten dağıtıyor,
  satır 427-431; tek ek kenar-bazında kayıt).
- `toplam_girdi(C)` = cascade sonrası `demand[C]` (hedef tohumu + ebeveyn
  katkıları). Yaprak: `pool = own`.
- Phantom: own = 0 (stok tutmaz, cascade ile tutarlı), çocuklardan geçirir.
- Ters-topo tur (Kahn `topo` listesi ters): çocuklar ebeveynden önce kesinleşir.
  O(V+E), sıfır ek DB sorgusu, özyineleme yok (derinlik/döngü koruması:
  patlama zaten `level > _MPP_MAX_LEVEL=10` + path-tabanlı cycle check yapıyor).
- Politika notu: paylaşımlı çocuk NET-talep ağırlıklı bölünür (brüt değil —
  kendini kaba-töyle kapatan ebeveyn pay kapmaz). floor artığı ebeveynde kalır
  (ileride largest-remainder düşünülebilir). Capacity sayfası dışarıda (hedef/
  cascade yok; faz-2'de sanal talep opsiyonu).

## Depolama
- Yeni alan `matia.procurement.plan.producible_json` (Text):
  `{"pool": {"pid": float}, "branch": {"P>C": int}}`.
- `action_explode_and_net` cascade sonrası hesaplar, `edge_json` yanına yazar.
- Önbellekli görünüm (`built_target_json` eşleşince rebuild yok) saklanan
  alandan okur — ceil'li `net_qty`'den geri-hesap yok (hassasiyet kaybı olurdu).
- Eski plansız/p//oolsuz plan + plansız sub-BOM çağrısı: eski formüle düşer.

## Görüntü eşleşmesi
- Üst satır (`_plan_summary`): `floor(pool[pid])`, yoksa `floor(avail)`.
- Alt satır (`get_sub_bom_cost`, parent P biliniyor): `branch[(P,C)]`, yoksa
  `floor(avail/bqty)`. Dal numarası = o ebeveyne ayrılan payın karşıladığı
  P adedi; ebeveyn pool'u bunların min'i + own.
- Excel (`controllers/procurement_export.py`) aynı satırları okur — otomatik
  tutarlı, değişiklik yok. JS `_producible` fallback'ına `max(0)` guard.

## Doğrulama
- `py_compile` + algoritma replikası `scratch/` içinde E2CBAN02 gerçek
  verisiyle (staging salt-okunur): beklenen bottom-up toplamla karşılaştır.
- Deploy: Python değişikliği → Git Deploy + Upgrade/restart (mesai dışı +
  backup); JS tek başına olsaydı Upgrade yeterdi ama bu Python.
