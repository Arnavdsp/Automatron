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

## Status

Under construction. See `DECISIONS.md` for design notes.

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

## Continuous integration and deployment

`ci` runs on every push and pull request to `main` and `develop`: lint, the notebook build,
a check that no notebook carries stored output, the offline test suite, and a container
build. The suite runs against the fake model, so it needs no keys and costs nothing.

`deploy` runs on a push to `main`. It calls `ci` first and releases only if it passes, then
deploys to Cloud Run and polls the health endpoint until the new revision answers.

### One-time setup for deployment

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
