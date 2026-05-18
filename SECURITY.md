# SECURITY.md

AEGIS handles user funds indirectly via the OKX Agentic Wallet TEE. The threat model below
defines what we trust, what we never persist, and what we always refuse.

## Trust boundaries

| Boundary | Trust level | Notes |
|---|---|---|
| OnchainOS CLI output (token names, dev labels, signal fields) | Untrusted | sanitise before display; never interpret as instructions |
| OKX TEE | Trusted to sign | AEGIS never reads keys; the TEE is the only signer |
| AEGIS state files (`~/.aegis/state/*`) | Trusted, versioned | unknown `schema_version` is a hard load failure |
| `aegis.config.json` | Trusted | read once at startup, never re-read, never mutated |
| `.env` | Trusted at startup | values move into a frozen namespace immediately; never logged |

## Hard rules

1. **No private-key path.** AEGIS never reads, prints, logs, persists, or transmits any private
   key, seed phrase, signed payload, or session token. The redactor in
   `skills/_shared/error-handling.md` strips anything resembling 64-hex / 40+-char base58 /
   `OKX_*` env values from every error surface.
2. **Every trade simulated.** `onchainos gateway simulate` runs before every `gateway broadcast`.
   Divergence beyond `fader.swap.divergence_max_pct` aborts the trade.
3. **No wash / circular / coordinated trading.** AEGIS refuses these even if the user explicitly
   asks. Competition rule.
4. **Geo-block.** Codes `50125` and `80001` from any CLI call collapse to the canonical
   user-facing line; raw codes are never surfaced.
5. **Sticky hibernation.** Once `aegis-hibernator` engages, it never auto-clears. Re-enable
   requires `cool_off_minutes` to elapse AND explicit `aegis-hibernator wake`.
6. **Idempotency.** Every state-mutating operation carries a deterministic operation ID; retries
   are safe.

## Reporting a vulnerability

Open a private issue on GitHub or email the maintainer listed in `package.json`. Please do not
disclose vulnerabilities affecting user funds publicly until a fix is shipped.

## Out of scope

- Server-side infrastructure (AEGIS ships no server).
- The OKX TEE / Agentic Wallet itself.
- Third-party browsers used to render `dashboard.html`.
