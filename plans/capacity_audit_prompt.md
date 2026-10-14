# RUN PROMPT — Capacity denetim bulgularını uygula (ayrı sessionda çalıştır)

Aşağıdaki metnin tamamını yeni bir sessiona yapıştır. Yeni session'ı masaüstündeki
**Matia OpenCode** kısayoluyla aç (`.env`'i yükleyip proje kökünde başlatır; aynı işi terminalden
`powershell -ExecutionPolicy Bypass -File scripts/start-opencode.ps1` de yapar).

---

`C:\Users\TKA\Desktop\antigravity\odoo\odoo_matia` projesindesin (Odoo 15, tek canlı DB, SSH yok,
XML-RPC). `matia_stock_planning` modülündeki denetim bulgularını uygulayacaksın.

ÖNCE ŞU SKILL'LERİ YÜKLE (sırayla): `odoo-15` (tek otorite; çelişmede bu kazanır),
`systematic-debugging`, `verification-before-completion`, `git-workflow`, `error-memory`.

SONRA SIRAYLA OKU: `docs/discovery.md`, `.agents/memory/HOT.md`,
`plans/capacity_audit_2026-10-12.md` (görev listesi budur).

GÖREV SIRASI:
1. §0 Bloker: staging salt-okunur sorgularla A1–A8 sayı-kanıtını kapat (tek ürün örneği).
2. B1→B6 (kritik+yüksek backend), her birinde şüpheli satırı `fields_get`/okumayla doğrula.
3. B7→B15 (orta+düşük backend).
4. C1→C9 (UI; `_t()` + rozet/ikon dual-signal).

KURALLAR:
- INSTANCE: tüm okuma/doğrulama STAGING (`staging-matia.odoobulut.com`) üzerinde yapılır.
  CANLI DB (`matia.odoobulut.com`) SALT-OKUNUR referanstır — canlıya write, upgrade, deploy YOK.
  Staging'de son hale gelen işi kullanıcı manuel olarak prod'a alır; sen prod'a taşıma yapma.
- Canlı DB'ye write YOK (onay almadan modül kur/kaldırma, toplu update, config değişikliği yok);
  `search_read`/`fields_get` serbest. Python değişikliği deploy/restart ister — kodu yaz, deploy ETME.
- Branch: `fix/capacity-audit-2026-10-12`; conventional commit; her grup bitiminde `todowrite` + commit.
- Odoo 15 yasakları: `list` view, `privilege_id`, `models.Constraint/Index`, OWL2, `env.sudo()` yok;
  `copy(default)` dict, sudo deseni `with_context(allowed_company_ids,active_test=False).sudo().env`.
- Her düzeltilen hatayı `log_error` ile kaydet; kalıcı bulguyu `docs/discovery.md` sonuna ekle (overwrite yasak).
- Context şişerse `compress` ile kapanmış grupları özetle.
- Bitince raporla: uygulanan (dosya:satır), atlanan + gerekçesi, İNSAN ADIMLARI (staging deploy+upgrade, test senaryoları).
