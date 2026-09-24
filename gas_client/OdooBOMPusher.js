/**
 * ODOO BOM GERİ YAZMA MODÜLÜ
 * ODOO_BOM sayfasındaki değişiklikleri Odoo'ya aktarır.
 *
 * Strateji: Mevcut BOM satırlarını sil ve yeniden oluştur (Delete + Recreate).
 * Bu yöntem sample projesindeki (MBOMProcessor) pattern ile aynıdır.
 */

/**
 * Ana fonksiyon — menüden çağrılır.
 */
function pushToOdoo() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const ui = SpreadsheetApp.getUi();

  // Onay iste
  const confirm = ui.alert(
    '⚠️ Odoo BOM Güncelleme',
    `Bu işlem BOM ID ${CONFIG.odoo.targetBomId} üzerindeki TÜM satırları silip\n` +
    `ODOO_BOM sayfasındaki verilerle yeniden oluşturacak.\n\n` +
    `Devam etmek istiyor musunuz?`,
    ui.ButtonSet.YES_NO
  );

  if (confirm !== ui.Button.YES) {
    ss.toast("İşlem iptal edildi.", "❌ İptal");
    return;
  }

  const sheet = ss.getSheetByName(CONFIG.sheets.odooBom);
  if (!sheet || sheet.getLastRow() < 2) {
    ui.alert("ODOO_BOM sayfası boş veya bulunamadı.");
    return;
  }

  try {
    ss.toast("Odoo'ya bağlanılıyor...", "📤 Güncelleme", 30);
    const odoo = new OdooBridge();
    const cols = CONFIG.columns;
    const bomId = CONFIG.odoo.targetBomId;

    // 1. Sayfadaki veriyi oku
    const lastRow = sheet.getLastRow();
    const data = sheet.getRange(2, 1, lastRow - 1, CONFIG.totalColumns).getValues();
    const validData = data.filter(row => row[cols.childRef]);

    if (validData.length === 0) {
      ui.alert("Sayfada geçerli veri bulunamadı.");
      return;
    }

    // 2. Ana BOM bilgilerini al
    const bomHeaders = odoo.searchRead('mrp.bom', [['id', '=', bomId]], ['product_tmpl_id']);
    if (!bomHeaders || bomHeaders.length === 0) {
      ui.alert(`BOM ID ${bomId} Odoo'da bulunamadı!`);
      return;
    }

    const rootTmplId = bomHeaders[0].product_tmpl_id[0];
    const rootProducts = odoo.searchRead('product.product', [['product_tmpl_id', '=', rootTmplId]], ['default_code', 'name']);
    const rootCode = (rootProducts && rootProducts.length > 0) ? (rootProducts[0].default_code || rootProducts[0].name) : '';

    // 3. Verileri parent bazında grupla
    const groups = groupByParent(validData, cols, rootCode);

    // 4. Her grup için BOM güncelle
    let totalUpdated = 0;

    for (const parentCode in groups) {
      const lines = groups[parentCode];

      // Bu parent'ın product_tmpl_id'sini bul
      let tmplId;
      if (parentCode === rootCode) {
        tmplId = rootTmplId;
      } else {
        const parentProducts = odoo.searchRead('product.product', [['default_code', '=', parentCode]], ['product_tmpl_id']);
        if (!parentProducts || parentProducts.length === 0) {
          console.error(`Ürün bulunamadı: ${parentCode}, atlanıyor.`);
          continue;
        }
        tmplId = parentProducts[0].product_tmpl_id[0];
      }

      // Bu template'in BOM'unu bul
      let targetBomId;
      if (parentCode === rootCode) {
        targetBomId = bomId; // Ana BOM
      } else {
        const childBoms = odoo.searchRead('mrp.bom', [['product_tmpl_id', '=', tmplId]], ['id']);
        if (childBoms && childBoms.length > 0) {
          targetBomId = childBoms[0].id;
        } else {
          // Alt BOM yoksa oluştur
          targetBomId = odoo.create('mrp.bom', {
            'product_tmpl_id': tmplId,
            'product_qty': 1,
            'type': 'normal'
          });
          if (!targetBomId) {
            console.error(`BOM oluşturulamadı: ${parentCode}`);
            continue;
          }
        }
      }

      ss.toast(`Güncelleniyor: ${parentCode}`, "📤 Odoo", 60);

      // Mevcut BOM satırlarını sil
      const existingLines = odoo.searchRead('mrp.bom.line', [['bom_id', '=', targetBomId]], ['id']);
      if (existingLines && existingLines.length > 0) {
        odoo.unlink('mrp.bom.line', existingLines.map(l => l.id));
      }

      // Yeni satırları oluştur
      for (const line of lines) {
        const childCode = line.childCode;
        const qty = line.qty;

        // Child ürünün product_id'sini bul
        const childProducts = odoo.searchRead('product.product', [['default_code', '=', childCode]], ['id']);
        let childProductId;

        if (childProducts && childProducts.length > 0) {
          childProductId = childProducts[0].id;
        } else {
          // Ürün yoksa oluştur
          childProductId = odoo.create('product.product', {
            'name': childCode,
            'default_code': childCode,
            'type': 'consu',
            'is_storable': true
          });
          if (!childProductId) {
            console.error(`Ürün oluşturulamadı: ${childCode}`);
            continue;
          }
        }

        // BOM satırı oluştur
        odoo.create('mrp.bom.line', {
          'bom_id': targetBomId,
          'product_id': childProductId,
          'product_qty': qty
        });

        totalUpdated++;
      }
    }

    // Timestamp güncelle
    updateSettingsTimestamp('Son Odoo Yazma');

    ui.alert(`✅ İşlem Tamamlandı!\n\nToplam ${totalUpdated} BOM satırı güncellendi.\nOdoo web arayüzünden kontrol edebilirsiniz.`);

  } catch (e) {
    console.error("Odoo geri yazma hatası:", e.message, e.stack);
    ui.alert("Geri yazma hatası: " + e.message);
  }
}

/**
 * Veriyi parent bazında gruplar.
 * @param {Array[]} data Sayfa verileri
 * @param {Object} cols Sütun indeksleri
 * @param {string} rootCode Ana ürün kodu
 * @returns {Object} { parentCode: [{ childCode, qty }] }
 */
function groupByParent(data, cols, rootCode) {
  const groups = {};

  data.forEach(row => {
    const parent = String(row[cols.parentRef] || '').trim();
    const child = String(row[cols.childRef] || '').trim();
    const qty = Number(row[cols.qty]) || 0;

    if (!parent || !child) return;

    if (!groups[parent]) groups[parent] = [];
    groups[parent].push({ childCode: child, qty: qty });
  });

  return groups;
}
