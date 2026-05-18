# preflight.md

Run before any `onchainos` CLI command from any AEGIS skill.

## 1. Verify CLI is installed

```bash
which onchainos
```

If missing, install per the OKX reference repo:

```bash
npx skills add okx/onchainos-skills
```

## 2. Verify version

```bash
onchainos --version
```

If the CLI version is greater than the skill version declared in this Skill's frontmatter, warn
the user: "OnchainOS CLI is newer than this skill — consider reinstalling AEGIS to pick up new
command signatures." Do not abort; continue.

## 3. Verify credentials

`OKX_API_KEY`, `OKX_SECRET_KEY`, and `OKX_PASSPHRASE` must be set in the environment. AEGIS reads
them once at startup, moves them into a frozen namespace, and never re-reads. If any are missing:

```
Missing OKX_API_KEY (or OKX_SECRET_KEY / OKX_PASSPHRASE). Copy .env.example to .env and fill in
your sandbox values. See README.md → Quick start.
```

## 4. Verify wallet status (only for skills that broadcast)

```bash
onchainos wallet status
```

- Not logged in → ask the user to run `onchainos wallet login <email>`.
- Multiple accounts → list and let the user pick.

## 5. Verify chain scope

Every swap, signal scan, and broadcast in AEGIS runs only on Solana (`501`) and X Layer (`196`).
Other chains are refused at the boundary with the message in `chain-support.md`.

## 6. Verify AEGIS state dir

```bash
mkdir -p ~/.aegis/state/blackbox ~/.aegis/logs
```

Idempotent; safe to repeat.
