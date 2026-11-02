---
title: Automatron

colorFrom: indigo

sdk: docker
app_port: 7860
Demo:  https://automatron-413625269952.us-central1.run.app 
license: mit
short_description: Multi-agent decision support for space, quant, e-commerce and real estate
---

# Automatron 

Multi-agent decision support for high-stakes workflows.

Automatron is a multi-agent system that helps structure complex decisions in four domains: space operations, quantitative finance, e-commerce and real estate.

Instead of sending a request directly to an LLM, Automatron breaks the task into specialised steps, gathers evidence, runs deterministic analysis, verifies the result, and stops at a human approval gate.

The system prepares the decision; a person makes it.

---

## How it works

```text
                         USER REQUEST
                              |
                              v
                       +--------------+
                       |  COORDINATOR |
                       | Plans the    |
                       | workflow     |
                       +------+-------+
                              |
                +-------------+-------------+
                |             |             |
                v             v             v
           RESEARCHER      ANALYST      EXECUTOR
                |             |             |
                +-------------+-------------+
                              |
                              v
                   +----------------------+
                   | Python / Tools       |
                   | Deterministic work  |
                   +----------+-----------+
                              |
                              v
                   +----------------------+
                   |     VERIFIER         |
                   | Evidence + numbers   |
                   +----------+-----------+
                              |
                       +------+------+
                       |             |
                    Revision        Pass
                       |             |
                       +------<------+
                              |
                              v
                     DECISION BRIEF
                              |
                              v
                    HUMAN APPROVAL
```

The important distinction is that the LLM is used for flexible reasoning, while important calculations and validation are handled deterministically.

---

## What it can do

Automatron currently contains **4 sectors and 12 workflows**.

| Sector | Workflows |
|---|---|
| **Space** | Conjunction triage, anomaly root cause, licensing and spectrum |
| **Quant** | Alpha audit, trade approval, trading-code compliance |
| **E-commerce** | Return dispute, chargeback representment, seller appeal |
| **Real Estate** | Due-diligence red flags, permit pre-screen, dispute summary |

All bundled scenarios use synthetic data and fictional organisations and jurisdictions.

---

## Two principles

### 1. Numbers come from tools

The model is not trusted to invent quantitative results in free-form text.

If a decision brief contains a number that was not produced by a deterministic tool, verification fails and the workflow is sent back for revision.

```text
Model reasoning
      |
      v
Tool execution
      |
      v
Deterministic result
      |
      v
Verification
```

### 2. Recommendations are not decisions

Automatron can research, analyse, calculate, identify risks and prepare recommendations.

It does not:

- Place orders
- Execute trades
- File documents
- Approve permits
- Take regulatory actions
- Make the final decision

The final decision remains with a qualified human.

---

## Architecture

```mermaid
flowchart TB

    USER["User Request"] --> API["FastAPI / Uvicorn"]

    API --> GRAPH["LangGraph"]

    GRAPH --> C["Coordinator"]

    C --> R["Researcher"]
    C --> A["Analyst"]
    C --> E["Executor"]

    R --> Q["LlamaIndex + Qdrant"]
    A --> T["Python Tools"]
    E --> T

    Q --> V["Deterministic Verifier"]
    T --> V

    V --> LOOP["Capped Revision Loop"]
    LOOP --> GRAPH

    V --> B["Decision Brief"]
    B --> H["Human Approval"]

    P["Provider Router"] --> GRAPH
    P --> M["6 Providers / 11 Model Slots"]

    GRAPH --> AUDIT["Hash-Chained Audit Log"]
```

### Core components

| Component | Purpose |
|---|---|
| **LangGraph** | Agent orchestration and workflow state |
| **LlamaIndex** | Retrieval pipeline |
| **Qdrant** | Vector storage |
| **Python tools** | Deterministic calculations |
| **Provider router** | Model selection and failover |
| **Verifier** | Deterministic validation |
| **Audit log** | Hash-chained decision history |
| **FastAPI** | API layer |
| **Cloud Run** | Production deployment |

---

## Agent roles

Automatron does not give every agent unrestricted access.

### Coordinator
Plans the workflow and dispatches tasks.

### Researcher
Retrieves relevant sector knowledge and supporting evidence.

### Analyst
Performs quantitative and sector-specific analysis using deterministic tools.

### Executor
Runs permitted tools and produces structured outputs.

Each role operates under a tool allowlist enforced in code.

---

## Retrieval

The retrieval layer uses **LlamaIndex + Qdrant** with dense and sparse retrieval.

```text
                    Request
                       |
                       v
                Retrieval Layer
                  /          \
                 /            \
                v              v
          Dense Search    Sparse Search
                \              /
                 \            /
                  v          v
                     Qdrant
                       |
                       v
                Relevant Evidence
```

Knowledge is isolated by sector so workflows operate against the appropriate domain context.

---

## Reliability

The project is designed around failure cases as well as the normal execution path.

### Provider failover

The provider router can fail over when providers encounter:

- Rate limits
- Quota exhaustion
- Context overflow

### Idempotent requests

`POST /api/v1/runs` supports an `Idempotency-Key`.

A retry with the same key returns the existing run instead of starting another one.

```text
Request
   |
   +--> First request  --> Start run
   |
   +--> Retry          --> Return existing run
```

### Deterministic verification

Agent output is checked before it reaches the human approval stage.

### Offline testing

The complete workflow can run without API keys using a fake model.

The real tools still execute, allowing the system to be tested without consuming provider quota.

### Auditability

Every decision is recorded in a hash-chained audit log that can be verified.

---

## Accounts and data isolation

Anyone can create an account. Each person sees only their own runs.

```text
/login ──> Supabase Auth ──> encrypted session cookie ──> interface
                                                     │
                                       every request verifies the token
```

- **Sign up, sign in, reset a password** on `/login`. Passwords go straight to
  Supabase Auth and are never stored here. Email confirmation and reset links
  finish on the same page.
- **The browser holds one cookie**: encrypted, `HttpOnly`, `SameSite=Lax`, and
  host-locked with the `__Host-` prefix behind HTTPS. Its token is verified on
  every request and refreshed before it expires; a session ends a week after
  sign-in, and signing out revokes it everywhere.
- **No account discovery.** A wrong password and an unknown address get the same
  answer, and so does signing up with an address that is already registered.
  Attempts are limited per address and per account, auth posts must come from
  this origin, and new passwords are checked before they are sent.
- **A run belongs to whoever started it.** The owner comes from the verified
  token, never from the request, and is checked on every route. Someone else's run
  id behaves exactly like one that does not exist.
- **The database enforces it too.** Profiles, sign-in history, runs and the audit
  trail live in Supabase under forced row-level security. The service writes as
  the signed-in user with the publishable key; it never holds a service-role key.
- **Run content is encrypted before it is stored.** Each run has its own AES-256-GCM
  key, wrapped by Cloud KMS or a key from Secret Manager, and every sealed value
  is bound to its run, owner and field. The database refuses plaintext in those
  columns, so a leaked backup shows sector, workflow and status, not what was asked
  or concluded.

The schema is in `supabase/migrations/`. `tests/integration/test_supabase_rls.py`
applies it to a throwaway PostgreSQL and attacks it as each role.

To turn accounts on, apply the migrations and set:

```text
SUPABASE_URL                 https://<project>.supabase.co
SUPABASE_PUBLISHABLE_KEY     the project's publishable key (never the secret one)
RUN_ENCRYPTION_KEYS          k1:<base64 32 bytes>, or RUN_KMS_KEY for Cloud KMS
SESSION_SECRET               base64 32 bytes, the same on every instance
APP_PASSWORD                 the operator credential for /ops and /metrics
```

---

## Observability

Traces, metrics and logs, joined by trace id.

```mermaid
flowchart LR
    APP["Automatron"] -- OTLP traces --> COL["OpenTelemetry Collector"]
    COL --> TEMPO["Tempo"]
    COL -- span metrics --> PROM["Prometheus"]
    APP -- /metrics --> PROM
    PROM --> GRAF["Grafana"]
    TEMPO --> GRAF
```

- **Traces (OpenTelemetry).** Each run leg is one trace, linked to the request that
  started it: every graph node, every plan step, every model attempt with its
  provider, model, outcome, token counts and time spent waiting on the rate
  limiter, and every tool call. Pausing for the reviewer is not reported as an
  error. Request bodies, headers and run content are never recorded.
- **Metrics (Prometheus).** Runs, time to brief, provider calls by outcome and
  latency, tokens, tool latency, online evaluation results, refused requests,
  durable-store writes and HTTP latency by route template. Latency samples carry
  exemplars, so a slow bucket in Grafana opens the trace of a run in it.
- **Logs.** JSON lines with credentials and personal data redacted, each carrying
  the trace and span id it was written under.
- **Alerts.** Eleven Prometheus rules, from a brief carrying a number no tool
  produced, to no provider answering, to repeated requests for someone else's runs.
- **Dashboards.** A provisioned Grafana dashboard, and `/ops` in the app itself for
  deployments with no Grafana.

Run the stack locally:

```bash
APP_PASSWORD=... GRAFANA_ADMIN_PASSWORD=... docker compose -f observability/docker-compose.yml up -d
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 APP_PASSWORD=... python app.py
# Grafana: http://localhost:3000   Prometheus: http://localhost:9090
```

Tracing is off unless `OTEL_EXPORTER_OTLP_ENDPOINT` is set, and costs nothing when
off. Any OTLP backend works, Google Cloud Trace included.

---

## Cloud deployment

Automatron is containerized and deployed to **Google Cloud Run**.

```mermaid
flowchart LR

    A["Git Push"] --> B["GitHub Actions"]
    B --> C["CI"]
    C --> D["Build + Tests"]
    D --> E["Workload Identity Federation"]
    E --> F["Google Cloud Run"]
    F --> G["Health Check"]
    G --> H["Live Revision"]
```

The deployment uses:

- GitHub Actions
- Google Cloud Run
- Artifact Registry
- Secret Manager
- Workload Identity Federation
- Automated post-deployment smoke tests

No long-lived Google Cloud service-account key is stored in the repository.

Current Cloud Run configuration:

```text
Memory:        2 GiB
CPU:           1
Max instances: 1
Concurrency:   20
Timeout:       900 seconds
```

---

## CI/CD

CI runs on pushes and pull requests and checks:

```text
Lint
  |
Notebook build
  |
Stored-output checks
  |
Offline tests
  |
Container build
```

Deployment runs after CI succeeds:

```text
Push to main
     |
     v
    CI
     |
   Pass
     |
     v
Cloud Run deployment
     |
     v
Health check
     |
     v
Smoke test
     |
     v
Live revision
```

---

## Run locally

Clone the repository:

```bash
git clone https://github.com/Arnavdsp/Automatron.git
cd Automatron
```

Install dependencies:

```bash
pip install -r requirements-dev.txt
```

Build the application modules:

```bash
python scripts/build_notebooks.py
```

Run completely offline:

```bash
AUTOMATRON_FAKE_LLM=1 python app.py
```

Run with real providers:

```bash
python app.py
```

Run tests:

```bash
pytest -q
```

Run evaluation scenarios:

```bash
python tests/eval/run_eval.py
```

The offline mode requires no API keys.

---

## Project structure

```text
Automatron/
|
├── app.py
├── Dockerfile
├── README.md
├── DECISIONS.md
├── requirements.txt
├── requirements-dev.txt
|
├── config/
│   ├── providers.yaml
│   ├── sectors.yaml
│   └── rules/
|
├── data/
│   ├── knowledge/
│   └── samples/
|
├── observability/
│   ├── docker-compose.yml
│   ├── otel-collector.yaml
│   ├── prometheus/
│   └── grafana/
|
├── notebooks/
│   ├── automatron_core.ipynb
│   ├── automatron_ecommerce.ipynb
│   ├── automatron_quant.ipynb
│   ├── automatron_realestate.ipynb
│   └── automatron_space.ipynb
|
├── scripts/
│   └── build_notebooks.py
|
├── supabase/
│   └── migrations/
|
├── tests/
│   ├── eval/
│   ├── integration/
│   ├── live/
│   └── unit/
|
└── .github/
    └── workflows/
        ├── ci.yml
        └── deploy.yml
```

---

## Design decisions

The repository contains `DECISIONS.md`, which documents the major architectural choices and the reasoning behind them.

It covers why each part was built the way it was, not only what it does.

---

## Evaluation

The project includes:

- Unit tests
- Integration tests
- Golden evaluation scenarios
- Offline fake-model testing
- Deployment smoke tests
- Notebook build checks
- Container build checks

Run the complete offline test suite:

```bash
pytest -q
```

Run evaluation scenarios:

```bash
python tests/eval/run_eval.py
```

Every live run is also scored as it reaches the approval gate, by the same
deterministic checks the golden scenarios use: the brief validates, every number
traces to a tool, every finding cites evidence, nothing claims a decision was
taken, the call budget held, and on live providers the brief arrived within its
target time. Scores appear on the run, on `/ops` and in Grafana.

---

## Limitations

Automatron is a portfolio and engineering project.

It is not:

- Investment advice
- Legal advice
- Compliance advice
- Engineering advice
- Regulatory advice
- Operational conjunction screening

All bundled data is synthetic.

The sector rules and thresholds are illustrative and would require independent validation before being used in a real production domain.

---

## Current status

```text
Sectors                 4
Workflows              12
Model providers         6
Model slots            11
Retrieval        Dense + Sparse
Verification     Deterministic
Audit             Hash-chained
Deployment        Cloud Run
CI/CD             GitHub Actions
Human approval    Required
Accounts          Supabase Auth + RLS
Run storage       Encrypted per run
Tracing           OpenTelemetry
Metrics           Prometheus + Grafana
```

---

## Future work

Areas I want to explore next:

- Distributed execution, with graph checkpoints shared across instances
- Persistent distributed idempotency
- Cost-aware model routing
- Retrieval evaluation
- Stronger policy verification
- Organizations with shared runs, which the schema already models

---

## Author

Arnav Deshpande

B.Tech, Space Science & Engineering  
IIT Indore

GitHub:  
https://github.com/Arnavdsp

---

## The core idea

```text
LLM reasoning
      |
      v
Tool execution
      |
      v
Deterministic verification
      |
      v
Decision brief
      |
      v
Human decision
```

Automatron is an exploration of how agentic AI systems can be made more structured, verifiable and controllable when the workflow matters as much as the answer.
