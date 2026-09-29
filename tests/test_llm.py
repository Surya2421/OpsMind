"""
Test Suite E: Real LLM Integration and Structured Output Validation
Tests real OpenAI-compatible endpoint with OpenRouter,
validating strict JSON parsing and diagnosis generation from real evidence.
"""

import os
import pytest
from core.llm_client import LLMClient
from core.config import validate_llm_credentials
from agents.diagnosis_agent import DiagnosisAgent


def test_missing_llm_credentials_fails_clearly():
    """Ensures missing LLM API key fails with an explicit error."""
    client = LLMClient(api_key="")
    with pytest.raises(ValueError) as excinfo:
        client.call_chat_completion([{"role": "user", "content": "hi"}])
    assert "LLM API key is missing" in str(excinfo.value)


def test_live_llm_structured_json():
    """Test E.1: Real API call to OpenAI-compatible provider with structured JSON validation."""
    validate_llm_credentials()
    client = LLMClient()
    response = client.call_json_completion([
        {
            "role": "system",
            "content": "You are a test evaluator. Respond with strict JSON containing 'status' and 'model'.",
        },
        {"role": "user", "content": "Run health probe."},
    ])

    assert isinstance(response, dict), f"Expected dict, got {type(response)}"
    assert "status" in response, f"Missing 'status' in {response}"


def test_diagnosis_agent_reason_from_evidence():
    """Test E.2: DiagnosisAgent generates structured recommendation from real evidence."""
    validate_llm_credentials()
    agent = DiagnosisAgent()

    fake_incident = {
        "incident_id": "test_inc_01",
        "error": "HTTP 502 Bad Gateway",
        "symptom": "Gateway returning 502; payment backend healthy on 8081",
    }
    fake_evidence = {
        "inspect_service_health_1": {"status_code": 502, "healthy": False},
        "inspect_service_health_2": {"status_code": 200, "healthy": True, "target_url": "http://127.0.0.1:8081/health"},
        "inspect_deployment_config_3": {
            "diff_detected": True,
            "differences": [{"field": "upstream_url", "current_value": "http://127.0.0.1:8099", "known_good_value": "http://127.0.0.1:8081"}],
        },
    }

    rec, traces = agent.reason_and_recommend(
        incident_context=fake_incident,
        gathered_evidence=fake_evidence,
        recalled_memories=[],
        reflection="",
    )

    assert isinstance(rec, dict)
    assert "diagnosis" in rec
    assert "root_cause" in rec
    assert rec["recommended_action"] in ("rollback_gateway_config", "restart_payment_backend", "restart_gateway")
    assert rec["confidence"] > 0
