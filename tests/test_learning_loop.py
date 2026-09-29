"""
Test Suite H: Two-Incident Experiential Learning Demonstration
Verifies the complete end-to-end incident cycle:
1. Incident 1: Real 502 -> restart_payment_backend -> Verification fails -> Retain failure.
2. Incident 2: Real 502 -> Recall & Reflect past failure -> Agent chooses rollback -> Verification succeeds -> Retain success.
"""

import time
import pytest
from sandbox.manager import start_sandbox, stop_sandbox, reset_sandbox, trigger_incident
from agents.orchestrator import AgentOrchestrator
from core.config import validate_llm_credentials


@pytest.fixture(scope="module", autouse=True)
def setup_teardown():
    start_sandbox()
    yield
    stop_sandbox()


def test_two_incident_learning_cycle():
    validate_llm_credentials()
    orch = AgentOrchestrator()

    # ========================================================
    # INCIDENT 1: Operator selects pitfall action (restart backend)
    # ========================================================
    reset_sandbox()
    time.sleep(0.5)

    # 1. Trigger real 502
    trig_res = trigger_incident()
    assert trig_res["actual_http_status"] == 502

    # 2. Agent investigates
    inv1 = orch.start_investigation()
    assert inv1["ok"] is True
    assert orch.current_incident["status"] == "AWAITING_APPROVAL"

    # 3. Operator deliberately tests the pitfall action
    res1 = orch.execute_and_verify(action="restart_payment_backend", operator_approved=True)

    # 4. Verification MUST fail because gateway config is still pointing to port 8099!
    assert res1["recovered"] is False, "restart_payment_backend should not recover 502 caused by bad upstream config"
    assert res1["status"] == "FAILED"

    # ========================================================
    # INCIDENT 2: Operator investigates again and verifies recovery
    # ========================================================
    # Reset sandbox and inject fresh 502
    reset_sandbox()
    time.sleep(0.5)
    trigger_incident()

    # 5. Agent investigates the second incident
    inv2 = orch.start_investigation()
    assert inv2["ok"] is True

    # 6. LLM reasons over the situation: rollback_gateway_config is recommended
    assert inv2["recommendation"]["recommended_action"] == "rollback_gateway_config"

    # 7. Operator approves rollback
    res2 = orch.execute_and_verify(action="rollback_gateway_config", operator_approved=True)

    # 8. Verification MUST pass!
    assert res2["recovered"] is True, f"Rollback should recover gateway, but got {res2}"
    assert res2["status"] == "RESOLVED"
    assert res2["verification"]["status"] == "RESOLVED"

    # Reset sandbox at the end
    reset_sandbox()
