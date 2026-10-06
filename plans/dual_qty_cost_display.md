# Cift Gosterge: Uretim Adedi + Net Alim + Maliyet Baz Netligi (2026-10-06)

## Problem
P2CPAS32 ornegi: Need 60, US 6 hazir, Producible 9 (6+3), Planned 54.
Alt satirlar M3L2PB40 (net 51), P3CPPB29 (net 54), P3CPPS30 (net 34).
Kullanici itirazi (dogrulandi):
1. MO ile birlesen parcalarda operasyon maliyeti planda YOK (kodda acikca
   yaziyor, asagida). O 3 setin parcasi stokta; sadece montaj MO'su lazim.
2. Agac maliyeti 54 set uzerinden tam malzeme degeri gosteriyor; karar
   verici bunu "alinacak/siparis edilecek" tutar saniyor -> yaniltici.
3. Teklif: Planned 51 + MO sayfasinda 54, veya Needed 54/51 cift gosterim.

## Karar (ikinci secenek: cift gosterim, Planned 54 kalir)
- Planned 51'e CEKILMEZ. Tek `order_qty` hem RFQ'yu (`own x order`,
  `get_supplier_summary:2780`) hem MO'yu (`product_qty = order_qty`,
  `action_create_mos:3027`) besliyor. 51 yapilirsa ya MO 51'e duser
  (3 eksik uretim) ya da uretim/satinalma adedi diye iki alan acmak gerekir.
- Ayrica cascade `cocuk = ebeveyn neti x kullanim - avail` oldugu icin
  ust 51 olsaydi M3 brutu 54 degil 51 olur, neti 48'e duserdi; oysa 54'luk
  MO 54 set parca ister (3 stoktan, 51 yeni). 51, parca BRUTUNU de eksik
  gosterirdi.
- Zaten mevcut yapı duality'yi satir-seviyesinde kodluyor: ust 54 = uretim
  gercegi, alt netler (51/54/34) = satinalma gercegi. Eksik olan, ust satirda
  bunun tek bakista okunmamasi + maliyet bazlarinin etiketsiz karismasi.

## Gosterim degisikligi (display-only, cascade/RFQ/MO matematiğine dokunmaz)
- Ust satir rozeti: `54 uret / 51 net alim` (veya Needed kolonunda
  `60 -> acik 51`). `acik = max(0, gross - floor(pool))`: P2CPAS32'de
  60-9=51. Payload'da `gross` + `producible` zaten var -> Faz-1 saf JS.
- Maliyet kolonu netligi: mevcut `rolled_total = birim x gross`
  (1424/1426) yerinde kalir ama etiketi "brut/full deger (stok tuketimi
  dahil)" olur; yanina `net tutar = rolled_birim x order_qty` kolonu
  (artimsal alim degeri). Supplier ozeti zaten net PO-degeri, degismez.
- Operasyon maliyeti FAZ-2'ye birakilir (routing/workcenter okuma +
  birim-montaj bedeli; `mrp.routing.workcenter` "Montaj - dakika" kayitlari
  discovery'de kayitli). Faz-1'de make node katkisi 0 oldugu tooltip'te
  belirtilir.

## Dogrulama
- `py_compile` (Python degerse) + `node --check` (JS).
- `scratch/` replikası P2CPAS32 verisiyle: ust `54/51`, M3 `54 brut/51 net`,
  P3CPPS30 `54 brut/34 net`; RFQ toplamı ve MO adedi (54) DEGISMEDIGI
  assert edilir.
- Paylasimli cocukta `gross - pool` ile `order` farkli cikabilir; gosterim
  degeri `order`'i ezmez, sadece rozet bilgisidir (Excel'e rakamsal kolon
  olarak aynen tasinir).

## Deploy
- Faz-1 (saf JS + etiket): Upgrade yeterli, restart gerekmez; sonrasi Ctrl+F5.
- Faz-2'de Python alani (`open_qty`, net rolled, operasyon bedeli) eklenirse:
  Git Deploy + Upgrade/restart (mesai disi + backup). Commit/push YOK
  (kullanici onayi bekleniyor).
