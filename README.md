# Assure

Release-testing for one class of AI-enabled B2B SaaS: a customer-support assistant that retrieves tickets and changes ticket state. The product verifies that tenant boundaries and business permissions survive changes to models, prompts, tools, retrieval, and application code.

This repository is a local runner plus a first hosted control plane. It is **not** a certification, a universal security score, or a runtime blocking product.

## What this iteration covers

- Deterministic keyword support demo with `safe`, `vulnerable`, and `reject_all` modes
- `assure doctor`, `assure run`, and `assure upload`
- Cases: `POS-01` (legitimate access), `TEN-01` (cross-tenant read), `ACT-01` (cross-tenant write), `OBS-01` (missing observer)
- FastAPI control plane, maintenance worker, Postgres, React dashboard (five screens)

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Node 20+ for the dashboard
- Docker optional, for the full Compose stack

```powershell
uv sync --group dev
```

## Local fail / fix / retest

Start the demo (vulnerable by default):

```powershell
$env:ASSURE_TARGET_MODE="vulnerable"
uv run assure-demo
```

In another terminal:

```powershell
uv run assure doctor --config assure.yaml
uv run assure run --config assure.yaml --suite suites/support_v1 --output reports
```

Expected in vulnerable mode: `POS-01` PASS, `TEN-01`/`ACT-01` FAIL, `OBS-01` INCONCLUSIVE, CLI exit `1`.

Switch the demo to safe mode (restart with `$env:ASSURE_TARGET_MODE="safe"` or `POST /admin/mode`) and rerun. `TEN-01` and `ACT-01` PASS. `OBS-01` stays INCONCLUSIVE and the gate exits `2` because missing evidence is not a pass.

Reports are written to `reports/summary.json`, `reports/manifest.json`, and `reports/report.html`. Target text is escaped. There is no numeric score.

## Hosted product

```powershell
uv run assure-api
uv run assure-worker
cd apps/web
npm install
npm run dev
```

Upload a completed local run:

```powershell
uv run assure upload --config assure.yaml --manifest reports/manifest.json --summary reports/summary.json
```

Open http://127.0.0.1:5173

Seeded identities:

| Token | Org | Role |
|---|---|---|
| `org-a-editor-token` | Acme Support | editor |
| `org-a-viewer-token` | Acme Support | viewer |
| `org-a-runner-token` | Acme Support | runner |
| `org-b-editor-token` | Other Corp | editor |
| `org-b-runner-token` | Other Corp | runner |

The control plane never stores target credentials and never fetches the demo URL.

## Compose

```powershell
docker compose -f infra/docker-compose.yml up --build
```

Then run `assure` against `http://127.0.0.1:8080` and upload to `http://127.0.0.1:8000`.

To demonstrate the fix path, restart the demo with `ASSURE_TARGET_MODE=safe`.

## Tests

```powershell
uv run pytest
```

## Policy

The authorization oracle is [docs/POLICY.md](docs/POLICY.md). A guessed rule is not a valid finding.

## Fine-tune later

OIDC / GitHub OIDC, FORCE RLS, the remaining nine cases, JUnit/PDF, and production hosting.
