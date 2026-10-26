# Batch Belge No Otomatik Kopyalama (BATCH x_docno -> RES document_number)

Tarih: 2026-10-26 | Durum: Studio staging'de CANLI + testli; modul KODLANDI +
  review OK, commit/deploy BEKLIYOR

## Sorun

- RES transferleri (Resupply Subcontractor, sequence RES) tedarikciye gonderilirken
  `document_number` (Belge No) bossa dogrulama "belge no giriniz" uyarisi veriyor.
- Batch (stock.picking.batch) ekraninda Studio alani `x_docno` (Doc No/Belge No) var,
  transferlerde `document_number` (`l10n_tr_account_document_stock` modulu) var.
- Mevcut akis 2 tik: `x_docno` yaz -> Actions > "Belge No Kopyala" (id 1243, TUM
  pickinglere yazar) -> Dogrula. Istek: Dogrula oncesi otomatik aktarim.

## Kararlar (kullanici, 2026-10-26)

- Yol: once Studio (deploy'suz), sonra modul (kalici).
- Kapsam: `done`/`cancel` haric TUM transferler (revizyon 2026-10-26: once sadece
  `assigned` idi, Dogrula diger RES'lerin belgesini de kontrol ettigi icin genisletildi).
- Dolu `document_number` uzerine yazilir.
- `x_docno` bossa otomasyon sessiz gecer (dogrulamadaki cekirdek uyari korunur).

## Adim 1: Studio (staging -> prod)

- `base.automation` (on_write, model stock.picking.batch, filter
  `[('x_docno','!=',False)]`), bagli server action `state=code`:
  `x_docno` strip edilip `done`/`cancel` haric tum pickinglere
  `write({'document_number': docno})` yapar. Dongu plain (safe_eval guvenli,
  lambda yok). Staging `base.automation` id 10 olarak kurulu + testli.
- Test: staging BATCH/00002 (1 assigned 4357 + 2 confirmed). Ayni degeri yeniden
  yaz -> otomasyon tetiklenir -> 3/3 `document_number` doldu (revizyon sonrasi
  PASS). Dogrula testi YOK (2 confirmed yuzunden standart "waiting for goods"
  hatasi verebilir; once Check Availability + confirmed temizligi gerekir).
- Prod'a tasima: Studio UI'dan ayni kayit elle acilir (ID'ler ortama ozel
  olabilir; kod birebir kopyalanir) VEYA staging dogrulamasi sonrasi MCP ile.

## Adim 2: Modul (kalici, `matia_stock_planning`)

- Yeni dosya `models/stock_picking_batch_docno.py`:
  `_inherit = 'stock.picking.batch'`, `action_done` override:
  `super()` oncesi ayni kopyalama (guard: `'x_docno' in self._fields` ve
  `'document_number' in picking._fields`; `ensure_one` YOK, cekirdek zaten koyuyor).
- Manifest `depends` += `stock_picking_batch` (acik bagimlilik; ikisi de kurulu,
  yeni kurulum yok). `l10n_tr_account_document_stock` depends'e EKLENMEZ
  (guard yeterli; agir TR paketine bagimlilik istenmiyor).
- Studio otomasyonu modul deploy sonrasi PASIFLESTIRILIR (cift yazim onlenir).
- DURUM 2026-10-26: kodlandi (`models/stock_picking_batch_docno.py`,
  `action_done` override + `_msp_copy_docno_to_pickings`, `_fields` guard'li,
  best-effort + `_logger.exception`), manifest 15.0.2.10.11 + depends
  `stock_picking_batch`, `py_compile` OK, odoo-reviewer KRITIK YOK (2 dusuk
  uygulandi: exception log + guard hoist). Commit/push + deploy BEKLIYOR.
- Deploy: Git Deploy + servis restart (mesai disi + backup) + modul Upgrade;
  `button_immediate_upgrade` YETMEZ (Python). Once staging dogrulama.
- odoo-reviewer denetimi + py_compile sart; commit/push kullanici onayiyla.

## Notlar

- `x_docno` Studio alanidir (modules bos); modul kodu `_fields` guard ile okur.
- `document_number` char, `x_docno` text -> strip sart (newline sizmasin).
- Batch `action_done` cekirdegi `assigned`/`confirmed` disinda state varsa hata
  verir; stok ayrilmamis pickinglerde Immediate Transfer sihirbazi acilabilir.
  Kopyalama availability kontrolunu atlamaz.
