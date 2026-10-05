---
description: Düzeltilen bir hatayı 1-2 satırla kalıcı hafızaya kaydet (Mem0 + errors-log.md, secret asla)
---

Aşağıdaki hata için `log_error` tool'unu çağır (fingerprint, cause, fix argümanlarıyla; araç-genel ders ise scope `global`). Tool yoksa `error-memory` skill'indeki ritüeli manuel uygula: $ARGUMENTS

1. **Recall** — `.agents/memory/HOT.md`'yi oku, Mem0'da `search_memories` ile parmak izini ara.
2. **Log (çift yazım, max 2 satır)** —
   - `.agents/memory/errors-log.md` sonuna tek satır ekle: `YYYY-MM-DD | [O15] parmak izi | kök neden -> çözüm`
   - Mem0 `add_memory` (scope `project`; araç-genel ders ise `global`) — metin `[O15]` önekiyle başlar (hub `[O19]` yazar; çapraz arama sonucunda sürüm tek bakışta belli olur).
3. **Promote** — aynı parmak izi 3. kez görülüyorsa `HOT.md`'ye tek satır olarak taşı (≤30 satır sınırını koru).

Kurallar: traceback yapıştırma, secret (`ODOO_PASSWORD`, API key) ASLA loglama. Aynı parmak izi 2. kez görülürse satırı güncelle, yeni satır ekleme.
