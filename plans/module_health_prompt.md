# RUN PROMPT — Module Health Overhaul (ayrı sessionda çalıştır)

Aşağıdaki metnin tamamını yeni bir sessiona yapıştır. Başlamadan önce
tüm izinleri (bash, dosya düzenleme, MCP okuma, subagent) onayla;
sonrasında 10 saat boyunca başında kimse olmayacak.

---

`C:\Users\TKA\Desktop\antigravity\odoo\odoo_matia` projesindesin
(Odoo 15, tek canlı DB, SSH yok, staging panel-deploy ile çalışır).
`matia_stock_planning` modülünün TAMAMINI baştan sona, satır satır,
saatler harcayarak elden geçireceksin: tüm buglar, tüm ölü kodlar,
profesyonel kalite, sadeleştirme, stabilite, açılma/çalışma hızı.

ÖNCE ŞU SKILL'LERİ YÜKLE (sırayla, hepsi):
1. `odoo-15` — tüm Odoo kararlarında tek otorite; çelişki olursa bu kazanır.
2. `systematic-debugging` — her bug için hipotez→kanıt→düzeltme→doğrulama.
3. `test-driven-development` — runtime yok; her public metodun sözleşmesini
   (girdi→çıktı→kenar durum) koddan doğrulayarak Ek-A tablosuna işle.
4. `verification-before-completion` — "bitti" demeden önce tüm kapıları çalıştır.
5. `git-workflow` — branch + conventional commit disiplini.
6. `error-memory` — her düzeltilen hatayı `log_error` ile kaydet.

SONRA `plans/module_health_overhaul.md` dosyasını baştan sona UYGULA
(Faz 0→5, Ek-A dahil). Plan açıksa plana uy; plan ile skill çelişirse
skill kazanır, plan ile `.agents/rules.md` §6 çelişirse §6 kazanır.

OTONOMİ KURALLARI (10 saat başıboş çalışacaksın, bunlara harfiyen uy):
- `question` tool'unu ASLA kullanma. Karar gerektiren her yerde en makul
  seçeneği seç, kararını rapor dosyasına bir satırla not et, devam et.
- İzin/onay bekleyerek DURMA. Başta tüm izinler verildi kabul et.
- Shell her zaman non-interactive: editör/pager/REPL yasak, `-y/--yes`
  bayrakları, `python -c`/tek komutlar, timeout'lu komutlar.
- YASAKLAR: canlı Odoo'ya write (preview_write/execute_write/chatter_post
  dahil — salt-okunur search_read/fields_get serbest), `git push`,
  commit --amend, staging/deploy/upgrade aksiyonları, `.env` okuma-yazma,
  secret loglama, `docs/discovery.md` ve log dosyalarına overwrite
  (oku + sona ekle), Capacity sayfasını etkileyen değişiklik.
- Her faz bitiminde `todowrite` güncelle + conventional-commit at
  (`chore(stock-planning): ...`); branch: `chore/module-health-overhaul`.
- Bağlam şişerse `compress` ile kapanmış fazları özetle, çalışmaya devam et.
- Bitince `plans/module_health_report.md` yaz: bug listesi (dosya:satır +
  kök neden), ölü kod, sadeleştirme, performans önce/sonra, karar notları
  ve İNSAN ADIMLARI (push, staging deploy+upgrade, canlı test senaryoları).
  Rapor bitmeden işi bitmiş sayma.
