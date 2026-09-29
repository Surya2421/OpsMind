# OpsMind — Real AI Incident Response Agent System

OpsMind is an actual, locally reproducible AI incident response agent system.
It features zero mocks, real system tools, an autonomous diagnosis agent loop, independent multi-probe verification, official Hindsight experiential memory (`retain`, `recall`, `reflect`), and a full execution trace console.

---

## Architecture Overview

```
Window 1: Target Payment App (checkout.html :8000/checkout or :8082)
  │ (User clicks "PAY NOW")
  ▼
API Gateway Proxy (:8080) ──── (Routes to Upstream) ────► Payment Backend (:8081)
  │
  │ (When Upstream Corrupted -> Real HTTP 502 Bad Gateway)
  ▼
Window 2: OpsMind Operator Console (index.html :8000)
  │
  ▼
FastAPI Backend (app.py)
  │
  ▼
Agent Orchestrator (agents/orchestrator.py)
  │
  ├──► Diagnosis Agent (agents/diagnosis_agent.py)
  │      ├── Autonomous Tool Loop (inspect_service_health, get_recent_logs, inspect_deployment_config)
  │      ├── Hindsight Memory (recall & reflect from bank "opsmind-demo")
  │      └── OpenRouter LLM (openrouter/free)
  │
  ├──► Human Operator Approval Gate (API & UI boundary)
  │
  ├──► Remediation Agent (agents/remediation_agent.py)
  │      └── Strictly Whitelisted Local Actions:
  │          - rollback_gateway_config
  │          - restart_payment_backend
  │          - restart_gateway
  │
  ├──► Verification Agent (agents/verification_agent.py)
  │      └── Independent 3-Probe Socket Health & Log Verification (Never trusts LLM claims)
  │
  └──► Hindsight Memory Manager (memory/hindsight_manager.py)
         └── Retains both SUCCESS and FAILED outcomes into long-term memory
```

---

## Two Browser Interfaces

### Window 1: Target Payment Application
- **URL**: `http://127.0.0.1:8000/checkout` (or standalone on `http://127.0.0.1:8082`)
- **Purpose**: Monitored production service ("CloudScale Pro Cluster - $149/mo").
- **Real Routing**: Clicking **PAY NOW** makes a genuine HTTP POST request through the API Gateway (`http://127.0.0.1:8080/api/v1/payments/process`).
- **Healthy State**: Returns `HTTP 200 OK` (Transaction Approved, latency measured, backend verified).
- **Incident State**: Returns genuine `HTTP 502 Bad Gateway` with real connection-refused payload when gateway upstream is misconfigured.

### Window 2: OpsMind Incident Response Console
- **URL**: `http://127.0.0.1:8000`
- **Purpose**: Autonomous incident management dashboard for SREs and on-call engineers.
- **Trace & Controls**: Real-time telemetry, sandbox controls, autonomous investigation traces, Hindsight recalled memories & reflection, LLM diagnosis, human approval gate, execution proof, and learning retention.

---

## Real Local Sandbox Environment

The system includes a reproducible two-service sandbox in `sandbox/`:
1. **Payment Backend Service** (`http://127.0.0.1:8081`): Real microservice handling `/health`, payment processing, and metrics, logging to `sandbox/logs/payment_service.log`.
2. **API Gateway Service** (`http://127.0.0.1:8080`): Real reverse proxy reading upstream target dynamically from `sandbox/config/gateway.json` and logging to `sandbox/logs/gateway.log`.
3. **Incident Injection**: Deliberately points upstream port to `8099`, generating genuine HTTP 502 Bad Gateway responses and real connection failure logs.

---

## Allowed Remediation Whitelist

To ensure safety, the remediation agent is strictly restricted to allowed local sandbox actions:
- `rollback_gateway_config`: Restores `gateway.json` to known-good golden backup (`http://127.0.0.1:8081`).
- `restart_payment_backend`: Restarts the backend process (demonstrates a failed remediation attempt when root cause is gateway config).
- `restart_gateway`: Restarts the API gateway proxy process.

Arbitrary shell execution is completely disallowed.

---

## Two-Incident Experiential Learning Demo

This demonstration shows how experiential memory directly influences agent reasoning:

### Incident 1 (Testing the False Fix):
1. In Window 1 (Target App), click **PAY NOW** to verify healthy payments (HTTP 200 OK).
2. In Window 2 (OpsMind), click **1. Trigger 502 Incident**.
3. In Window 1 (Target App), click **PAY NOW** again to observe a real **HTTP 502 Bad Gateway**.
4. In Window 2 (OpsMind), click **2. Investigate Incident**. The agent gathers health, log, and config evidence using real tools.
5. In the **Human Operator Approval Gate**, deliberately choose `restart_payment_backend` (the pitfall action).
6. Click **Approve & Execute Remediation**.
7. The backend restarts, but the gateway remains broken (upstream is still `8099`).
8. **Independent verification fails** (gateway still returns 502).
9. The failure outcome is recorded and retained into Hindsight long-term memory.

### Incident 2 (Adaptive Recovery via Memory):
1. In Window 2 (OpsMind), click **Reset Sandbox**, then click **1. Trigger 502 Incident** again.
2. In Window 1 (Target App), click **PAY NOW** to confirm the incident is active.
3. In Window 2 (OpsMind), click **2. Investigate Incident**.
4. The agent recalls the prior incident from Hindsight, synthesizes that restarting the backend failed for this symptom pattern, and reasons that the config mismatch is the true root cause.
5. The agent recommends `rollback_gateway_config`.
6. Click **Approve & Execute Remediation**.
7. **Independent verification succeeds** (3 consecutive 200 OK socket probes).
8. The successful outcome is retained into Hindsight.
9. In Window 1 (Target App), click **PAY NOW** — payment succeeds immediately with HTTP 200 OK!

---

## Installation & Prerequisites

### Prerequisites
- Python 3.10+
- Valid OpenRouter API Key
- Valid Hindsight API Key

### Installation
```bash
git clone <repo-url>
cd opsmind_prototype
pip install -r requirements.txt
```

### Environment Configuration (.env)
Create `.env` based on `.env.example`:

```bash
# Hindsight Configuration
HINDSIGHT_API_URL=https://api.hindsight.vectorize.io
HINDSIGHT_API_KEY=hsk_your_key_here
HINDSIGHT_BANK_ID=opsmind-demo

# OpenRouter LLM Configuration (OpenAI-compatible)
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_API_KEY=sk-or-v1-your_key_here
LLM_MODEL=openrouter/free

# Ports
GATEWAY_PORT=8080
BACKEND_PORT=8081
UI_PORT=8000
```

---

## Running the Application

### Option A: Single Command (Recommended)
Starts the FastAPI backend, sandbox services, OpsMind Console, and Target Checkout App:
```powershell
uvicorn app:app --port 8000
```
- **OpsMind Dashboard**: `http://127.0.0.1:8000`
- **Target Payment App**: `http://127.0.0.1:8000/checkout`

### Option B: Standalone Target Application Port
To run the Target Application on a dedicated port (e.g. 8082):
```powershell
# Terminal 1: Core OpsMind Backend & Sandbox
uvicorn app:app --port 8000

# Terminal 2: Dedicated Target Checkout App
python target_app.py --port 8082
```
- **OpsMind Dashboard**: `http://127.0.0.1:8000`
- **Target Payment App**: `http://127.0.0.1:8082`

---

## Running Verification Tests

Run the complete 12-test pytest suite:
```powershell
pytest -v
```

Run the end-to-end smoke test suite (Suites A through H):
```powershell
python smoke_test.py
```

---

## Troubleshooting

- **CORS or Port Conflicts**: Ensure ports `8000`, `8080`, and `8081` are not in use by other processes. If needed, run `python -c "from sandbox.manager import stop_sandbox; stop_sandbox()"` to terminate stale processes.
- **OpenRouter Free Tier Rate Limit**: OpenRouter free models have a daily quota (50 requests/day on uncredited accounts). OpsMind will explicitly fail and report `429 Rate limit exceeded` if your daily key quota is depleted.
- **Hindsight Connectivity**: Ensure your `HINDSIGHT_API_KEY` is valid and bank `opsmind-demo` is accessible. Missing credentials fail immediately with an explicit error.
