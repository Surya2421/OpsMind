"""
Browser-Level End-to-End Simulation Test
Simulates the exact HTTP requests and browser actions across both interfaces:
Window 1 (Target Checkout App) & Window 2 (OpsMind Console)
"""

import time
import requests
import pytest
from sandbox.manager import start_sandbox, stop_sandbox, reset_sandbox, trigger_incident
from core.config import GATEWAY_URL, BACKEND_URL


@pytest.fixture(scope="module", autouse=True)
def manage_sandbox():
    start_sandbox()
    yield
    stop_sandbox()


def test_browser_flow_healthy_to_incident_to_recovery():
    # 1. Reset sandbox to clean state
    reset_sandbox()
    time.sleep(0.5)

    # 2. Window 1: User visits Target App -> Probes /health
    gw_health = requests.get(f"{GATEWAY_URL}/health", timeout=3)
    assert gw_health.status_code == 200, f"Expected 200, got {gw_health.status_code}"
    health_json = gw_health.json()
    assert health_json.get("healthy") is True

    # 3. Window 1: User clicks "PAY NOW" -> POST /api/v1/payments/process
    pay_payload = {
        "amount": 2400.00,
        "currency": "USD",
        "plan": "Payflow Enterprise Plan",
        "cardholder": "Sarah Jenkins",
    }
    pay_resp = requests.post(
        f"{GATEWAY_URL}/api/v1/payments/process",
        json=pay_payload,
        timeout=3,
    )
    assert pay_resp.status_code == 200
    pay_data = pay_resp.json()
    assert pay_data.get("status") == "APPROVED"
    assert "transaction_id" in pay_data
    assert pay_data.get("amount") == 2400.00
    # Verify CORS headers
    assert pay_resp.headers.get("access-control-allow-origin") == "*"

    # 4. Window 2: SRE triggers 502 incident
    inc_res = trigger_incident()
    assert inc_res["actual_http_status"] == 502

    # 5. Window 1: Target App probes /health and detects degradation
    gw_degraded = requests.get(f"{GATEWAY_URL}/health", timeout=3)
    assert gw_degraded.status_code == 502
    assert gw_degraded.headers.get("access-control-allow-origin") == "*"

    # 6. Window 1: Customer clicks "PAY NOW" during incident -> Real 502
    pay_fail = requests.post(
        f"{GATEWAY_URL}/api/v1/payments/process",
        json=pay_payload,
        timeout=3,
    )
    assert pay_fail.status_code == 502
    err_json = pay_fail.json()
    assert err_json.get("error") == "Bad Gateway"
    assert "8099" in err_json.get("upstream_target", "")
    assert pay_fail.headers.get("access-control-allow-origin") == "*"

    # 7. Window 2: Remediation executed (rollback_gateway_config)
    from tools.system_tools import execute_remediation, verify_system
    rem_res = execute_remediation("rollback_gateway_config")
    assert rem_res["success"] is True

    # 8. Independent verification verifies recovery
    ver_res = verify_system()
    assert ver_res["recovered"] is True
    assert ver_res["status"] == "RESOLVED"

    # 9. Window 1: Customer returns and clicks "PAY NOW" -> SUCCESS!
    pay_recovered = requests.post(
        f"{GATEWAY_URL}/api/v1/payments/process",
        json=pay_payload,
        timeout=3,
    )
    assert pay_recovered.status_code == 200
    rec_data = pay_recovered.json()
    assert rec_data.get("status") == "APPROVED"
    assert "transaction_id" in rec_data

    # Clean reset
    reset_sandbox()
