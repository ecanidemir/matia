# Production Auto-Fill Gross-Want Fix (2026-10-06)

## Sorun
Auto-fill `Needed = N - avail` yaziyor, rebuild cascade'i stoktan bir kez daha
dusuyordu (`net = demand - avail`, `matia_procurement_plan.py:820`).
`0 < avail < N` olan her satir avail kadar eksik siparis uretiyordu;
paylasimli parcada satir "50" gosterirken gercek havuz ihtiyaci daha buyuktu.
Ayrica satirsiz top'larda client avail 0 okudugu icin 60 siskinligi oluyordu.

## Degisiklik (2 dosya, kucuk)
- `static/src/js/procurement_plan.js::_onNeedFill`: `needMap[pid] = N`
  (brut istek; stok okuma kaldirildi). Toast + grup tooltip + Needed/Planned
  baslik title'lari yeni anlami anlatir.
- `models/matia_procurement_plan.py::get_tree_with_cost`: satirsiz kit
  top'lari icin tek bulk `_mpp_stock_split` ile CANLI stok (TR/US unreserved);
  `planned` yorumu guncellendi (satirsiz fallback = kendi agac neti;
  satir varsa client cascade net'i tercih eder).

## Anlam sozlesmesi (kullaniciya anlatim)
- Needed = brut istek (girilen N). Planned = havuzlanmis net
  (brut + diger ebeveynlerin net tuketimi - TR+US stok).
- Siparis karari Planned'dan okunur; paylasim `Also used in` notunda gorunur.

## Dogrulama
- `python -m py_compile` OK, `node --check` OK.
- `scratch/test_autofill_gross.py`: 5 senaryo (paylasimsiz 0/10/250 stok,
  paylasimli 10/250 stok) — NEW formulu 5/5 havuz gercegiyle esit;
  OLD formulu 3 senaryoda avail kadar eksik (biri siparisi tamamen yok ediyor).

## Deploy (insan adimi)
1. Commit + push (bu branch; push YOK — direkt istenmeden pushlama).
2. Staging odoobulut panelinden Git Deploy + Upgrade/restart
   (mesai disi + oncesi backup). `button_immediate_upgrade` YETMEZ.
3. Sonrasi browser Ctrl+F5 (JS bundle).
4. Dogrulama (staging MPP-0004): Screws grubuna 60 + Apply ->
   tum satirlar Needed 60; Recalculate sonrasi stok fazlasi satirlar
   Planned OK/0, gercek aciklar (orn. 2418) Planned 60; paylasimli
   satirda Planned >= Needed (havuz toplami).
