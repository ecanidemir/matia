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
2026-10-06 | [O15] tree+cost TypeError int object is not subscriptable (_last_buy_vals order_id) | _mpp_last_buys order_id'yi int donerken _last_buy_vals [id,name] varsayip [0] okudu -> buy_dt oncelikli + order_id normalize (list/tuple->[0], int aynen) ile order_dates okuma
2026-10-06 | [auto] APIError [400]: Requests ending with a model turn are not supported. | kürate edilmedi -> /log-error ile işle
2026-10-06 | [O15] production plan usage qty hep 1.0 | get_tree_with_cost level-0 satırlarda bom_qty 1.0 sabit yazılmış, bl.product_qty okunmamış -> matia_procurement_plan.py:1867 float(bl.product_qty or 1.0) yapıldı
2026-10-06 | [O15] mpp auto-fill double-netting + lineless avail 0 | Auto-fill N-avail yazip cascade bir kez daha dusuyordu (cift-netting); satirsiz top avail 0 okunuyordu -> Needed=N brut yazilir, stok tek elde netlenir; satirsiz top canli split stok gosterir (branch, staging verify bekliyor)
2026-10-06 | [auto] APIError [503]: The backend is temporarily overloaded. Please retry. | kürate edilmedi -> /log-error ile işle
2026-10-06 | [O15] prices manufacture/subcontract filtresi TR kullanicida bos + unknown | stock.location.route adlari ir.translation ile cevriliyor; classifier Ingilizce substring bakiyordu, TR oturumda Manufacture/Subcontract eslesmedi -> Route name okunan 3 nokta lang='en_US' ile okunuyor (15.0.2.4.0); cevrilebilir display name ile eslestirme yasak
2026-10-07 | [O15] plan rolled UoM: ham BOM qty x stok-UoM fiyati (E2CBAN03 972$ vs 130$) | Patlatma ham BOM qty sakliyordu, tum para/stok mat satir-UoM bazli -> _mpp_norm_bom_qty helper (cocuk stok UoM cevrim, fail-safe ham) + 5 cagri; simulasyon 130.34 tuttu
2026-10-08 | [O15] E1RCRN01 Std 0.6126 company-context leak (TR/US force_company yoklugu) | standard_price company-dependent okunuyordu; pinsiz read US degerini (30.0) TR kuruyla carpip 0.6126 uretti -> force_company TR/US dual std read + docstring duzeltme (commit 5d0e831); deploy sonrasi staging 3.93*/prod 4.26 beklenir
2026-10-08 | [O15] Prices USD bos hucre (0.10 TRY -> 0.00 USD) | res.currency._convert hedef kur yuvarlamasina (USD 0.01) gore yuvarliyor; sub-cent TRY fiyatlar 0.0 oluyordu -> _last_buy_vals, _mpc_price_map ve tree fallback cagrilarina round=False eklendi (commit 388ea34)
2026-10-08 | odoo15 wrong-instance upgrade (prod yerine staging varsayımı) | Yan etki öncesi ODOO_URL doğrulanmadı (prod sanılan env staging çıktı) -> Write öncesi URL'yi yazdırıp teyit et + önce smoke_after_deploy.py çalıştır
2026-10-08 | odoo15 deploy-without-upgrade total outage (UndefinedColumn res_users) | Yeni kod restart ile yuklendi ama modul Upgrade atlandi, kolon olusmadi -> Deploy sonrasi smoke_after_deploy.py YESIL olmadan haber verme; auth cokerse kod-revert + redeploy
2026-10-08 | [O15] edit-newline merge SyntaxError (procurement_export satir birlesmesi) | oldString sonundaki newline dustu, iki statement tek satira yapisip SyntaxError verdi -> edit sonrasi py_compile sart; cok-satirli anchor`da sondaki boslugu degistirme
2026-10-09 | powershell inline-regex terminator hatasi | Regex icinde gomulu tirnak PowerShell parser'i bozdu -> Karmasik deseni grep tool'una birakip shell komutlarini basit tut
2026-10-09 | [auto] APIError [403]: Upstream request failed: An active OpenCode Go subscription is required to use Go models. | kürate edilmedi -> /log-error ile işle
