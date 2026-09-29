"""
Test Suite D: Hindsight Integration and Credential Enforcement
Tests that missing Hindsight credentials produce clear, explicit exceptions,
and verifies real Hindsight operations when configured.
"""

import os
import pytest
from memory.hindsight_manager import HindsightManager
from core.config import validate_hindsight_credentials


def test_missing_credentials_raises_clear_error():
    """Test D.1: clear error when HINDSIGHT_API_KEY is missing."""
    mgr = HindsightManager(api_key="")
    with pytest.raises(ValueError) as excinfo:
        mgr.get_client()
    assert "Hindsight API credentials are missing" in str(excinfo.value)


def test_hindsight_real_calls_if_key_present():
    """Test D.2: retain, recall, reflect with real client if key configured."""
    key = os.getenv("HINDSIGHT_API_KEY", "").strip()
    if not key:
        pytest.skip("HINDSIGHT_API_KEY not configured in environment. Skipping live API call.")

    mgr = HindsightManager(api_key=key)
    res = mgr.retain_incident_outcome(
        incident_id="test_live_01",
        service="api-gateway",
        symptom="HTTP 502 Bad Gateway",
        evidence_summary="Config diff on upstream port 8099",
        root_cause="Bad deployment v2.8",
        action_attempted="rollback_gateway_config",
        action_outcome="SUCCESS",
        verification_evidence="3/3 probes returned 200",
        duration_seconds=3.2,
        lesson="Gateway config rollback restores upstream connectivity.",
    )
    assert res["ok"] is True

    memories = mgr.recall_memories("HTTP 502 gateway upstream")
    assert isinstance(memories, list)

    reflection = mgr.reflect_on_incident("Compare rollback vs restart outcomes for gateway errors")
    assert isinstance(reflection, str)
    assert len(reflection) > 0
