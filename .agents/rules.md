# Proje Kurallari (Project Rules) — Matia Odoo Hub

Bu projede (Odoo 15, XML-RPC) calisirken asagidaki kurallara **kesinlikle** uymalisin.

## 0. Discovery Dosyasi (ZORUNLU)

- **HER SEANS BASINDA** `docs/discovery.md` dosyasini oku. Bu dosyada sunucu hakkinda kalici bilgiler, bilinen hata desenleri ve cozumleri bulunur.
- Yeni bir sey kesfettiginde (yapi, hata, cozum), dosyanin sonuna ekle.
- Bu kurali kullaniciya hatirlatma. AI kendisi uygulayacak.

## 1. Baglanti ve Sorgulama

- **MCP once**: Tum Odoo sorgulamalari icin `odoo_matia_*` MCP araclarini kullan.
- **Failover**: MCP aracı basarisiz olursa, CLI'da Python script ile XML-RPC baglantisi dene (ilerde eklenecek).
- **Transport**: Odoo 15 XML-RPC kullanir. JSON-2'den asla bahsetme.

## 2. Guvenlik

- **Hassas Veriler**: API anahtarlari, sifreler asla koda gommeyin. `.env` dosyasindan okuyun.
- **Loglama**: Debug log'larinda `ODOO_PASSWORD` degerini ASLA yazdirma.
- **Yikici Islemler**: Modul kurma/kaldirma, veri silme, yapilandirma degisikligi yapmadan once kullaniciya sor.

## 3. Hata Analizi

- **Kullanici hata metni sagladiysa**: Once hata metnini analiz et, ardindan ilgili Odoo model/konfigurasyonunu sorgula.
- **SSH Yok**: Sunucu log'una, dosya sistemine erisim yok. Tum analiz Odoo API'si + kullanici sagladigi bilgilerle sinirli.
- **Odoo 15 API farklari**: Odoo 19'da calisan bir yontem Odoo 15'te calismayabilir. Ornegin `@api.depends_context` yoktur.

## 4. Dosya Yonetimi

- **Overwrite Yasa**: Mevcut dosyalara ASLA overwrite yapma. Once oku, sonra sonuna ekle.
- **Gecici Dosyalar**: Deneme script'lerini `scratch/` altinda tut. Proje kokunde veya `scripts/`'de cop birakma.

## 5. Kullanici Iletisimi

- Teknik terimleri aciklarken kullaniciya net bir dil kullan.
- "Bilgim yok" / "Yapamam" demek yerine cozum odakli ol.
- Bir islemin Odoo 15'te mumkun olup olmadigindan emin degilsen, once doku kontrol et, sonra cevapla.
