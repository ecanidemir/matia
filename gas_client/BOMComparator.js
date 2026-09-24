/**
 * BOM KARŞILAŞTIRMA MODÜLÜ
 * SW_BOM ve ODOO_BOM sayfalarını karşılaştırır, farkları KARSILASTIRMA sayfasına yazar.
 *
 * Karşılaştırma alanları:
 *   - Parent_Ref, Child_Ref (eşleşme anahtarı), Miktar
 *   - alt_kod (akıllı karşılaştırma: Odoo BOM yapısından türetilir)
 *
 * alt_kod mantığı:
 *   - Parçanın Odoo BOM'unda tek alt parçası varsa → beklenen alt_kod = o parçanın kodu
 *   - Birden fazla alt parçası varsa → beklenen alt_kod = "N/A"
 *   - Alt BOM yoksa → beklenen alt_kod = "" (boş)
 */

/**
 * Ana karşılaştırma fonksiyonu — menüden çağrılır.
 */
function compareBOMs() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const ui = SpreadsheetApp.getUi();

  // Kaynak sayfaları al
  const swSheet = ss.getSheetByName(CONFIG.sheets.swBom);
  const odooSheet = ss.getSheetByName(CONFIG.sheets.odooBom);

  if (!swSheet || swSheet.getLastRow() < 2) {
    ui.alert("SW_BOM sayfası boş veya bulunamadı. Lütfen önce CSV yükleyin.");
    return;
  }

  if (!odooSheet || odooSheet.getLastRow() < 2) {
    ui.alert("ODOO_BOM sayfası boş veya bulunamadı. Lütfen önce Odoo BOM çekin.");
    return;
  }

  try {
    ss.toast("Karşılaştırma yapılıyor...", "🔍 Analiz", 30);

    const cols = CONFIG.columns;

    // 1. Verileri oku (Gizli kolonlar dahil olmak üzere tüm genişliği alır)
    const swData = readSheetData(swSheet, false);
    const odooData = readSheetData(odooSheet, true);

    // 2. Map'ler oluştur (Orijinal yapıları parse et, görsel kopyaları ignore et)
    const swMap = buildDataMap(swData, false);
    const odooMap = buildDataMap(odooData, true);

    // 3. alt_kod türetme — Odoo BOM yapısından
    const derivedAltKod = deriveAltKodFromOdoo(odooData);

    // 4. Karşılaştırma sayfasını hazırla
    const sheetName = CONFIG.sheets.comparison;
    let compSheet = ss.getSheetByName(sheetName);
    if (!compSheet) {
      compSheet = ss.insertSheet(sheetName);
    } else {
      compSheet.clear();
      compSheet.clearConditionalFormatRules();
    }

    // 5. Başlıklar (Yan Yana Karşılaştırma)
    const compHeaders = [
      'Odoo Üst Parça', 'Odoo Alt Parça', 'Odoo Miktar', 'Odoo alt_kod (türetilmiş)',
      'Durum',
      'SW Üst Parça', 'SW Alt Parça', 'SW Miktar', 'SW alt_kod'
    ];
    compSheet.getRange(1, 1, 1, compHeaders.length)
      .setValues([compHeaders])
      .setFontWeight('bold')
      .setBackground('#6d28d9')
      .setFontColor('white');

    // 6. Karşılaştırma yap
    const resultRows = [];

    // Tüm relation key'lerini topla (SW + Odoo birleşim kümesi)
    const allKeys = new Set([...Object.keys(swMap), ...Object.keys(odooMap)]);

    for (const key of allKeys) {
      const swEntry = swMap[key];
      const odooEntry = odooMap[key];
      
      const refObj = swEntry || odooEntry;
      const childRef = refObj.child;
      const parentRef = refObj.parent;

      const odooDerivedAltKod = derivedAltKod[childRef] !== undefined ? derivedAltKod[childRef] : '';

      const row = new Array(compHeaders.length).fill('');

      if (swEntry && odooEntry) {
        // Her iki tarafta da var — yan yana bas ve karşılaştır
        row[0] = parentRef;
        row[1] = childRef;
        row[2] = odooEntry.qty;
        row[3] = odooDerivedAltKod;
        // row[4] : Durum
        row[5] = parentRef;
        row[6] = childRef;
        row[7] = swEntry.qty;
        row[8] = swEntry.altKod;

        // Fark kontrolü
        const diffs = [];
        if (String(swEntry.qty) !== String(odooEntry.qty)) diffs.push('miktar');
        if (normalizeValue(swEntry.altKod) !== normalizeValue(odooDerivedAltKod)) diffs.push('alt_kod');

        row[4] = diffs.length > 0 ? '⚠️ Farklı (' + diffs.join(', ') + ')' : '✅ Eşit';
      } else if (swEntry && !odooEntry) {
        // Sadece SW'de var (Odoo bölgesi boş)
        row[4] = '➕ Sadece SW\'de';
        row[5] = parentRef;
        row[6] = childRef;
        row[7] = swEntry.qty;
        row[8] = swEntry.altKod;
      } else if (!swEntry && odooEntry) {
        // Sadece Odoo'da var (SW bölgesi boş)
        row[0] = parentRef;
        row[1] = childRef;
        row[2] = odooEntry.qty;
        row[3] = odooDerivedAltKod;
        row[4] = '➖ Sadece Odoo\'da';
      }

      resultRows.push(row);
    }

    // Sadece farklı olanları sayfaya yazmak için filtrele (Eşit olanları gizle)
    let hiddenEqCount = 0;
    const filteredRows = [];
    for (const r of resultRows) {
      if (r[4].startsWith('✅')) {
        hiddenEqCount++;
      } else {
        filteredRows.push(r);
      }
    }
    // Bundan sonra işlemlere sadece farklı olanlarla devam et
    resultRows.length = 0;
    resultRows.push(...filteredRows);

    // --- BOM TREE SIRALAMASI (DFS) ---
    const graph = {};
    const allChildrenInRows = new Set();

    resultRows.forEach(row => {
      // SW veya Odoo parent kolonlarındaki veriyi kullan (hangisi doluysa)
      const p = String(row[0] || row[5] || '');
      const c = String(row[1] || row[6] || '');
      if (!graph[p]) graph[p] = [];
      graph[p].push(row);
      allChildrenInRows.add(c);
    });

    // Alt parçaları alfabetik sırala
    for (const p in graph) {
      graph[p].sort((a, b) => {
        const cA = String(a[1] || a[6] || '');
        const cB = String(b[1] || b[6] || '');
        return cA.localeCompare(cB);
      });
    }

    const sortedRows = [];
    const visitedEdges = new Set();

    function dfs(p) {
      if (!graph[p]) return;
      for (const row of graph[p]) {
        const c = String(row[1] || row[6] || '');
        const edgeKey = p + '|' + c;
        if (visitedEdges.has(edgeKey)) continue;
        visitedEdges.add(edgeKey);
        sortedRows.push(row);
        dfs(c); // Çocuğun alt parçalarına in
      }
    }

    // Kök ebeveynleri (hiçbir listeye child olarak girmeyenler) bul
    const roots = Object.keys(graph).filter(p => !allChildrenInRows.has(p));
    roots.sort((a, b) => a.localeCompare(b));

    for (const root of roots) dfs(root);
    for (const p in graph) dfs(p); // Kalan (kopuk/orphan) dallar

    resultRows.length = 0;
    resultRows.push(...sortedRows);
    // ---------------------------------

    // 7. Sayfaya yaz
    if (resultRows.length > 0) {
      compSheet.getRange(2, 1, resultRows.length, compHeaders.length).setValues(resultRows);
    }

    // 8. Renklendirme
    applyComparisonColors(compSheet, resultRows);

    compSheet.setFrozenRows(1);
    compSheet.autoResizeColumns(1, compHeaders.length);
    compSheet.setColumnWidth(5, 180); // Durum geniş

    // Timestamp
    updateSettingsTimestamp('Son Karşılaştırma');

    // Özet
    const eqCount = hiddenEqCount;
    const diffCount = resultRows.filter(r => r[4].startsWith('⚠️')).length;
    const swOnlyCount = resultRows.filter(r => r[4].startsWith('➕')).length;
    const odooOnlyCount = resultRows.filter(r => r[4].startsWith('➖')).length;

    ss.toast(
      `Karşılaştırma tamamlandı: ✅${eqCount} eşit, ⚠️${diffCount} farklı, ➕${swOnlyCount} sadece SW, ➖${odooOnlyCount} sadece Odoo`,
      "🔍 Sonuç"
    );

  } catch (e) {
    console.error("Karşılaştırma hatası:", e.message, e.stack);
    ui.alert("Karşılaştırma hatası: " + e.message);
  }
}

/**
 * Sayfa verilerini okur (2. satırdan itibaren).
 * İşlevselliğini artırmak için tüm sütunları alır (Görsel clone/kopya byrak kolonları dahil).
 * @returns {Array[]} Satır verileri
 */
function readSheetData(sheet, isOdoo = false) {
  const lastRow = sheet.getLastRow();
  if (lastRow < 2) return [];

  // Data mapleri yaparken görünmez flag alanını da alabilmek için `totCols + 1` e kadar al
  const totCols = isOdoo ? CONFIG.odooTotalColumns : CONFIG.totalColumns;
  const data = sheet.getRange(2, 1, lastRow - 1, totCols + 1).getValues();
  
  const cols = isOdoo ? CONFIG.odooColumns : CONFIG.columns;
  return data.filter(row => row[cols.childRef]); // Boş satırları filtrele
}

/**
 * Veri dizisinden parent_ref ve child_ref birleşik anahtarıyla map oluşturur.
 * NOT: Aynı childRef farklı parent'lar altında olabilir.
 *      Bu durumda parent|childRef birleşik anahtar kullanılır.
 * GÖRSEL KOPYALAR (Visual Clones): Ağaç mantığını göstermek için DFS ile üretilen kopyalar sayılmaz.
 * @returns {Object} { "parent|child": { parent, child, qty, uretimSekli, ... } }
 */
function buildDataMap(data, isOdoo = false) {
  const map = {};
  const cols = isOdoo ? CONFIG.odooColumns : CONFIG.columns;
  const totCols = isOdoo ? CONFIG.odooTotalColumns : CONFIG.totalColumns;

  data.forEach(row => {
    // Görsel kopya kontrolü (DFS Tree Expansion tarafından işaretlenmiştir)
    if (row[totCols] === true || String(row[totCols]).toLowerCase() === 'true' || row[totCols] === 1) {
      return; // Kopya montajları işleme girip sayıları katlamasın
    }

    const parentRef = String(row[cols.parentRef] || '').trim();
    const childRef = String(row[cols.childRef] || '').trim();
    if (!childRef) return;

    // Aynı ilişkide (aynı parent, aynı child) macro'dan birden fazla satır gelmişse cıvatalar vb. miktar toplanır
    const key = parentRef + '|' + childRef;

    if (map[key]) {
       map[key].qty = Number(map[key].qty) + Number(row[cols.qty] || 0);
    } else {
      map[key] = {
        parent: parentRef,
        child: childRef,
        qty: Number(row[cols.qty] || 0),
        uretimSekli: String(row[isOdoo ? 99 : cols.uretimSekli] || '').trim(), // Odoo'da yok
        malzeme: String(row[isOdoo ? 99 : cols.malzeme] || '').trim(),
        malzemeEbat: String(row[isOdoo ? 99 : cols.malzemeEbat] || '').trim(),
        altKod: String(row[isOdoo ? 99 : cols.altKod] || '').trim(),
        revizyon: String(row[isOdoo ? 99 : cols.revizyon] || '').trim(),
        tarih: String(row[isOdoo ? 99 : cols.tarih] || '').trim()
      };
    }
  });

  return map;
}

/**
 * Odoo BOM yapısından alt_kod değerini türetir.
 *
 * Mantık:
 *   - Bir parçanın (childRef) parent olarak göründüğü satırlara bak
 *   - 1 alt parça → alt_kod = o alt parçanın kodu
 *   - Birden fazla alt parça → alt_kod = "N/A"
 *   - Parent olarak hiç görünmüyorsa → alt_kod = "" (boş)
 *
 * @param {Object[]} odooData ODOO_BOM satır verileri
 * @returns {Object} { childRef: derivedAltKod }
 */
function deriveAltKodFromOdoo(odooData) {
  const cols = CONFIG.columns;
  const result = {};

  // Her parçanın alt parçalarını bul
  const childrenMap = {}; // { parentRef: Set[childRef1, childRef2, ...] }

  odooData.forEach(row => {
    const parent = String(row[cols.parentRef] || '').trim();
    const child = String(row[cols.childRef] || '').trim();
    if (!parent || !child) return;

    if (!childrenMap[parent]) childrenMap[parent] = new Set();
    childrenMap[parent].add(child);
  });

  // Tüm bilinen child'lar için alt_kod türet
  const allChildren = new Set();
  odooData.forEach(row => {
    const child = String(row[cols.childRef] || '').trim();
    if (child) allChildren.add(child);
    const parent = String(row[cols.parentRef] || '').trim();
    if (parent) allChildren.add(parent);
  });

  for (const ref of allChildren) {
    const childrenSet = childrenMap[ref];
    if (!childrenSet || childrenSet.size === 0) {
      result[ref] = 'N/A'; // Alt BOM yok
    } else if (childrenSet.size === 1) {
      result[ref] = Array.from(childrenSet)[0]; // Tek alt parça
    } else {
      result[ref] = 'N/A'; // Birden fazla benzersiz alt parça var
    }
  }

  return result;
}

/**
 * Değeri karşılaştırma için normalize eder.
 */
function normalizeValue(val) {
  if (val === null || val === undefined) return '';
  return String(val).trim().toLowerCase();
}

/**
 * Karşılaştırma sonuçlarına renk uygular.
 */
function applyComparisonColors(sheet, rows) {
  if (rows.length === 0) return;

  // Pastel arka plan renkleri (Parent grubuna göre değişecek)
  const bgColors = ['#F4F8F7', '#FFFFFF'];
  let currentBgIndex = 0;
  let lastParent = null;

  for (let i = 0; i < rows.length; i++) {
    const rowNum = i + 2; // 2. satırdan başlar
    // Durum sütunu 4. indexte (5. kolon)
    const status = rows[i][4];
    const parent = String(rows[i][0] || rows[i][5]);
    const rowRange = sheet.getRange(rowNum, 1, 1, rows[i].length);

    // Parent değiştiyse pastel rengi değiştir
    if (lastParent !== null && parent !== lastParent) {
      currentBgIndex = (currentBgIndex + 1) % 2;
    }
    lastParent = parent;

    const rowBg = bgColors[currentBgIndex];
    rowRange.setBackground(rowBg).setFontColor('#000000');

    if (status.startsWith('✅')) {
      sheet.getRange(rowNum, 5).setBackground('#e6f4ea').setFontColor('#137333');
    } else if (status.startsWith('⚠️')) {
      // Farklı — satır açık turuncu, Durum hücresi kırmızımtırak
      sheet.getRange(rowNum, 5).setBackground('#fce8e6').setFontColor('#c5221f');

      // Miktar farkı (Odoo Miktar: index 2, SW Miktar: index 7)
      if (String(rows[i][2]) !== String(rows[i][7])) {
        sheet.getRange(rowNum, 3).setBackground('#FFE0B2').setFontWeight('bold'); // Odoo Miktar (Kolon 3)
        sheet.getRange(rowNum, 8).setBackground('#FFE0B2').setFontWeight('bold'); // SW Miktar (Kolon 8)
      }
      // alt_kod farkı (Odoo alt_kod: index 3, SW alt_kod: index 8)
      if (normalizeValue(rows[i][3]) !== normalizeValue(rows[i][8])) {
        sheet.getRange(rowNum, 4).setBackground('#FFE0B2').setFontWeight('bold'); // Odoo alt_kod (Kolon 4)
        sheet.getRange(rowNum, 9).setBackground('#FFE0B2').setFontWeight('bold'); // SW alt_kod (Kolon 9)
      }
    } else if (status.startsWith('➕')) {
      // Sadece SW'de — Odoo kısmı boyalı olacak (Sol taraf 1-4. hücreler) boş / hatalı olduğu belli olsun
      sheet.getRange(rowNum, 1, 1, 4).setBackground('#FFCDD2'); // Odoo tarafı kırmızı
      sheet.getRange(rowNum, 6, 1, 4).setBackground('#C8E6C9'); // SW tarafı yeşil
      sheet.getRange(rowNum, 5).setFontColor('#1b5e20');
    } else if (status.startsWith('➖')) {
      // Sadece Odoo'da — SW kısmı boyalı olacak (Sağ taraf 6-9. hücreler) boş / hatalı olduğu belli olsun
      sheet.getRange(rowNum, 1, 1, 4).setBackground('#C8E6C9'); // Odoo tarafı yeşil
      sheet.getRange(rowNum, 6, 1, 4).setBackground('#FFCDD2'); // SW tarafı kırmızı
      sheet.getRange(rowNum, 5).setFontColor('#b71c1c');
    }
  }
}

/**
 * Bir sayfayı (SW_BOM veya ODOO_BOM) BOM ağacı yapısına göre sıralar ve renklendirir.
 * @param {GoogleAppsScript.Spreadsheet.Sheet} sheet Hedef sayfa 
 * @param {Array[]} dataRows Sayfadaki veri satırları (başlık hariç)
 * @param {boolean} isOdoo İlgili sayfa Odoo tablosu mu?
 */
function sortAndColorSheet(sheet, dataRows, isOdoo = false) {
  if (!dataRows || dataRows.length === 0) return;

  const cols = isOdoo ? CONFIG.odooColumns : CONFIG.columns;
  const totCols = isOdoo ? CONFIG.odooTotalColumns : CONFIG.totalColumns;
  
  // 1. DFS ile Ağaç Sıralaması Oluştur
  const graph = {};
  const allChildren = new Set();
  
  dataRows.forEach(row => {
    const p = String(row[cols.parentRef] || '').trim();
    const c = String(row[cols.childRef] || '').trim();
    if (!graph[p]) graph[p] = [];
    graph[p].push(row);
    allChildren.add(c);
  });

  // Alt parçaları isme göre sırala
  Object.keys(graph).forEach(p => {
    graph[p].sort((a, b) => String(a[cols.childRef]).localeCompare(String(b[cols.childRef])));
  });

  const sortedRows = [];
  const visitedRows = new Set(); // Sadece Unique referanslarını tutar, ancak iterasyonu kesmez

  function dfs(p, pathStack = new Set()) {
    if (!graph[p]) return;
    for (const row of graph[p]) {
      // Bir satır NESNESİNİN görsel olarak kopyası oluşturularak listeye tüm dallar tam yansıtılır.
      // Sığ kopya alıyoruz, böylece "visual clone flag" bayrağını en son hücreye ekleyebiliriz.
      const outRow = [...row];
      
      if (visitedRows.has(row)) {
        outRow[totCols] = true; // Daha önce basıldıysa; bu bir görsel kopya
      } else {
        visitedRows.add(row);
        outRow[totCols] = false; // Orijinal ilk referans
      }
      
      sortedRows.push(outRow);

      const c = String(row[cols.childRef] || '').trim();
      
      if (pathStack.has(c)) {
         // Sonsuz döngü engellemesi (Circular Reference)
         continue;
      }
      
      const newStack = new Set(pathStack);
      newStack.add(c);
      dfs(c, newStack);
    }
  }

  // Kökleri bul (en üst montajlar)
  const roots = Object.keys(graph).filter(p => !allChildren.has(p));
  roots.sort((a,b) => a.localeCompare(b));
  
  roots.forEach(r => dfs(r, new Set([r])));
  Object.keys(graph).forEach(p => dfs(p, new Set([p]))); // Gözden kaçanlar (orphan)

  // 2. Artık listeyi sayfaya yazarken, önce eski içeriği temizle (Leftovers kalmasın)
  const lastRow = sheet.getLastRow();
  if (lastRow > 1) {
    sheet.getRange(2, 1, lastRow - 1, sheet.getMaxColumns()).clearContent().setBackground(null);
  }

  // 3. Sayfaya Geri Yaz (Sıralanmış hali + Görünmez Clone Flag kolonuyla birlikte)
  sheet.getRange(2, 1, sortedRows.length, totCols + 1).setValues(sortedRows);
  sheet.hideColumns(totCols + 1); // Visual Clone Flag (true/false) kolonunu gizle

  // 4. Renklendirme (Pastel Dalgalanma)
  const bgColors = ['#F4F8F7', '#FFFFFF'];
  let currentBgIndex = 0;
  let lastParent = null;

  for (let i = 0; i < sortedRows.length; i++) {
    const rowNum = i + 2;
    const parent = String(sortedRows[i][cols.parentRef]);
    
    // Parent değiştiyse pastel rengi dalgalandır
    if (lastParent !== null && parent !== lastParent) {
      currentBgIndex = (currentBgIndex + 1) % 2;
    }
    lastParent = parent;

    sheet.getRange(rowNum, 1, 1, totCols).setBackground(bgColors[currentBgIndex]);
  }
}
