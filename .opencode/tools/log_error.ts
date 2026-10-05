import { tool } from "@opencode-ai/plugin"
import { appendFile, readFile } from "node:fs/promises"
import path from "node:path"

// Matia Odoo Hub: duzeltilen hatanin deterministik cift yazimi.
// Kullanim: once hatayi DUZELT, kok nedeni anla, sonra bu tool'u cagir.
// Secret (sifre, API key icerigi) argumanlara ASLA yazma.

export default tool({
  description:
    "Duzeltilen bir dev hatasini kalici hafizaya kaydet: .agents/memory/errors-log.md dosyasina tek satir ekler ve Mem0 bulut hafizasina yazar. Once hatayi duzeltip kok nedeni bul, sonra cagir.",
  args: {
    fingerprint: tool.schema
      .string()
      .describe("Kisa parmak izi: arac + semptom, ornek: 'odoo_matia MCP bos env (yanlis proje URL)'"),
    cause: tool.schema.string().describe("Kok neden, tek cumle, ornek: 'User-level env workspace .env'i eziyordu'"),
    fix: tool.schema.string().describe("Cozum, tek cumle, ornek: 'User-level degisken silindi + start-opencode.ps1 ile baslat'"),
    scope: tool.schema
      .enum(["project", "global"])
      .optional()
      .describe("Mem0 kapsami. Varsayilan project. Arac-genel ders (opencode/PS/git) ise global."),
  },
  async execute(args, context) {
    const date = new Date().toISOString().slice(0, 10)
    const line = `${date} | ${args.fingerprint} | ${args.cause} -> ${args.fix}\n`
    const file = path.join(context.worktree, ".agents/memory/errors-log.md")

    let fileResult = "atlandi (ayni parmak izi mevcut)"
    try {
      const cur = await readFile(file, "utf8").catch(() => "")
      if (!cur.includes(args.fingerprint)) {
        await appendFile(file, line, "utf8")
        fileResult = "eklendi"
      }
    } catch (e) {
      fileResult = `hata: ${String(e).slice(0, 120)}`
    }

    let mem0Result = "atlandi (MEM0_API_KEY yok)"
    const key = process.env.MEM0_API_KEY
    if (key) {
      try {
        const res = await fetch("https://api.mem0.ai/v1/memories/", {
          method: "POST",
          headers: { Authorization: `Token ${key}`, "Content-Type": "application/json" },
          body: JSON.stringify({
            messages: [{ role: "user", content: line }],
            user_id: "odoo-matia",
            metadata: { project: "odoo-matia", source: "opencode-log-error-tool", scope: args.scope ?? "project" },
          }),
        })
        mem0Result = res.ok ? "kaydedildi" : `basarisiz (HTTP ${res.status})`
      } catch {
        mem0Result = "basarisiz (ag hatasi)"
      }
    }

    return `errors-log.md: ${fileResult}; mem0 [${args.scope ?? "project"}]: ${mem0Result}`
  },
})
