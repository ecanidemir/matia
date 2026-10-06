# Production Plan Slot Kayit Sistemi (0-9)

## Hedef (kullanici karari, 2026-10-06)

- 50 / 100 / 150 / 200 gibi farkli hedeflerle calisilacak; tek ekranda cok sutun
  acmak Odoo'yu yorar endisesiyle her calisma AYRI kaydedilip tek tek acilacak,
  Excel raporu calisma bazinda alinacak.
- DB'ye en fazla 10 calisma kaydedilip acilabilecek; her kaydin sabit id'si
  0..9 olacak. Ornek kullanim: "0 ve 3 nolu plani tek excelde ver" (bu karsilastirma
  AYRI bir gelistirme, bu planda sadece kayit kismi yapilir).
- Secici: header dropdown. Isimlendirme: sadece kod (MPP sirasi + slot no).

## Tasarim

- Yeni model YOK. `matia.procurement.plan` uzerinde yeni alan:
  `slot = fields.Integer(default=-1)`; -1 = eski/slotsuz plan (legacy, dokunulmaz).
  `_sql_constraints` ile aralik denetimi (`CHECK(slot >= -1 AND slot <= 9)`,
  Odoo 15 tuple formati). DB unique YOK (staging'de cift isimli kayitlar var;
  kodda slot basina `order='id desc', limit=1` ile en yenisi kullanilir).
- Slot'a kaydetme = o slotun planina `target_json` yazma + `get_tree_with_cost`
  ile rebuild (mevcut `set_targets_and_rebuild` mantigi aynen; satir snapshot'lari
  planda durur, ilerideki slot-karsilastirma Excel'i ayni veriyi okur).
- Server metodlari (JS'ten `model/method/args` ile cagrilir; `ensure_one` YOK):
  - `get_slot_list()` -> 10 girdi: `{slot, plan_id, name, state, target_count,
    write_date}`; bos slot `plan_id=False`.
  - `load_slot(slot)` -> slot plani yoksa bos plan acar (sequence adi + slot),
    `get_tree_with_cost` doner + `slots` + `active_slot` enjekte edilir.
  - `save_slot(slot, targets)` -> bul/yeni olustur, hedefleri temizle
    (mevcut `set_targets_and_rebuild` temizligi), yaz + rebuild doner.
  - `get_startup_tree()` -> en son yazilan slot planini acar (slot >= 0,
    `order='write_date desc'`); slot plani yoksa legacy davranis
    (en son plan). Sonuca `slots` + `active_slot` eklenir.
  - `_plan_summary` ek anahtarlar: `slot`, ayrica agac sonucu
    `active_slot`; `slots` listesi agac ozetlerine eklenir (RFQ override
    `super()` cagirdigi icin anahtarlar korunur).
- Client (sadece procurement dosyalari; Capacity'ye DOKUNULMAZ):
  - Header'a slot bari: `<select class="mpp-slot-select">` (secenekler kisa:
    `Slot 0` .. `Slot 9`, MPP kodu gosterilmez) + `Save` butonu (aktif
    needMap'i secili slota yazar) + kisa durum rozeti (`Slot N`, bosta
    `Slot N - empty`). MPP kodu yalniz uzerine-yazma onay mesajinda gecer.
  - Slot degisimi -> `load_slot` + `_applySummary` + render (tum tablolar).
  - Save -> `save_slot(secili_slot, needMap)` + bildirim + dropdown tazeleme.
  - `_applySummary` `slots`/`active_slot` saklar; `_planId` aynen plan id doner
    (Excel/RFQ/MO akislari degismez, aktif slotun planini kullanir).
- Kaydedilmeyen degisim: input focus'tayken (blur olmadan) slot degistirilirse
  yazilmamis deger kaybolur; blur zaten otosave yapar (`set_targets_and_rebuild`
  aynen durur). Ek onay diyologu YOK (sadelik karari).

## Sinirlar / kurallar

- Slot basina tek plan (en yeni gecerli); ayni slot'a kaydetme uzerine yazar,
  satirlar rebuild edilir (RFQ/MO linkli planin uzerine yazma uyarisi client'ta
  gosterilir: `rfq_count > 0` ise Save oncesi `confirm`).
- 10 slot sabittir; artirim isterse `9` sabiti + CHECK degisir (ileride).
- Karsilastirma Excel'i (slot 0 vs 3 tek dosyada) bu isin DISINDA; veri modeli
  (slot + target_json + line snapshot) ona hazirdir.

## Dogrulama

- `py_compile` + `node --check` + case-sensitive TR-karakter taramasi (0).
- Staging'de: slot 0'a 50, slot 1'e 100 yaz -> reload -> dropdown'da ikisi de
  gorunur -> her birini acip Excel al -> degerler korunur.
- Deploy: Python var -> Git Deploy + Upgrade/restart (mesai disi + backup).
