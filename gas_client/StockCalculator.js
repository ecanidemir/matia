/**
 * ODOO MULTI-BOM STOK VE ÜRETİM HESAPLAYICI
 * Belirlenen birden fazla reçetedeki bileşenleri çeker, şirket bazlı stokları karşılaştırır.
 */

function calculateMultiBOMStock() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const ui = SpreadsheetApp.getUi();
  
  // Hedef Reçeteler
  const TARGET_BOMS = {
    1735: "Common Parts",
    1737: "Outdoor Parts",
    1738: "Seat Parts"
  };
  const bomIds = Object.keys(TARGET_BOMS).map(id => parseInt(id));
  const sheetName = "TOPLU_STOK_ANALIZ";

  try {
    ss.toast("Odoo'ya bağlanılıyor...", "📦 Toplu Stok Hesaplama", 30);
    const odoo = new OdooBridge();

    // 1. Lokasyonları tanımla
    const targetLocationNames = [
      "WHUS/NCR Storage",
      "WHUS/Stock",
      "WHTR/NCR Alanı",
      "WHTR/Stock"
    ];
    
    ss.toast("Lokasyon bilgileri alınıyor...", "📦 Toplu Stok Hesaplama");
    const allInternalLocations = odoo.searchRead('stock.location', [['usage', '=', 'internal']], ['id', 'complete_name', 'display_name']);
    
    // Her bir iç lokasyonun hangi hedef lokasyona ait olduğunu haritala
    const subLocToTargetMap = {}; 
    allInternalLocations.forEach(loc => {
      const fullName = (loc.complete_name || loc.display_name || "").replace(/\s*\/\s*/g, "/");
      
      for (let i = 0; i < targetLocationNames.length; i++) {
        const target = targetLocationNames[i].replace(/\s*\/\s*/g, "/");
        // Tam eşleşme veya yolun bir parçası olarak eşleşme (örn: Physical/WHUS/Stock/Shelf1)
        if (fullName === target || fullName.endsWith("/" + target) || fullName.startsWith(target + "/") || fullName.includes("/" + target + "/")) {
          subLocToTargetMap[loc.id] = i;
          break;
        }
      }
    });

    if (Object.keys(subLocToTargetMap).length === 0) {
      ss.toast("Uyarı: Belirtilen isimlerle eşleşen lokasyon bulunamadı!", "⚠️ Lokasyon Hatası", 10);
    }

    // 2. Tüm BOM Bileşenlerini Çek
    ss.toast("Tüm reçete bileşenleri çekiliyor...", "📦 Toplu Stok Hesaplama");
    const bomLines = odoo.searchRead('mrp.bom.line', [['bom_id', 'in', bomIds]], ['bom_id', 'product_id', 'product_qty']);
    
    if (!bomLines || bomLines.length === 0) {
      ui.alert("Belirtilen BOM ID'leri için bileşen bulunamadı.");
      return;
    }

    const productIdsSet = new Set();
    const productUsageMap = {}; // { productId: { totalQty: X, boms: [Name1, Name2] } }

    bomLines.forEach(line => {
      if (line.product_id && line.bom_id) {
        const pId = line.product_id[0];
        const bId = line.bom_id[0];
        const bName = TARGET_BOMS[bId] || `BOM ${bId}`;
        const qty = line.product_qty || 0;

        productIdsSet.add(pId);

        if (!productUsageMap[pId]) {
          productUsageMap[pId] = { totalQty: 0, boms: new Set() };
        }
        productUsageMap[pId].totalQty += qty;
        productUsageMap[pId].boms.add(bName);
      }
    });

    const productIds = Array.from(productIdsSet);

    // 3. Ürün bilgilerini çek
    ss.toast("Ürün detayları alınıyor...", "📦 Toplu Stok Hesaplama");
    const products = odoo.searchRead('product.product', [['id', 'in', productIds]], ['id', 'default_code', 'name']);
    const productDataMap = {};
    products.forEach(p => { productDataMap[p.id] = p; });

    // 4. Stok verilerini çek (Internal lokasyonlar)
    ss.toast("Stoklar kontrol ediliyor...", "📦 Toplu Stok Hesaplama");
    const quants = odoo.searchRead('stock.quant', [['product_id', 'in', productIds], ['location_id.usage', '=', 'internal']], ['product_id', 'quantity', 'location_id']);
    
    const stockMap = {}; 
    productIds.forEach(pId => {
      stockMap[pId] = [0, 0, 0, 0]; // 4 hedef lokasyon için sıfırla
    });

    if (quants && quants.length > 0) {
      quants.forEach(q => {
        if (q.product_id && q.location_id) {
          const pId = q.product_id[0];
          const lId = q.location_id[0];
          const targetIdx = subLocToTargetMap[lId];
          
          if (stockMap[pId] && targetIdx !== undefined) {
            stockMap[pId][targetIdx] += (q.quantity || 0);
          }
        }
      });
    } else {
      ss.toast("Ürünler için stok kaydı (quant) bulunamadı.", "ℹ️ Bilgi");
    }

    // 5. Sayfayı Hazırla
    let sheet = ss.getSheetByName(sheetName);
    if (!sheet) {
      sheet = ss.insertSheet(sheetName);
    } else {
      sheet.clear();
    }

    // Başlıklar
    const headers = [
      'Komponent', 
      'Toplam Reçete Miktarı', 
      'Bağlı Reçeteler',
      ...targetLocationNames, 
      'Toplam Stok', 
      'İhtiyaç (Eksik) Miktar'
    ];
    
    const rows = [];
    productIds.forEach((pId, idx) => {
      const p = productDataMap[pId];
      if (!p) return;
      
      const usage = productUsageMap[pId];
      const compDisplay = p.default_code ? `[${p.default_code}] ${p.name}` : p.name;
      const lStocks = stockMap[pId] || [0, 0, 0, 0];
      const bomsList = Array.from(usage.boms).join(', ');

      const rowIndex = rows.length + 3; 
      const sumFormula = `=E${rowIndex}+G${rowIndex}`; // Sadece WHUS/Stock ve WHTR/Stock toplamı (NCR hariç)
      const missingFormula = `=MAX(0, (B${rowIndex} * $K$1) - H${rowIndex})`;

      rows.push([
        compDisplay, 
        usage.totalQty, 
        bomsList,
        ...lStocks, 
        sumFormula, 
        missingFormula
      ]);
    });

    // 6. Yazdırma ve Formatlama
    sheet.getRange("J1").setValue("İstenen Üretim Seti:").setFontWeight("bold").setHorizontalAlignment("right");
    sheet.getRange("K1").setValue(1).setBackground("#e6f4ea").setFontWeight("bold").setHorizontalAlignment("center");
    
    sheet.getRange("J2").setValue("Maksimum Üretilebilir Set:").setFontWeight("bold").setHorizontalAlignment("right");
    sheet.getRange("K2").setFormula(`=ARRAYFORMULA(MIN(IF(B3:B>0, INT(H3:H/B3:B), 999999)))`)
         .setBackground("#fce8e6").setFontWeight("bold").setHorizontalAlignment("center");

    sheet.getRange(2, 1, 1, headers.length).setValues([headers])
      .setFontWeight('bold').setBackground('#1a73e8').setFontColor('white');

    if (rows.length > 0) {
      sheet.getRange(3, 1, rows.length, headers.length).setValues(rows);
    }

    // Görünüm
    sheet.setFrozenRows(2);
    sheet.autoResizeColumns(1, headers.length);
    sheet.getRange(3, 2, rows.length, 1).setHorizontalAlignment("center"); // Miktar
    sheet.getRange(3, 4, rows.length, 6).setHorizontalAlignment("center"); // Sayılar

    // Koşullu Biçimlendirme (Eksik varsa tüm satırı vurgula)
    const fullRange = sheet.getRange(3, 1, rows.length, headers.length);
    const rule = SpreadsheetApp.newConditionalFormatRule()
      .whenFormulaSatisfied("=$I3>0")
      .setBackground("#fce8e6") // Açık kırmızı arka plan (tüm satır)
      .setRanges([fullRange])
      .build();
    sheet.setConditionalFormatRules([rule]);

    sheet.getRange("H3:H").setBackground("#e8f0fe"); // Toplam stok sütununu ayrı renkte tut (opsiyonel)

    sheet.getRange(2, 1, rows.length + 1, headers.length).setBorder(true, true, true, true, true, true);
    sheet.getRange(1, 10, 2, 2).setBorder(true, true, true, true, false, true);

    ss.toast("Analiz tamamlandı.", "✅ Başarılı");
    ss.setActiveSheet(sheet);

  } catch (e) {
    console.error(e);
    ui.alert("Hata: " + e.message);
  }
}
