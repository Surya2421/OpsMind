"""
OpsMind FastAPI Application
Real AI Incident Response Agent Backend.
Zero mocks. Real local sandbox. Real system tools. Real Hindsight memory. Real LLM reasoning.
"""

import logging
from typing import Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from core.config import (
    get_status_summary,
    validate_llm_credentials,
    validate_hindsight_credentials,
)
from sandbox.manager import (
    start_sandbox,
    stop_sandbox,
    reset_sandbox,
    trigger_incident,
    get_sandbox_status,
)
from tools.system_tools import inspect_service_health
from agents.orchestrator import AgentOrchestrator
from memory.hindsight_manager import HindsightManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("OpsMindApp")

app = FastAPI(
    title="OpsMind — Real AI Incident Response Agent",
    version="1.0.0",
    description="Autonomous incident response agent system with local sandbox, real tools, and Hindsight memory.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Shared orchestrator instance
orchestrator = AgentOrchestrator()
hindsight_mgr = HindsightManager()


class InvestigateRequest(BaseModel):
    service: str = "api-gateway"
    severity: str = "HIGH"
    error: str = "HTTP 502 Bad Gateway"
    symptom: str = "Gateway returning HTTP 502; upstream service connection failing"


class RemediateRequest(BaseModel):
    action: str
    operator_approved: bool = True


class MemoryCheckRequest(BaseModel):
    query: str


@app.get("/")
def get_root():
    return FileResponse("index.html")


@app.get("/checkout")
@app.get("/app")
def get_checkout():
    return FileResponse("checkout.html")


@app.get("/api/status")
def get_status():
    """Returns real operational status of LLM, Hindsight, and Sandbox."""
    summary = get_status_summary()
    sandbox_status = get_sandbox_status()
    return {
        "ok": True,
        "config": summary,
        "sandbox": sandbox_status,
        "active_incident": orchestrator.current_incident,
    }


@app.get("/api/service-health")
def get_service_health():
    """Live probe of Gateway and Backend services."""
    status = get_sandbox_status()
    gw_probe = inspect_service_health()
    return {
        "ok": True,
        "sandbox_status": status,
        "gateway_probe": gw_probe,
    }


@app.post("/api/sandbox/start")
def api_start_sandbox():
    """Starts backend and gateway services."""
    try:
        res = start_sandbox()
        return res
    except Exception as e:
        logger.error(f"Failed to start sandbox: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/sandbox/stop")
def api_stop_sandbox():
    """Stops sandbox services."""
    try:
        res = stop_sandbox()
        return res
    except Exception as e:
        logger.error(f"Failed to stop sandbox: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/sandbox/reset")
def api_reset_sandbox():
    """Restores sandbox to clean, working state (upstream 8081)."""
    try:
        res = reset_sandbox()
        return res
    except Exception as e:
        logger.error(f"Failed to reset sandbox: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/sandbox/trigger-incident")
def api_trigger_incident():
    """
    Triggers an ACTUAL HTTP 502 incident by pointing gateway config to port 8099.
    Fires real traffic and produces real error evidence.
    """
    try:
        res = trigger_incident()
        return res
    except Exception as e:
        logger.error(f"Failed to trigger incident: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/investigate")
def api_investigate(req: InvestigateRequest):
    """
    Runs autonomous investigation loop:
    DETECT -> INVESTIGATE -> MEMORY_RECALL -> MEMORY_REFLECT -> REASON -> RECOMMEND -> APPROVAL.
    """
    try:
        result = orchestrator.start_investigation(req.model_dump())
        return result
    except Exception as e:
        logger.error(f"Investigation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/remediate")
def api_remediate(req: RemediateRequest):
    """
    Executes operator-approved remediation:
    APPROVAL -> EXECUTE -> VERIFY -> LEARN.
    """
    try:
        result = orchestrator.execute_and_verify(
            action=req.action,
            operator_approved=req.operator_approved,
        )
        return result
    except Exception as e:
        logger.error(f"Remediation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/trace")
def api_get_trace():
    """Returns the current real step-by-step execution trace."""
    return {
        "ok": True,
        "trace": orchestrator.get_trace(),
    }


@app.post("/api/memory/check")
def api_memory_check(req: MemoryCheckRequest):
    """Queries Hindsight memory directly to verify stored experiences."""
    try:
        memories = hindsight_mgr.recall_memories(req.query)
        reflection = hindsight_mgr.reflect_on_incident(req.query)
        return {
            "ok": True,
            "query": req.query,
            "memories": memories,
            "reflection": reflection,
        }
    except Exception as e:
        logger.error(f"Memory check failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.on_event("startup")
def on_startup():
    logger.info("OpsMind Backend starting up. Initializing sandbox...")
    try:
        start_sandbox()
    except Exception as e:
        logger.warning(f"Could not automatically start sandbox on startup: {e}")


@app.on_event("shutdown")
def on_shutdown():
    logger.info("OpsMind Backend shutting down. Stopping sandbox...")
    try:
        stop_sandbox()
    except Exception as e:
        logger.warning(f"Error stopping sandbox on shutdown: {e}")
