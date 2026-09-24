/**
 * ODOO BOM ÇEKME MODÜLÜ
 * Odoo'dan belirli bir BOM'u (ID: 1707) tüm alt BOM'larıyla birlikte recursive olarak çeker
 * ve ODOO_BOM sayfasına 9 sütunluk yapıda yazar.
 */

/**
 * Ana fonksiyon — menüden çağrılır.
 */
function fetchOdooBOM() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const ui = SpreadsheetApp.getUi();

  try {
    ss.toast("Odoo'ya bağlanılıyor...", "📥 BOM Çekme", 30);
    const odoo = new OdooBridge();

    const bomId = CONFIG.odoo.targetBomId;

    // 1. Ana BOM header bilgisi
    const bomHeaders = odoo.searchRead('mrp.bom', [['id', '=', bomId]], [
      'id', 'product_tmpl_id', 'product_qty', 'type', 'code',
      'bom_line_ids'
    ]);

    if (!bomHeaders || bomHeaders.length === 0) {
      ui.alert(`BOM ID ${bomId} bulunamadı! Lütfen AYARLAR sayfasındaki BOM ID'yi kontrol edin.`);
      return;
    }

    const bomHeader = bomHeaders[0];
    const tmplId = bomHeader.product_tmpl_id[0];

    // Ana ürünün default_code'unu al
    const rootProducts = odoo.searchRead('product.product', [['product_tmpl_id', '=', tmplId]], ['default_code', 'name']);
    const rootCode = (rootProducts && rootProducts.length > 0)
      ? (rootProducts[0].default_code || rootProducts[0].name)
      : `BOM_${bomId}`;

    ss.toast(`Ana ürün: ${rootCode} — Alt BOM'lar taranıyor...`, "📥 BOM Çekme", 60);

    // 2. Batched (Toplu) BOM çekme
    const allRows = [];
    fetchBOMTreeBatched(odoo, bomId, rootCode, allRows, ss);

    // 3. Sayfaya yaz
    const sheetName = CONFIG.sheets.odooBom;
    let sheet = ss.getSheetByName(sheetName);
    if (!sheet) {
      sheet = ss.insertSheet(sheetName);
    } else {
      sheet.clear();
    }

    // Başlıklar
    sheet.getRange(1, 1, 1, CONFIG.odooHeaders.length)
      .setValues([CONFIG.odooHeaders])
      .setFontWeight('bold')
      .setBackground('#e8710a')
      .setFontColor('white');

    // Veri yaz
    if (allRows.length > 0) {
      sheet.getRange(2, 1, allRows.length, CONFIG.odooTotalColumns).setValues(allRows);
    }

    // Görünüm ayarları
    sheet.setFrozenRows(1);
    sheet.autoResizeColumns(1, CONFIG.odooTotalColumns);

    // --- SIRALAMA VE RENKLENDİRME ---
    // Odoo sayfası farklı formattadır (5 sütun), sortAndColorSheet Odoo sütunlarını dinamik almalıdır.
    sortAndColorSheet(sheet, allRows, true); // true = isOdoo
    // ---------------------------------

    // Timestamp güncelle
    updateSettingsTimestamp('Son BOM Çekme');

    ss.toast(`${allRows.length} satır çekildi. (BOM ID: ${bomId})`, "✅ Tamamlandı");

  } catch (e) {
    console.error("Odoo BOM çekme hatası:", e.message, e.stack);
    ui.alert("BOM çekme hatası: " + e.message);
  }
}

/**
 * Recursive BOM çekme işlemi yerine, BOM ağacını **seviye seviye (Level-Order) batched** şekilde tarar.
 * Her seviye için (satırlar, ürünler, alt-BOM'lar) sadece 3 API çağrısı yaparak
 * API sorgularını yüzlerceden 10-15 seviyesine düşürür ve saniyeler içinde tamamlar.
 *
 * @param {OdooBridge} odoo Odoo bağlantısı
 * @param {number} startBomId Başlangıç BOM ID'si
 * @param {string} rootCode Kök montaj kodu
 * @param {Array[]} allRows Tüm satırlar (mutated)
 * @param {Spreadsheet} ss Toast mesajları için
 */
function fetchBOMTreeBatched(odoo, startBomId, rootCode, allRows, ss) {
  let queue = [{ bomId: startBomId, parentCode: rootCode }];
  let processedParents = new Set(); // Hangi montajın çocuklarını (edges) allRows'a yazdığımızı takip eder
  let visitedEdges = new Set();    // Hangi parent|child bağını QUEUE'ya eklediğimizi takip eder (Sonsuz döngü koruması)
  
  // Yerel veritabanı (Mükerrer API çağrısını engeller)
  const bomLinesCache = {};
  const productCache = {};
  const templateBomCache = {};
  const operationCache = {}; // Workcenter isimleri için
  
  let level = 1;

  while (queue.length > 0) {
    // 0. Queue Deduplication (Aynı ebeveyne ait tekrarları temizle ki raw veride duplicate satır oluşmasın)
    const uniqueQueue = [];
    const seenParents = new Set();
    for (const q of queue) {
      if (!seenParents.has(q.parentCode)) {
        seenParents.add(q.parentCode);
        uniqueQueue.push(q);
      }
    }
    queue = uniqueQueue;

    // 1. İhtiyaç duyulan BOM satırlarını (mrp.bom.line) TEK SEFERDE çek
    const missingBomIds = [...new Set(queue.map(q => q.bomId).filter(id => !bomLinesCache[id]))];
    
    if (missingBomIds.length > 0) {
      ss.toast(`Ağaç Derinliği ${level} Taranıyor... (${missingBomIds.length} parça listesi çekiliyor)`, "📥 Hızlı İndirme");
      const lines = odoo.searchRead('mrp.bom.line', [['bom_id', 'in', missingBomIds]], [
        'bom_id', 'product_id', 'product_qty'
      ]);
      
      missingBomIds.forEach(id => bomLinesCache[id] = []);
      if (lines) {
        lines.forEach(line => {
          if (line.bom_id) {
            const bId = line.bom_id[0];
            if (bomLinesCache[bId]) bomLinesCache[bId].push(line);
          }
        });
      }
    }

    // 2. Satırlardaki ürün bilgilerini (product.product) TEK SEFERDE çek
    const neededProductIds = new Set();
    queue.forEach(item => {
      const lines = bomLinesCache[item.bomId] || [];
      lines.forEach(l => {
        if (l.product_id) neededProductIds.add(l.product_id[0]);
      });
    });

    const missingProductIds = [...neededProductIds].filter(id => !productCache[id]);
    if (missingProductIds.length > 0) {
      const prods = odoo.searchRead('product.product', [['id', 'in', missingProductIds]], [
        'id', 'default_code', 'name', 'product_tmpl_id'
      ], 5000);
      if (prods) prods.forEach(p => productCache[p.id] = p);
    }

    // 3. Ürünlerin alt BOM'u olup olmadığını (mrp.bom) ve Operasyonları (mrp.routing.workcenter) TEK SEFERDE çek
    const neededTmplIds = new Set();
    missingProductIds.forEach(id => {
       const p = productCache[id];
       if (p && p.product_tmpl_id) neededTmplIds.add(p.product_tmpl_id[0]);
    });
    
    const missingTmplIds = [...neededTmplIds].filter(id => templateBomCache[id] === undefined);
    if (missingTmplIds.length > 0) {
       const childBoms = odoo.searchRead('mrp.bom', [['product_tmpl_id', 'in', missingTmplIds]], ['id', 'product_tmpl_id', 'type', 'operation_ids']);
       missingTmplIds.forEach(id => templateBomCache[id] = null); // Initialize as negative
       
       if (childBoms && childBoms.length > 0) {
         // Workcenter isimlerini bulmak için operation_ids leri topla
         const neededOpIds = new Set();
         childBoms.forEach(b => {
           if (b.operation_ids && b.operation_ids.length > 0) {
             b.operation_ids.forEach(opId => neededOpIds.add(opId));
           }
         });
         
         const missingOpIds = [...neededOpIds].filter(id => operationCache[id] === undefined);
         if (missingOpIds.length > 0) {
           const ops = odoo.searchRead('mrp.routing.workcenter', [['id', 'in', missingOpIds]], ['id', 'workcenter_id']);
           missingOpIds.forEach(id => operationCache[id] = "");
           if (ops) {
             ops.forEach(op => {
               if (op.workcenter_id) operationCache[op.id] = op.workcenter_id[1]; // [id, name]
             });
           }
         }

         // BOM bilgilerini ve doldurulmuş operasyon isimlerini önbelleğe kaydet
         childBoms.forEach(b => {
           if (b.product_tmpl_id) {
             let wcNames = [];
             if (b.operation_ids) {
               wcNames = b.operation_ids.map(oid => operationCache[oid]).filter(name => name);
             }
             // Duplicate isimleri temizle (örn. Montaj Alanı, Montaj Alanı -> Montaj Alanı)
             wcNames = [...new Set(wcNames)];
             
             templateBomCache[b.product_tmpl_id[0]] = { 
               id: b.id, 
               type: b.type,
               workcenters: wcNames.join(' / ')
             };
           }
         });
       }
    }

    // 4. Mevcut seviyeyi işle, sayfaya veri ekle ve bir sonraki seviyenin kuyruğunu (nextQueue) oluştur
    const nextQueue = [];
    
    for (const item of queue) {
      // Eğer bu ebeveynin çocuklarını daha önce allRows'a eklediysek tekrar ekleme (Çift miktar hatasını önler)
      if (processedParents.has(item.parentCode)) continue;
      processedParents.add(item.parentCode);

      const lines = bomLinesCache[item.bomId] || [];
      
      for (const line of lines) {
        if (!line.product_id) continue;
        const productId = line.product_id[0];
        const product = productCache[productId];
        if (!product) continue;

        const childCode = product.default_code || product.name || `ID_${productId}`;
        const qty = line.product_qty || 0;
        
        let workcenterNames = "";
        let childBomId = null;
        let bomTypeDisplay = "Parça"; // Default
        
        if (product.product_tmpl_id) {
          const childTmplId = product.product_tmpl_id[0];
          const bInfo = templateBomCache[childTmplId];
          if (bInfo) {
            childBomId = bInfo.id;
            workcenterNames = bInfo.workcenters || "";
            
            if (bInfo.type === 'normal') bomTypeDisplay = "Üretim";
            else if (bInfo.type === 'phantom') bomTypeDisplay = "Kit (Phantom)";
            else if (bInfo.type === 'subcontract') bomTypeDisplay = "Fason";
            else bomTypeDisplay = bInfo.type;
          }
        }

        // Sayfaya yazılacak 5 sütunlu satırı oluştur
        const row = new Array(CONFIG.odooTotalColumns).fill('');
        row[CONFIG.odooColumns.parentRef] = item.parentCode;
        row[CONFIG.odooColumns.childRef] = childCode;
        row[CONFIG.odooColumns.qty] = qty;
        row[CONFIG.odooColumns.bomType] = bomTypeDisplay;
        row[CONFIG.odooColumns.workcenter] = workcenterNames;
        allRows.push(row);

        if (childBomId) {
          // Sonsuz döngüden korumak için (örn. yanlışlıkla kendine bağlanan montajlar) kenarı kontrol et
          const edgeKey = item.parentCode + '|' + childCode;
          
          if (!visitedEdges.has(edgeKey)) {
             visitedEdges.add(edgeKey);
             nextQueue.push({
               bomId: childBomId,
               parentCode: childCode
             });
          }
        }
      }
    }

    queue = nextQueue;
    level++;
  }
}
