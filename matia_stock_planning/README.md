# Matia TekRMD Stok & Kapasite Planlama Modülü (`matia_stock_planning`)

Bu modül, **Odoo 15** için geliştirilmiş olup, Stok (Envanter) menüsü altında TekRMD cihazı için BOM reçetelerini ve eldeki güncel stokları analiz eden etkileşimli bir kapasite planlama ekranı sunar.

## Temel Özellikler

1. **Reçete Bazlı Gruplandırma:**
   - **Base (Mavi):** `TekRMD Common Parts v2` (84 bileşen)
   - **Outdoor (Yeşil):** `TekRMD Outdoor Parts` (9 bileşen)
   - **Seat (Mor):** `TekRMD Seat Parts` (7 bileşen)

2. **Gelişmiş Lokasyon ve Çoklu Şirket Filtrelemesi:**
   - **TR Lokasyonları:** `WHTR/Stock/*` altındaki tüm internal stok konumları (149 lokasyon).
   - **USA Lokasyonları:** `WHUS/Stock/*` altındaki internal stok konumları.
   - **NCR Hariç Tutma:** `WHTR/NCR Alanı` ve `WHUS/NCR Storage` net stok hesabına katılmaz; sadece bilgi olarak ayrı sütunda gösterilir.
   - Tek tıkla sadece TR, sadece USA veya TR + USA birleşik hesaplama. En az bir konum seçilmesi zorunludur.

3. **Hesaplamalar ve Sütunlar:**
   - **Kullanım Miktarı:** Reçetedeki ihtiyaç adedi. İstenildiğinde tek tıkla gizlenebilir/gösterilebilir.
   - **Üretilebilecek Cihaz Sayısı:** `floor(stok_miktari / kullanim_miktari)`. Kritik darboğazlar renkli rozetlerle vurgulanır.
   - **20 Cihaz İhtiyacı:** `(20 * kullanim_miktari) - stok_miktari`. Stok yeterliyse yeşil `OK`, yetersizse eksik parça sayısı gösterilir.
   - **Dinamik Hedef Cihaz Sütunları:** Kullanıcı arayüzdeki `+ Hedef Sütunu Ekle` butonuyla en fazla 3 adet özel hedef cihaz sütunu (örn. 10, 50, 100, 200) ekleyebilir veya başlığındaki `[x]` butonu ile kaldırabilir.

4. **Birebir Excel (.xlsx) Dışa Aktarma:**
   - Ekranda o an hangi sütunlar görünüyorsa (gizlenen sütunlar hariç, eklenen dinamik sütunlar dahil) aynı renk ve yapıda Excel (.xlsx) olarak anında indirilir.

5. **Performans ve Hız:**
   - Tek bir `read_group` RPC çağrısıyla 103 tekil ürünün stokları milisaniyeler içinde çekilir.
   - Dinamik sütun ekleme ve parça arama anında tepki verir.

## Kurulum

1. `matia_stock_planning` klasörünü Odoo sunucusundaki `addons` dizinine kopyalayın.
2. Odoo arayüzünde Geliştirici Modunu (Developer Mode) açın.
3. **Uygulamalar > Uygulama Listesini Güncelle** yapın.
4. **Uygulamalar** menüsünde `matia_stock_planning` aratıp **Yükle (Install)** butonuna tıklayın.
5. Menüden **Stok > Cihaz Kapasite Planı** veya **Stok > Raporlama > TekRMD Cihaz Kapasitesi** seçeneğine tıklayarak kullanmaya başlayın.
