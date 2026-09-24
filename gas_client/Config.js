/**
 * SİSTEM AYARLARI
 * Odoo bağlantısı, sayfa isimleri ve sütun yapısı konfigürasyonu.
 *
 * CSV Yapısı: 9 sütun (Parent, Child, Miktar + 6 Custom Property)
 * VBA makro (ExportBOM.vba) çıktısıyla uyumludur.
 */
const CONFIG = {
  // Odoo Bağlantı Bilgileri
  odoo: {
    url: 'https://matia.odoobulut.com',
    db: 'matia.odoobulut.com',
    username: 'enes@matiamobility.com',
    apiKey: PropertiesService.getScriptProperties().getProperty('ODOO_KEY'),
    targetBomId: 1707
  },

  // Sayfa (Sheet) İsimleri
  sheets: {
    swBom: 'SW_BOM',
    odooBom: 'ODOO_BOM',
    comparison: 'KARSILASTIRMA',
    settings: 'AYARLAR'
  },

  // SW CSV Sütun İndeksleri
  columns: {
    parentRef: 0,      // A - Üst Parça
    childRef: 1,       // B - Alt Parça
    qty: 2,            // C - Miktar
    uretimSekli: 3,    // D - uretim_sekli
    malzeme: 4,        // E - malzeme
    malzemeEbat: 5,    // F - malzeme_ebat
    altKod: 6,         // G - alt_kod
    revizyon: 7,       // H - revizyon
    tarih: 8           // I - tarih
  },

  // ODOO BOM Sütun İndeksleri
  odooColumns: {
    parentRef: 0,      // A - Üst Parça
    childRef: 1,       // B - Alt Parça
    qty: 2,            // C - Miktar
    bomType: 3,        // D - BOM Türü
    workcenter: 4      // E - Workcenter
  },

  // SW_BOM Sayfa Başlıkları
  headers: [
    'Üst Parça (Parent)',
    'Alt Parça (Child)',
    'Miktar',
    'uretim_sekli',
    'malzeme',
    'malzeme_ebat',
    'alt_kod',
    'revizyon',
    'tarih'
  ],

  // ODOO_BOM Sayfa Başlıkları
  odooHeaders: [
    'Üst Parça (Parent)',
    'Alt Parça (Child)',
    'Miktar',
    'BOM Türü',
    'Workcenter Adı'
  ],

  // Toplam sütun sayıları
  totalColumns: 9,
  odooTotalColumns: 5
};
