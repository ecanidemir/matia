import type { Plugin } from "@opencode-ai/plugin"
import { appendFile, readFile } from "node:fs/promises"
import path from "node:path"

// Matia Odoo Hub: oturum hatalarini otomatik ham log'a dusurur.
// Kurasyon (kok neden + cozum + Mem0) hala `log_error` tool'u / `/log-error`
// komutu ile yapilir — bu plugin sadece "hicbir hata kaybolmasin" garantisidir.

const LOG_REL = ".agents/memory/errors-log.md"
const MAX_AUTO_LINES = 200

function redact(s: string): string {
  return s
    .replace(/[A-Za-z0-9_]*?(API[_-]?KEY|PASSWORD|TOKEN|SECRET)[A-Za-z0-9_]*?\s*[:=]\s*\S+/gi, "$1=[REDACTED]")
    .replace(/Bearer\s+\S+/gi, "Bearer [REDACTED]")
    .replace(/\b(sk|m0|ghp|gho|glpat)_[A-Za-z0-9_-]+/g, "[REDACTED]")
}

function summarize(event: any): string {
  // session.error olayinin FAYDALI kismini cikar: hata adi + mesaji.
  const props = event?.properties ?? {}
  const err = props.error ?? {}
  const name = err.name ?? event?.type ?? "session.error"
  const data = err.data ?? {}
  const rawMsg = err.message ?? data.message ?? data.error ?? data.statusText ?? ""
  const code = data.statusCode ?? data.status ?? data.code ?? err.code ?? ""
  const head = code ? `${name} [${code}]` : `${name}`
  const body = typeof rawMsg === "string" ? rawMsg : JSON.stringify(rawMsg)
  if (!body) return "" // mesaj icerigi yoksa sinyal yok demektir
  return `${head}: ${body}`.replace(/\s+/g, " ").trim()
}

export const ErrorLogger: Plugin = async ({ client, worktree }) => {
  return {
    event: async ({ event }) => {
      if (event.type !== "session.error") return
      try {
        const msg = redact(summarize(event)).slice(0, 160)
        // Sinyal yoksa olu satir yazma (mesaj icerigi tasimayan olaylari atla)
        if (!msg) return
        const file = path.join(worktree, LOG_REL)
        const cur = await readFile(file, "utf8").catch(() => "")
        const lines = cur.split("\n")
        if (lines.filter((l) => l.includes("[auto]")).length >= MAX_AUTO_LINES) {
          await client.app.log({
            body: { service: "error-logger", level: "warn", message: "auto log cap reached, skipping" },
          })
          return
        }
        if (cur.includes(msg)) return // dedup: aynı hata zaten loglanmış
        const date = new Date().toISOString().slice(0, 10)
        await appendFile(file, `${date} | [auto] ${msg} | kürate edilmedi -> /log-error ile işle\n`, "utf8")
      } catch (e) {
        await client.app.log({
          body: { service: "error-logger", level: "warn", message: `skip: ${String(e).slice(0, 120)}` },
        })
      }
    },
  }
}
