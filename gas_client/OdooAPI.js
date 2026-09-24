/**
 * ODOO XML-RPC KÖPRÜSÜ
 * Odoo ERP sistemi ile XML-RPC protokolü üzerinden iletişim kurar.
 *
 * Desteklenen işlemler: authenticate, search_read, create, write, unlink
 */
class OdooBridge {
  /**
   * Yapılandırmayı yükler ve kimlik doğrulaması yapar.
   */
  constructor() {
    this.conf = CONFIG.odoo;
    this.uid = this.authenticate();
  }

  /**
   * Odoo'da kimlik doğrulaması yapar. UID'yi 1 saat önbelleğe alır.
   * @returns {number} Odoo User ID
   */
  authenticate() {
    const cache = CacheService.getScriptCache();
    const cachedUid = cache.get('odoo_uid_matia');
    if (cachedUid) return parseInt(cachedUid);

    const xml = `<?xml version='1.0'?>
      <methodCall>
        <methodName>authenticate</methodName>
        <params>
          <param><value><string>${this.conf.db}</string></value></param>
          <param><value><string>${this.conf.username}</string></value></param>
          <param><value><string>${this.conf.apiKey}</string></value></param>
          <param><value><struct></struct></value></param>
        </params>
      </methodCall>`;

    try {
      const resp = UrlFetchApp.fetch(`${this.conf.url}/xmlrpc/2/common`, {
        method: 'post',
        contentType: 'text/xml',
        payload: xml,
        muteHttpExceptions: true
      });

      const content = resp.getContentText();
      const match = content.match(/<int>(\d+)<\/int>/);

      if (match && match[1]) {
        const uid = parseInt(match[1]);
        cache.put('odoo_uid_matia', String(uid), 3600);
        return uid;
      } else {
        throw new Error("Kimlik doğrulama yanıtı geçersiz. Yanıt: " + content);
      }
    } catch (e) {
      throw new Error(`Odoo Bağlantı Hatası: ${e.message}`);
    }
  }

  /**
   * Arama ve okuma yapar (search_read).
   * @param {string} model Odoo model adı
   * @param {Array[]} domain Arama kriterleri
   * @param {string[]} fields Okunacak alanlar
   * @param {number} [limit=2000] Maksimum kayıt sayısı
   * @returns {Object[]} Kayıt listesi
   */
  searchRead(model, domain, fields, limit = 2000) {
    const domainXml = domain.map(d => {
      let valTag;
      if (typeof d[2] === 'string') {
        valTag = `<string>${this._escapeXml(d[2])}</string>`;
      } else if (typeof d[2] === 'boolean') {
        valTag = `<boolean>${d[2] ? 1 : 0}</boolean>`;
      } else if (Array.isArray(d[2])) {
        // XML-RPC array support for operators like 'in'
        const arrVals = d[2].map(v => {
          if (typeof v === 'string') return `<value><string>${this._escapeXml(v)}</string></value>`;
          return `<value><int>${v}</int></value>`;
        }).join('');
        valTag = `<array><data>${arrVals}</data></array>`;
      } else {
        valTag = `<int>${d[2]}</int>`;
      }
      return `<value><array><data>
          <value><string>${d[0]}</string></value>
          <value><string>${d[1]}</string></value>
          <value>${valTag}</value>
       </data></array></value>`;
    }).join('');

    const fieldsXml = fields.map(f => `<value><string>${f}</string></value>`).join('');

    const xml = `<?xml version='1.0'?>
      <methodCall>
        <methodName>execute_kw</methodName>
        <params>
          <param><value><string>${this.conf.db}</string></value></param>
          <param><value><int>${this.uid}</int></value></param>
          <param><value><string>${this.conf.apiKey}</string></value></param>
          <param><value><string>${model}</string></value></param>
          <param><value><string>search_read</string></value></param>
          <param><value><array><data>
            <value><array><data>${domainXml}</data></array></value>
          </data></array></value></param>
          <param><value><struct>
            <member><name>fields</name><value><array><data>${fieldsXml}</data></array></value></member>
            <member><name>limit</name><value><int>${limit}</int></value></member>
          </struct></value></param>
        </params>
      </methodCall>`;

    try {
      const resp = UrlFetchApp.fetch(`${this.conf.url}/xmlrpc/2/object`, {
        method: 'post',
        contentType: 'text/xml',
        payload: xml,
        muteHttpExceptions: true
      });
      return this._parseXmlResponse(resp.getContentText());
    } catch (e) {
      console.error(`Odoo searchRead hatası (${model}):`, e.message);
      return [];
    }
  }

  /**
   * Yeni kayıt oluşturur.
   * @param {string} model Odoo model adı
   * @param {Object} data Oluşturulacak veri
   * @returns {number|null} Oluşturulan kaydın ID'si
   */
  create(model, data) {
    const xml = `<?xml version='1.0'?>
      <methodCall>
        <methodName>execute_kw</methodName>
        <params>
          <param><value><string>${this.conf.db}</string></value></param>
          <param><value><int>${this.uid}</int></value></param>
          <param><value><string>${this.conf.apiKey}</string></value></param>
          <param><value><string>${model}</string></value></param>
          <param><value><string>create</string></value></param>
          <param><value><array><data>
            <value><struct>
              ${this._objToXmlStruct(data)}
            </struct></value>
          </data></array></value></param>
        </params>
      </methodCall>`;

    try {
      const resp = UrlFetchApp.fetch(`${this.conf.url}/xmlrpc/2/object`, {
        method: 'post',
        contentType: 'text/xml',
        payload: xml,
        muteHttpExceptions: true
      });

      const content = resp.getContentText();
      if (content.includes("<fault>")) {
        console.error(`Odoo Create Fault (${model}):`, content);
        return null;
      }
      const match = content.match(/<int>(\d+)<\/int>/);
      return match ? parseInt(match[1]) : null;
    } catch (e) {
      console.error(`Odoo Create Exception (${model}):`, e.message);
      return null;
    }
  }

  /**
   * Mevcut kayıtları günceller.
   * @param {string} model Odoo model adı
   * @param {number[]} ids Güncellenecek kayıt ID'leri
   * @param {Object} data Güncellenecek veriler
   * @returns {boolean} Başarılı ise true
   */
  write(model, ids, data) {
    const idsXml = ids.map(id => `<value><int>${id}</int></value>`).join('');

    const xml = `<?xml version='1.0'?>
      <methodCall>
        <methodName>execute_kw</methodName>
        <params>
          <param><value><string>${this.conf.db}</string></value></param>
          <param><value><int>${this.uid}</int></value></param>
          <param><value><string>${this.conf.apiKey}</string></value></param>
          <param><value><string>${model}</string></value></param>
          <param><value><string>write</string></value></param>
          <param><value><array><data>
            <value><array><data>${idsXml}</data></array></value>
            <value><struct>
              ${this._objToXmlStruct(data)}
            </struct></value>
          </data></array></value></param>
        </params>
      </methodCall>`;

    try {
      const resp = UrlFetchApp.fetch(`${this.conf.url}/xmlrpc/2/object`, {
        method: 'post',
        contentType: 'text/xml',
        payload: xml,
        muteHttpExceptions: true
      });
      return resp.getContentText().includes("<boolean>1</boolean>");
    } catch (e) {
      console.error(`Odoo Write Exception (${model}):`, e.message);
      return false;
    }
  }

  /**
   * Kayıtları siler (unlink).
   * @param {string} model Odoo model adı
   * @param {number[]} ids Silinecek kayıt ID'leri
   * @returns {boolean} Başarılı ise true
   */
  unlink(model, ids) {
    if (!ids || ids.length === 0) return true;

    const idsXml = ids.map(id => `<value><int>${id}</int></value>`).join('');

    const xml = `<?xml version='1.0'?>
      <methodCall>
        <methodName>execute_kw</methodName>
        <params>
          <param><value><string>${this.conf.db}</string></value></param>
          <param><value><int>${this.uid}</int></value></param>
          <param><value><string>${this.conf.apiKey}</string></value></param>
          <param><value><string>${model}</string></value></param>
          <param><value><string>unlink</string></value></param>
          <param><value><array><data>
            <value><array><data>${idsXml}</data></array></value>
          </data></array></value></param>
        </params>
      </methodCall>`;

    try {
      const resp = UrlFetchApp.fetch(`${this.conf.url}/xmlrpc/2/object`, {
        method: 'post',
        contentType: 'text/xml',
        payload: xml,
        muteHttpExceptions: true
      });
      const content = resp.getContentText();
      if (content.includes("<fault>")) {
        console.error(`Odoo Unlink Fault (${model}):`, content);
        return false;
      }
      return true;
    } catch (e) {
      console.error(`Odoo Unlink Exception (${model}):`, e.message);
      return false;
    }
  }

  /**
   * XML yanıtını JS nesne dizisine dönüştürür.
   * @private
   */
  _parseXmlResponse(xml) {
    try {
      const doc = XmlService.parse(xml);
      if (xml.includes("<fault>")) {
        console.error("Odoo API Fault:", xml);
        return [];
      }

      const params = doc.getRootElement().getChild('params');
      if (!params) return [];

      const dataNode = params.getChild('param').getChild('value').getChild('array').getChild('data');
      if (!dataNode) return [];

      return dataNode.getChildren('value').map(valNode => {
        let record = {};
        const struct = valNode.getChild('struct');
        if (!struct) return {};

        struct.getChildren('member').forEach(m => {
          const key = m.getChild('name').getText();
          const valWrapper = m.getChild('value');
          let val = "";

          if (valWrapper.getChild('string')) val = valWrapper.getChild('string').getText();
          else if (valWrapper.getChild('int')) val = parseInt(valWrapper.getChild('int').getText());
          else if (valWrapper.getChild('double')) val = parseFloat(valWrapper.getChild('double').getText());
          else if (valWrapper.getChild('boolean')) val = (valWrapper.getChild('boolean').getText() === "1");
          else if (valWrapper.getChild('array')) {
            const data = valWrapper.getChild('array').getChild('data');
            val = data ? data.getChildren('value').map(v => {
              if (v.getChild('int')) return parseInt(v.getChild('int').getText());
              if (v.getChild('string')) return v.getChild('string').getText();
              if (v.getChild('double')) return parseFloat(v.getChild('double').getText());
              return "";
            }) : [];
          }

          record[key] = val;
        });
        return record;
      });
    } catch (e) {
      console.error("XML Parse Hatası:", e.message);
      return [];
    }
  }

  /**
   * JS objesini XML-RPC struct formatına çevirir.
   * @private
   */
  _objToXmlStruct(data) {
    return Object.keys(data).map(key => {
      let val = data[key];
      let valXml = "";

      if (typeof val === 'string') valXml = `<string>${this._escapeXml(val)}</string>`;
      else if (typeof val === 'number') {
        valXml = Number.isInteger(val) ? `<int>${val}</int>` : `<double>${val}</double>`;
      }
      else if (typeof val === 'boolean') valXml = `<boolean>${val ? 1 : 0}</boolean>`;
      else if (Array.isArray(val)) {
        const arrayContent = val.map(v => {
          if (Array.isArray(v)) {
            return `<value><array><data>${v.map(subV => {
              if (Array.isArray(subV)) {
                return `<value><array><data>${subV.map(id => `<value><int>${id}</int></value>`).join('')}</data></array></value>`;
              }
              return Number.isInteger(subV) ? `<value><int>${subV}</int></value>` : `<value><string>${this._escapeXml(String(subV))}</string></value>`;
            }).join('')}</data></array></value>`;
          }
          return Number.isInteger(v) ? `<value><int>${v}</int></value>` : `<value><string>${this._escapeXml(String(v))}</string></value>`;
        }).join('');
        valXml = `<array><data>${arrayContent}</data></array>`;
        return `<member><name>${key}</name><value>${valXml}</value></member>`;
      }

      return `<member><name>${key}</name><value>${valXml}</value></member>`;
    }).join('');
  }

  /**
   * XML özel karakterlerini escape eder.
   * @private
   */
  _escapeXml(str) {
    if (!str) return '';
    return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
}
