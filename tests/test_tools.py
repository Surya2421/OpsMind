"""
Test Suite C, F, G: Real System Tools, Remediation, and Verification
Tests health tool, deployment config diffing, pitfall backend restart (verification fails),
and config rollback recovery (verification passes).
"""

import time
import pytest
from sandbox.manager import start_sandbox, stop_sandbox, reset_sandbox, trigger_incident
from tools.system_tools import (
    inspect_service_health,
    inspect_deployment_config,
    execute_remediation,
    verify_system,
    ALLOWED_REMEDIATION_ACTIONS,
)
from core.config import GATEWAY_URL


@pytest.fixture(scope="module", autouse=True)
def setup_teardown():
    start_sandbox()
    yield
    stop_sandbox()


def test_tool_health_and_config_diff():
    """Test C: health tool returns actual status; config tool finds actual diff."""
    # 1. Start clean
    reset_sandbox()
    cfg_clean = inspect_deployment_config("gateway")
    assert cfg_clean["diff_detected"] is False

    # 2. Trigger incident (sets upstream to 8099)
    trigger_incident()
    cfg_corrupted = inspect_deployment_config("gateway")
    assert cfg_corrupted["diff_detected"] is True
    assert any(d["field"] == "upstream_url" for d in cfg_corrupted["differences"])


def test_remediation_backend_restart_fails_verification():
    """Test F: restart backend during bad gateway config -> verification fails."""
    # Gateway is corrupted pointing to 8099
    trigger_incident()

    # Operator mistakenly restarts backend
    rem_res = execute_remediation("restart_payment_backend")
    assert rem_res["success"] is True

    # Independent verification must detect the gateway is STILL broken!
    verif = verify_system(f"{GATEWAY_URL}/health", probe_count=2)
    assert verif["recovered"] is False, "Verification should fail because gateway upstream is still 8099"
    assert verif["status"] == "FAILED"


def test_remediation_rollback_passes_verification():
    """Test G: rollback gateway config -> verification passes."""
    # Active 502 incident
    trigger_incident()

    # Operator approves rollback_gateway_config
    rem_res = execute_remediation("rollback_gateway_config")
    assert rem_res["success"] is True

    # Verification must confirm repeated 200 responses
    time.sleep(0.3)
    verif = verify_system(f"{GATEWAY_URL}/health", probe_count=3)
    assert verif["recovered"] is True, f"Verification failed: {verif}"
    assert verif["status"] == "RESOLVED"
    assert all(p["healthy"] for p in verif["gateway_probes"])


def test_unsupported_action_is_rejected():
    """Ensures arbitrary shell or unwhitelisted actions are strictly rejected."""
    with pytest.raises(ValueError):
        execute_remediation("rm -rf /")

    with pytest.raises(ValueError):
        execute_remediation("drop_database")
