# RFQ Satir Kapsama (Line Coverage) — Suppliers Sekmesi

Istek (m0097, YILMAZER ornegi): RFQ butonlari satir seviyesinde kapsama
bakmali. Para-birimi split'i (2 RFQ: USD satir ayri) NORMAL, degismiyor.

## Davranis kurallari

1. Kapsama = plan satirinin ihtiyaci (order_qty), plana bagli IPTAL
   DISI PO'larin satirlarinda ayni urunle karsilaniyorsa covered.
2. Tum satirlar covered'sa supplier satirinda RFQ butonu CIKMAZ
   ("Covered" rozeti). Acik satir varsa buton cikar.
3. Buton/tahmini olusturma SADECE acik kisim icin RFQ acar
   (remaining qty) — "rfq butonu bunu tamamlayacak".
4. RFQ'da miktar dusurme / RFQ->PO sonrasi iptal otomatik algilanir
   (iptal PO kapsam disidir, buton geri gelir).
5. Manuel tasima (iptal RFQ'daki urunu diger RFQ'ya ekleme) ayni
   mekanizmayla algilanir: urun canli PO satirinda varsa covered.

## Server (Python var)

- Yeni helper `_rfq_coverage_map(env_sudo, plan)` (plan.py, @api.model):
  `plan.purchase_order_ids` (state != 'cancel') satirlarini
  (partner, company, product) bazinda toplar; her plan satiri icin
  `covered_qty` (satir UoM'una `_compute_quantity`, try/except —
  cevrilemezse o PO satiri sayilmaz = guvenli yon) + `remaining =
  max(0, order - covered)`. Epsilon 1e-9.
- KAPSAM KARARI (m0109, kullanici): URUN bazinda, plana bagli TUM
  RFQ/PO'lara bakilir (seller/company fark etmez — "tedarikcinin ismi
  degisebilir, onemli olan urun herhangi bir rfq ya da po'da var mi").
  Fully-covered -> BUTON GIZLENIR ("Covered" rozeti).
- GENISLETME (m0143, kullanici): sifirdan acilmis MANUEL PO'lar da
  sayilir. Sinir: plan.create_date ONCESI dokumanlar sayilmaz (plan
  netting'inden eski arz; yoksa yillar oncesinin PO'su her seyi
  kapatir). Plana bagli PO'da tarih siniri YOK. Bagli + global
  kesisimde cift sayim engellenir (linked_ids).
- TAKIP GORUNURLUGU (m0153, kullanici): kapsayan dokumanlar alt-satir
  RFQs hucresinde DOGUDAN listelenir ("in: PO-1, PO-2" + "+N more";
  tam liste title'da). Server `covered_docs: [{id, name}]` (max 5) +
  `covered_total` doner (`covered_by` string kaldirildi). Isim
  tiklamasi PO formunu yeni sekmede acar (`_onOpenPo`,
  `_onOpenProduct` deseni). Isimler JS'te escape'li.
- `_rfq_groups` (rfq.py): sadece remaining > eps satirlar gruba girer;
  PO satir qty + subtotal remaining uzerinden; bos grup duser.
  -> preview + 2 create action otomatik top-up uretir. `skipped`'e
  'covered' sayaci eklenir.
- `get_supplier_summary`: satirlara `covered_qty`/`remaining_qty`;
  supplier'a `open_line_count`/`covered_line_count`. Toplamlar
  DEGISMEZ (tahmin ayni kalir).
- `has_draft_rfq` / repeat-confirm aynen (draft varsa confirm sorar).
- `purchase_line_id`/`mo` tarafi degismez.

## Client (JS, procurement_plan.js)

- `_supplierRowHtml`: seller yok / admin degil dallari aynen; open==0
  ise buton yerine yesil "Covered" rozeti; open>0 ise buton + kucuk
  "x/y open" notu.
- `_supplierLinesHtml`: satirda mini "covered A / open B UoM" bilgisi
  (mevcut 6 kolon hizasi korunur).

## Test

- `py_compile` + `node --check` + odoo-reviewer (salt-okunur).
- scratch simulasyon: coverage map saf dilim (shipped fonksiyonlar
  exec), senaryolar: tam kapsama / kismi / iptal / UoM cevrim-hatasi.
- Canli dogrulama staging slot 5 (plan 30): mevcut RFQ + manuel
  tasima + miktar dusurme + iptal senaryolari.

## Deploy

- Python var -> odoobulut Git Deploy + restart (mesai disi + backup)
  + modul Upgrade + Ctrl+F5. NOT: onceki 4 commit (f14f6c2, df5b747,
  02a9974, 4a4bca2) hala deploy bekliyor — ayni pencere kullanilabilir.
- Commit/push SADECE kullanici "push et" dedikten sonra.
