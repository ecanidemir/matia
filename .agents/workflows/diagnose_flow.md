---
description: Matia Odoo Tani ve Yapilandirma Akisi
---

# Tani ve Yapilandirma Akisi — Matia Odoo Hub

Bu workflow, `odoo_matia` projesinde (Odoo 15, tek canli instance, SSH yok) sorulacak her yapilandirma sorusu ve hata analizi icin izlenmesi gereken adimlari tanimlar. Staging/deploy yoktur; canli DB'ye dokunan her adim salt-okunur varsayilip write icin onay alinir.

## 1. Soruyu netlestir

- Kullanici ne soruyor: yapilandirma aciklamasi mi, hata analizi mi, veri sorgusu mu?
- Hata analizi ise: hata metni/log tam mi? Eksikse iste (tarih, kullanici, ekran, tekrarlanabilirlik).
- Kapsam disi mi kontrol et: ozel modul gelistirme isteniyorsa `matia_stock_planning` disinda soz verme; sunucu dosya sistemi/log isteniyorsa SSH olmadigini acikla.

## 2. Hafiza recall

- `docs/discovery.md`'yi oku (sunucu kalici bilgileri, bilinen desenler).
- `.agents/memory/HOT.md`'yi oku + ilgili parmak izini Mem0 `search_memories` ile ara; bilinen desen varsa bastan uygula.
- Odoo 15 suphesi varsa: 19 kaliplarini (list/tree, privilege_id, JSON-2) ele, `.agents/rules.md` §6'yi uygula.

## 3. Sorgula (salt-okunur once)

- Baglanti: `odoo_matia_list_instances` (bos donerse `.agents/rules.md` §1 teşhis proseduru).
- Veri: once `search_read`/`read` ile ilgili model/ayar/kaydi oku (ornek: `ir.config_parameter`, `ir.module.module`, `stock.quant`, hata izindeki model).
- Supheli alan/metod: `fields_get` veya kucuk `search_read` ile dogrula; ezberden alan adi kullanma.
- Write gerekiyorsa: once kaydi goster, `.agents/rules.md` §4 canli-DB kuralina gore onay al (preview/dry-run paylas).

## 4. Analiz et ve cozum uret

- Bulgu -> kok neden -> cozum sirasiyla yaz, kisa tut.
- Multi-company suphesi varsa: sirket bagimsizligi (`parent-child yok`), `company_id=False` kayitlar, `allowed_company_ids` baglami ve `copy()` default-dict deseni kontrol edilir.
- Modul degisikligi gerekiyorsa: `matia_stock_planning` icinde mi, Python degisikligi deploy/restart gerektirir mi belirt; buyuk degisiklikte `@odoo-reviewer` subagent ile salt-okunur denetim iste.

## 5. Dokumante et

- Kalici bulgu (yapi, hata, cozum) `docs/discovery.md` sonuna eklenir (baslik + tarih).
- Kapsamli is (modul degisikligi, goc hazirligi) oncesi `plans/` altina plan yazilir.
- Gecici notlar/script ciktilari `scratch/`'te kalir.

## 6. Hafiza flush (oturum kapanmadan, ZORUNLU)

- Oturumda duzeltilen her hata `log_error` tool'u (`/log-error`) ile kayda girdi mi? Girilmemisse simdi cagir.
- `powershell -File scripts/lint_error_log.ps1` temiz mi? `[auto]` birikmisse kurate et, secret suphesi varsa temizle.
- 3. tekrara ulasan desen `HOT.md`'ye terfi etti mi?
