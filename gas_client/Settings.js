/**
 * AYARLAR SAYFASI
 * Odoo bağlantı bilgilerini ve hedef BOM ID'sini görüntüler/yönetir.
 */
function setupSettings() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheetName = CONFIG.sheets.settings;

  let sheet = ss.getSheetByName(sheetName);
  if (!sheet) {
    sheet = ss.insertSheet(sheetName);
  } else {
    sheet.clear();
  }

  // Başlık
  sheet.getRange("A1:B1").setValues([["⚙️ AYARLAR", ""]]).setFontWeight("bold").setFontSize(14);
  sheet.getRange("A1:B1").setBackground("#1a73e8").setFontColor("white");

  // Ayar Satırları
  const settings = [
    ["Odoo URL", CONFIG.odoo.url],
    ["Veritabanı", CONFIG.odoo.db],
    ["Kullanıcı", CONFIG.odoo.username],
    ["API Key", "(Script Properties'de saklanır)"],
    ["Hedef BOM ID", CONFIG.odoo.targetBomId],
    ["", ""],
    ["📋 DURUM", ""],
    ["Son BOM Çekme", ""],
    ["Son Karşılaştırma", ""],
    ["Son Odoo Yazma", ""]
  ];

  sheet.getRange(3, 1, settings.length, 2).setValues(settings);

  // Stil
  sheet.getRange("A3:A12").setFontWeight("bold").setBackground("#f3f3f3");
  sheet.getRange("B3:B7").setBackground("#e8f0fe");
  sheet.getRange("A9:B9").setFontWeight("bold").setBackground("#e6f4ea");

  // Sütun genişlikleri
  sheet.setColumnWidth(1, 200);
  sheet.setColumnWidth(2, 350);

  // Korumalı alanlar (API key satırı)
  const prot = sheet.getRange("B6").protect().setDescription("API Key - Değiştirilemez");
  prot.setWarningOnly(true);

  SpreadsheetApp.getActiveSpreadsheet().toast("Ayarlar sayfası kuruldu.", "✅ Tamamlandı");
}

/**
 * AYARLAR sayfasındaki son işlem tarihini günceller.
 * @param {string} field Alan adı ('Son BOM Çekme', 'Son Karşılaştırma', 'Son Odoo Yazma')
 */
function updateSettingsTimestamp(field) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(CONFIG.sheets.settings);
  if (!sheet) return;

  const timestamp = Utilities.formatDate(new Date(), "Europe/Istanbul", "dd.MM.yyyy HH:mm:ss");

  const fieldMap = {
    'Son BOM Çekme': 10,
    'Son Karşılaştırma': 11,
    'Son Odoo Yazma': 12
  };

  const row = fieldMap[field];
  if (row) {
    sheet.getRange(row, 2).setValue(timestamp);
  }
}
