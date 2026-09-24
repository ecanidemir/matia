/**
 * MENÜ VE AÇILIŞ
 * E-Tablo açıldığında özel menü oluşturur.
 */
function onOpen() {
  SpreadsheetApp.getUi().createMenu('🔄 MATIA')
    .addItem('📂 SolidWorks CSV Yükle', 'showCSVImportDialog')
    .addSeparator()
    .addItem('📥 Odoo BOM Çek (ID: ' + CONFIG.odoo.targetBomId + ')', 'fetchOdooBOM')
    .addItem('📦 Toplu Stok Analizi (Common/Outdoor/Seat)', 'calculateMultiBOMStock')
    .addSeparator()
    .addItem('🔍 Karşılaştır (SW ↔ Odoo)', 'compareBOMs')
    .addSeparator()
    .addItem('📤 Odoo\'ya Geri Yaz', 'pushToOdoo')
    .addItem('📥 SW Güncelleme CSV İndir', 'showCSVExportDialog')
    .addSeparator()
    .addItem('⚙️ Ayarları Kur', 'setupSettings')
    .addToUi();
}
