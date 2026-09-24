/**
 * CSV DIŞA AKTARMA MODÜLÜ
 * KARSILASTIRMA veya ODOO_BOM sayfasındaki verileri CSV olarak indirir.
 * SolidWorks ImportProperties makrosu bu CSV'yi okuyarak Custom Properties günceller.
 */

/**
 * CSV export diyaloğunu açar.
 */
function showCSVExportDialog() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();

  // Aktif sayfayı veya SW_BOM sayfasını kullan
  const activeSheet = ss.getActiveSheet();
  const validSheets = [CONFIG.sheets.swBom, CONFIG.sheets.odooBom, CONFIG.sheets.comparison];
  const sheetName = validSheets.includes(activeSheet.getName()) ? activeSheet.getName() : CONFIG.sheets.swBom;

  const sheet = ss.getSheetByName(sheetName);
  if (!sheet || sheet.getLastRow() < 2) {
    SpreadsheetApp.getUi().alert("İndirilecek veri bulunamadı. Sayfa: " + sheetName);
    return;
  }

  // Veriyi oku
  const lastRow = sheet.getLastRow();
  const lastCol = sheet.getLastColumn();
  const data = sheet.getRange(1, 1, lastRow, lastCol).getValues(); // Başlık dahil

  // CSV String oluştur (noktalı virgül ayraçlı)
  let csvString = "";
  data.forEach(row => {
    const sanitizedRow = row.map(cell => {
      let val = String(cell);
      if (val.includes(";") || val.includes("\n") || val.includes('"')) {
        return '"' + val.replace(/"/g, '""') + '"';
      }
      return val;
    });
    csvString += sanitizedRow.join(";") + "\r\n";
  });

  // UI hazırla
  const timestamp = Utilities.formatDate(new Date(), "Europe/Istanbul", "yyyyMMdd_HHmm");
  const fileName = sheetName + "_Export_" + timestamp + ".csv";

  const htmlTemplate = HtmlService.createTemplateFromFile('CSVExporterUI');
  htmlTemplate.csvData = Utilities.base64Encode(csvString, Utilities.Charset.UTF_8);
  htmlTemplate.fileName = fileName;

  const html = htmlTemplate.evaluate()
    .setWidth(380)
    .setHeight(160);

  SpreadsheetApp.getUi().showModalDialog(html, '📥 CSV Olarak İndir — ' + sheetName);
}
