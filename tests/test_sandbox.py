"""
Test Suite A & B: Local Sandbox and Incident Verification
Tests that backend and gateway run as real services, return real 200s,
and produce genuine HTTP 502 Bad Gateway responses with real logs when corrupted.
"""

import time
import pytest
from sandbox.manager import (
    start_sandbox,
    stop_sandbox,
    reset_sandbox,
    trigger_incident,
    get_sandbox_status,
)
from tools.system_tools import inspect_service_health, get_recent_logs
from core.config import BACKEND_URL, GATEWAY_URL


@pytest.fixture(scope="module", autouse=True)
def setup_teardown_sandbox():
    start_sandbox()
    yield
    stop_sandbox()


def test_sandbox_starts_healthy():
    """Test A: Sandbox start -> backend health 200, gateway health 200."""
    reset_sandbox()
    time.sleep(0.5)

    status = get_sandbox_status()
    assert status["backend"]["status"] == "HEALTHY", f"Backend unhealthy: {status}"
    assert status["gateway"]["status"] == "HEALTHY", f"Gateway unhealthy: {status}"

    be_probe = inspect_service_health(f"{BACKEND_URL}/health")
    assert be_probe["status_code"] == 200, f"Expected 200 from backend, got {be_probe}"
    assert be_probe["healthy"] is True

    gw_probe = inspect_service_health(f"{GATEWAY_URL}/health")
    assert gw_probe["status_code"] == 200, f"Expected 200 from gateway, got {gw_probe}"
    assert gw_probe["healthy"] is True


def test_incident_triggers_real_502_and_logs():
    """Test B: Trigger incident -> gateway health 502, logs contain real connection failure."""
    incident_result = trigger_incident()
    assert incident_result["ok"] is True
    assert incident_result["actual_http_status"] == 502

    # Verify gateway health tool returns 502
    gw_probe = inspect_service_health(f"{GATEWAY_URL}/health")
    assert gw_probe["status_code"] == 502, f"Expected 502, got {gw_probe['status_code']}"
    assert gw_probe["healthy"] is False

    # Verify real error log entries exist on disk
    logs = get_recent_logs("gateway", max_lines=20)
    assert logs["has_errors"] is True, "Expected error lines in gateway.log"
    assert any("econnrefused" in line.lower() or "502" in line.lower() for line in logs["error_lines"]), (
        f"Expected ECONNREFUSED in logs: {logs['error_lines']}"
    )

    # Clean up
    reset_sandbox()
