---
title: Automatron
emoji: 🛰️
colorFrom: indigo
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: Multi-agent decision support for space, quant, e-commerce and real estate
---

# Automatron

Multi-agent decision support for high-stakes work in four sectors: space operations,
quantitative finance, e-commerce disputes, and real estate due diligence.

A coordinator agent plans the work; researcher, analyst, and executor agents gather
evidence, run deterministic analysis, and assemble a decision brief. Every workflow ends
at a human approval gate — the system prepares the decision, it never takes it.

## What it does

Four sectors, three workflows each. Every one ends at a human approval gate: the
system prepares a decision and never takes it.

| Sector | Workflows |
|---|---|
| **Space** | conjunction triage · anomaly root cause · licensing and spectrum packet |
| **Quant** | alpha audit · trade approval gate · trading-code compliance review |
| **E-commerce** | return dispute · chargeback representment · seller appeal review |
| **Real estate** | due-diligence red flags · permit pre-screen · dispute summary |

Two rules shape the whole design:

**Every number a person sees comes from a Python tool, never from model free-text.**
A brief that cites a figure no tool produced fails verification and is sent back.

**The system recommends; a person decides.** No orders are placed, no filings are
made, no permits are decided, no accounts are actioned. Levels like
`HUMAN_APPROVAL_REQUIRED` or `ESCALATE_TO_COUNSEL` route work to the right person.

Sector rules, thresholds and sample data are configuration, not code, and are
invented for this project. They belong to fictional firms, cities and jurisdictions
and are illustrative only — see the disclaimers in `config/sectors.yaml`.

## Architecture

A coordinator plans the work; researcher, analyst and executor agents run it under a
per-role tool allowlist enforced in code. Results are assembled into a decision brief,
checked by a deterministic verifier, and held at the approval gate.

- **LangGraph** for orchestration, with parallel step dispatch, a capped revision
  loop, and the approval interrupt.
- **LlamaIndex + Qdrant** for retrieval, hybrid dense and sparse, isolated per sector.
- **Six providers, eleven model slots**, with failover on rate limits, quota and
  context overflow. See `config/providers.yaml` and `DECISIONS.md`.
- **Hash-chained audit log**: every decision is recorded and the chain is verifiable.

Application logic lives in the five notebooks under `notebooks/`, which build into
importable modules. `DECISIONS.md` records every design choice and why.

## Status

All four sectors are built: twelve workflows, each runnable offline against the
bundled samples. See `DECISIONS.md` for the design record.

## Running it

Application logic lives in the notebooks under `notebooks/`; `scripts/build_notebooks.py`
turns them into the importable modules in `automatron_build/`.

```bash
pip install -r requirements-dev.txt
python scripts/build_notebooks.py       # notebooks -> automatron_build/*.py
AUTOMATRON_FAKE_LLM=1 python app.py     # offline, no keys needed
python app.py                           # with real keys from .env
pytest -q                               # unit and integration, offline
pytest -q -m live                       # live provider checks, needs keys
python tests/eval/run_eval.py           # golden scenarios
```

No keys are needed to try it: with `AUTOMATRON_FAKE_LLM=1` the real tools still run
and only the model is replaced, so every workflow is demonstrable offline.

### Configuration

Copy `.env.example` to `.env` and fill in what you have. Everything is optional —
the app starts in demo mode and says so when no provider key is present.

| Variable | Purpose |
|---|---|
| `GROQ_API_KEY`, `GROQ_API_KEY_2`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `MISTRAL_API_KEY`, `CEREBRAS_API_KEY` | Provider keys. Any subset works; the router uses what it has. |
| `QDRANT_URL`, `QDRANT_API_KEY` | Vector store. Falls back to local storage when unreachable. |
| `APP_USERNAME`, `APP_PASSWORD` | HTTP basic auth. **Without a password every API route is open**, which is fine locally and not fine anywhere reachable. |
| `PORT` | Defaults to 7860; Cloud Run injects its own. |
| `LOG_LEVEL`, `MAX_PARALLEL_STEPS`, `RATE_LIMIT_PER_IP_PER_HOUR` | Runtime tuning. |
| `RUN_TIMEOUT_S` | A run's ceiling, default 600 s. Free provider tiers queue rather than refuse — a single queued call has been seen taking four minutes — so this allows for a degraded provider chain, not a healthy one. |

Thresholds per sector live in `config/sectors.yaml` and can be overridden by the
environment variables listed in `.env.example`.

## Disclaimers

This is decision-support software built as a portfolio project. It is not
investment, legal, compliance, engineering or regulatory advice, and it is not
operational conjunction screening. All bundled data is synthetic and generated from
fixed seeds: no real customer, order, seller, property, person or security appears
anywhere in it. Sector rules are invented and belong to fictional organisations.

A qualified human — an operator, trader, compliance officer, specialist, attorney or
permit examiner as appropriate — makes every decision this system prepares.

## Continuous integration and deployment

`ci` runs on every push and pull request to `main` and `develop`: lint, the notebook build,
a check that no notebook carries stored output, the offline test suite, and a container
build. The suite runs against the fake model, so it needs no keys and costs nothing.

`deploy` runs on a push to `main`. It calls `ci` first and releases only if it passes, then
deploys to Cloud Run and polls the health endpoint until the new revision answers.

### Hugging Face Space

The Space builds from the `Dockerfile`; the front matter at the top of this file is
its card. Nothing here is committed to the repository — the token is typed at the
prompt and the secrets live in the Space's own settings.

1. **Create the Space** — huggingface.co → New Space → name `automatron` →
   SDK **Docker** → template **Blank** → hardware **CPU basic (free)**.
2. **Add secrets** under Settings → Variables and secrets:
   `GROQ_API_KEY`, `GROQ_API_KEY_2`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`,
   `MISTRAL_API_KEY`, `QDRANT_URL`, `QDRANT_API_KEY`, and `APP_PASSWORD`.
   Add as plain variables: `LOG_LEVEL=INFO`, `MAX_PARALLEL_STEPS=2`.

   `APP_PASSWORD` is not optional on a public Space. Without it every API route is
   open to anyone who finds the URL.
3. **Create a write token** at huggingface.co/settings/tokens.
4. **Push**, giving the token as the password when git asks:

   ```bash
   git remote add space https://huggingface.co/spaces/<hf-username>/automatron
   git push space develop:main
   ```
5. **Watch the build logs.** The app is live once they show Uvicorn running. A free
   Space sleeps when idle and restarts on the next visit; its runtime disk resets
   each time, which is expected — nothing durable is kept there.

The repository's binaries are seven synthetic PNGs of about a kilobyte each, and the
largest tracked file is a 584 KB CSV, so Git LFS is not used. If a future sample
pushes the repository past what plain git accepts, track that file with LFS rather
than adding LFS across the board.

### After a deploy

```bash
python tests/deploy_smoke.py https://<service-url> --password "$APP_PASSWORD"
```

Read-only: it starts no runs. It checks that the liveness probe answers without
credentials, that all four sectors registered, that the service is running against
real providers rather than the fake model, that the API refuses an anonymous caller,
and that at least one provider slot is usable. It exits non-zero on the first failure,
so it can gate a release.

### Cloud Run: one-time setup

Authentication uses workload identity federation, so no service account key is ever stored
in the repository. Run these once, replacing the project and repository if they differ:

```bash
PROJECT_ID=automatron-508916
REPO=Arnavdsp/Automatron
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')

gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com iamcredentials.googleapis.com

gcloud iam service-accounts create automatron-deploy --display-name="Automatron deploy"
DEPLOYER="automatron-deploy@${PROJECT_ID}.iam.gserviceaccount.com"

for role in roles/run.admin roles/cloudbuild.builds.editor \
            roles/artifactregistry.admin roles/iam.serviceAccountUser \
            roles/storage.admin; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${DEPLOYER}" --role="$role"
done

gcloud iam workload-identity-pools create github --location=global \
  --display-name="GitHub Actions"
gcloud iam workload-identity-pools providers create-oidc github \
  --location=global --workload-identity-pool=github \
  --display-name="GitHub" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository=='${REPO}'" \
  --issuer-uri="https://token.actions.githubusercontent.com"

# Only this repository may impersonate the deploy account.
gcloud iam service-accounts add-iam-policy-binding "$DEPLOYER" \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github/attribute.repository/${REPO}"

gcloud iam workload-identity-pools providers describe github \
  --location=global --workload-identity-pool=github --format='value(name)'
```

Store the secrets the service reads at runtime, and grant the runtime account access:

```bash
for name in groq-api-key groq-api-key-2 gemini-api-key openrouter-api-key \
            mistral-api-key qdrant-url qdrant-api-key app-password; do
  printf '%s' "<value>" | gcloud secrets create "$name" --data-file=-
done

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role=roles/secretmanager.secretAccessor
```

`app-password` is not optional. Without it every API route is open, and the service is
deployed with public access, so the workflow treats it as required and the deploy fails
rather than publishing an unauthenticated service.

Then add three repository secrets under Settings → Secrets and variables → Actions:

| Secret | Value |
|---|---|
| `GCP_PROJECT_ID` | the project id |
| `GCP_WIF_PROVIDER` | the provider resource name printed by the last command above |
| `GCP_DEPLOY_SERVICE_ACCOUNT` | `automatron-deploy@<project-id>.iam.gserviceaccount.com` |

Set a billing budget with alerts before the first deploy. `--max-instances 1` caps how
much can run at once, but a budget is the thing that tells you if something is wrong.

## Author

Arnav
