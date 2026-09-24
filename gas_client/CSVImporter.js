/**
 * CSV İÇE AKTARMA MODÜLÜ
 * SolidWorks VBA makrosu tarafından oluşturulan CSV dosyasını okur ve SW_BOM sayfasına yazar.
 */

/**
 * Dosya seçme diyaloğunu açar.
 */
function showCSVImportDialog() {
  const html = HtmlService.createHtmlOutputFromFile('CSVImporterUI')
    .setWidth(420)
    .setHeight(260);
  SpreadsheetApp.getUi().showModalDialog(html, '📂 SolidWorks CSV Yükle');
}

/**
 * HTML arayüzünden gelen CSV içeriğini işler ve SW_BOM sayfasına yazar.
 * @param {string} csvContent CSV dosya içeriği
 */
function processCSVImport(csvContent) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheetName = CONFIG.sheets.swBom;

  // Sayfayı bul veya oluştur
  let sheet = ss.getSheetByName(sheetName);
  if (!sheet) {
    sheet = ss.insertSheet(sheetName);
  }

  // CSV Parse (Noktalı Virgül Ayracı)
  const rows = parseCSV(csvContent, ";");

  if (rows.length < 2) {
    throw new Error("CSV dosyası boş veya geçersiz formatta!");
  }

  // İlk satır başlık, veri 2. satırdan başlar
  const dataRows = rows.slice(1);

  if (dataRows.length === 0) {
    SpreadsheetApp.getUi().alert("Dosyada veri bulunamadı.");
    return;
  }

  // Sayfayı temizle
  sheet.clear();

  // Başlıkları yaz (CONFIG'den)
  sheet.getRange(1, 1, 1, CONFIG.headers.length)
    .setValues([CONFIG.headers])
    .setFontWeight('bold')
    .setBackground('#1a73e8')
    .setFontColor('white');

  // Veriyi hazırla (9 sütuna normalize et)
  const targetValues = dataRows.map(row => {
    const rowData = new Array(CONFIG.totalColumns).fill("");
    for (let i = 0; i < CONFIG.totalColumns; i++) {
      if (i < row.length) {
        rowData[i] = row[i];
      }
    }
    return rowData;
  });

  // Sayfaya yaz (2. satırdan başla)
  if (targetValues.length > 0) {
    sheet.getRange(2, 1, targetValues.length, CONFIG.totalColumns).setValues(targetValues);
    SpreadsheetApp.flush();

    // Görünüm ayarları
    sheet.setFrozenRows(1);
    sheet.autoResizeColumns(1, CONFIG.totalColumns);

    // --- SIRALAMA VE RENKLENDİRME ---
    sortAndColorSheet(sheet, targetValues);
    // ---------------------------------

    ss.toast(targetValues.length + " satır başarıyla SW_BOM sayfasına yüklendi.", "✅ Tamamlandı");
  }
}

/**
 * CSV Parser — tırnak ve satır içi ayraçları destekler.
 * @param {string} str CSV içeriği
 * @param {string} delimiter Ayraç karakteri
 * @returns {string[][]} Satır ve sütun dizisi
 */
function parseCSV(str, delimiter) {
  const arr = [];
  let quote = false;
  let row = [];
  let col = '';

  for (let c = 0; c < str.length; c++) {
    let cc = str[c];
    let nc = str[c + 1];

    if (cc === '"') {
      if (quote && nc === '"') {
        col += '"';
        c++;
      } else {
        quote = !quote;
      }
      continue;
    }

    if (cc === delimiter && !quote) {
      row.push(col);
      col = '';
      continue;
    }

    if ((cc === '\r' && nc === '\n') || cc === '\n') {
      if (quote) {
        col += cc;
      } else {
        if (cc === '\r' && nc === '\n') c++;
        row.push(col);
        arr.push(row);
        row = [];
        col = '';
      }
      continue;
    }

    col += cc;
  }

  if (col !== '' || row.length > 0) {
    row.push(col);
    arr.push(row);
  }

  return arr;
}
