---
description: Matia Odoo tanı akışını adım adım uygula (soruyu netleştir → recall → salt-okunur sorgula → analiz et → dokümante et → hafıza flush)
agent: build
---

`.agents/workflows/diagnose_flow.md` dosyasını oku ve aşağıdaki akışı $ARGUMENTS kapsamında (boşsa mevcut görevin kapsamında) sırayla uygula:

1. **Soruyu netleştir** — yapılandırma mı, hata mı, veri sorgusu mu; hata ise log tam mı, kapsam dışı mı?
2. **Recall** — `docs/discovery.md` + `.agents/memory/HOT.md` + Mem0 `search_memories`; Odoo 19 kalıplarını ele.
3. **Sorgula** — önce salt-okunur (`search_read`/`read`, `fields_get` doğrulama); write gerekiyorsa kaydı gösterip onay al.
4. **Analiz** — bulgu → kök neden → çözüm; multi-company şüphesinde şirket bağlamını kontrol et.
5. **Dokümante** — kalıcı bulguyu `docs/discovery.md` sonuna ekle.
6. **Hafıza flush** — düzeltilen hatalar `/log-error` ile kayda girdi mi, `scripts/lint_error_log.ps1` temiz mi, 3. tekrar HOT'a terfi etti mi?

Her adımda `.agents/rules.md` ve `AGENTS.md` kurallarına uy. Canlı DB write ve modül kur/kaldır öncesi onay al (staging yok).
