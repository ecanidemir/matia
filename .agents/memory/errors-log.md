# errors-log.md — Ham Hata Kaydı (Matia Odoo Hub)

> Her düzeltilen dev hatası (kod, MCP, yapıştırılan traceback) buraya **tek satır** eklenir.
> Format: `YYYY-MM-DD | [O15] parmakizi (araç + semptom) | kök neden -> çözüm`
> Traceback yapıştırma, secret yazma (`ODOO_PASSWORD`, API key). Aynı parmakizi 2. kez
> görülürse satırı güncelle, 3. tekrarda `HOT.md`'ye terfi ettir. Mem0'ya da `add_memory`
> (scope `project`) ile aynı tek satırı yaz.

2026-09-25 | [O15] odoo_matia MCP yanlis projeye baglandi (test-argerobotik URL) | kok neden: Windows User-level env ODOO_URL/DB/USERNAME workspace .env'i eziyordu -> cozum: User-level 3 degisken silindi + opencode scripts/start-opencode.ps1 ile baslatilir
2026-09-25 | [O15] scripts/load_env.ps1 .env bulamadi | kok neden: script iki ust klasordaki odoo/.env dosyasini ariyordu (o dosya yok) -> cozum: repo kokundeki .env'i okuyacak sekilde duzeltildi, kalici baslatma icin start-opencode.ps1 kullanilir
2026-09-25 | [O15] company_id=False phantom BOM copy "Uyumsuz sirket kayitlari" | kok neden: satirlar check_company=True alanlara sahipken copy _check_company_auto validasyonuna takiliyor -> cozum: copy(id, {'default': {'company_id': 1}}) ile sirketli kopya olustur
2026-10-05 | [O15] upgrade ParseError: View inheritance may not use attribute 'string' as selector | inherit secici olarak page `string` attribute kullanmisti, Odoo 15 bunu yasakliyor -> xpath expr //page[field[@name='line_ids']] secici + yeni page name=draft_rfqs
