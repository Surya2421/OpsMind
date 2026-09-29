"""
OpsMind End-to-End Smoke Test Runner
Executes all 8 core verification suites (A through H) against the real local sandbox,
real system tools, real LLM provider, and real Hindsight memory manager.
"""

import os
import sys
import time
from core.config import (
    validate_llm_credentials,
    validate_hindsight_credentials,
    HINDSIGHT_API_KEY,
    LLM_API_KEY,
    GATEWAY_URL,
    BACKEND_URL,
)
from sandbox.manager import (
    start_sandbox,
    stop_sandbox,
    reset_sandbox,
    trigger_incident,
    get_sandbox_status,
)
from tools.system_tools import (
    inspect_service_health,
    get_recent_logs,
    inspect_deployment_config,
    execute_remediation,
    verify_system,
)
from memory.hindsight_manager import HindsightManager
from core.llm_client import LLMClient
from agents.orchestrator import AgentOrchestrator


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def run_smoke_tests():
    print("=" * 70)
    print("OPSMIND END-TO-END SYSTEM VERIFICATION")
    print("=" * 70)

    results = {}

    # ---------------------------------------------------------
    # SUITE A: Sandbox Start & Health Probes (200 OK)
    # ---------------------------------------------------------
    print("\n[A] Testing Sandbox Startup & Initial Health...")
    try:
        start_sandbox()
        reset_sandbox()
        time.sleep(0.5)
        status = get_sandbox_status()
        be_probe = inspect_service_health(f"{BACKEND_URL}/health")
        gw_probe = inspect_service_health(f"{GATEWAY_URL}/health")

        assert be_probe["status_code"] == 200, f"Backend probe returned {be_probe['status_code']}"
        assert gw_probe["status_code"] == 200, f"Gateway probe returned {gw_probe['status_code']}"
        results["A_sandbox_start"] = ("PASSED", f"Gateway :8080 (200 OK), Backend :8081 (200 OK)")
        print(f"    [OK] Passed: {results['A_sandbox_start'][1]}")
    except Exception as e:
        results["A_sandbox_start"] = ("FAILED", str(e))
        print(f"    [X] Failed: {e}")

    # ---------------------------------------------------------
    # SUITE B: Incident Trigger & Evidence Verification (502 Bad Gateway)
    # ---------------------------------------------------------
    print("\n[B] Testing Real Incident Injection & Log Evidence...")
    try:
        trig = trigger_incident()
        assert trig["actual_http_status"] == 502, f"Expected 502, got {trig['actual_http_status']}"
        gw_probe = inspect_service_health(f"{GATEWAY_URL}/health")
        assert gw_probe["status_code"] == 502, f"Expected 502 probe, got {gw_probe['status_code']}"
        logs = get_recent_logs("gateway", max_lines=15)
        assert logs["has_errors"] is True, "No errors found in gateway.log"
        results["B_incident_trigger"] = ("PASSED", f"Real 502 returned, {len(logs['error_lines'])} error logs recorded")
        print(f"    [OK] Passed: {results['B_incident_trigger'][1]}")
    except Exception as e:
        results["B_incident_trigger"] = ("FAILED", str(e))
        print(f"    [X] Failed: {e}")

    # ---------------------------------------------------------
    # SUITE C: Real Tool Execution (Health & Config Diffing)
    # ---------------------------------------------------------
    print("\n[C] Testing Real System Tools (Health & Config Diff)...")
    try:
        diff_res = inspect_deployment_config("gateway")
        assert diff_res["diff_detected"] is True, "Expected config diff to be detected"
        diff_fields = [d["field"] for d in diff_res["differences"]]
        assert "upstream_url" in diff_fields, f"Expected upstream_url in diff, got {diff_fields}"
        results["C_system_tools"] = ("PASSED", f"Detected live diff on: {diff_fields}")
        print(f"    [OK] Passed: {results['C_system_tools'][1]}")
    except Exception as e:
        results["C_system_tools"] = ("FAILED", str(e))
        print(f"    [X] Failed: {e}")

    # ---------------------------------------------------------
    # SUITE D: Hindsight Memory Integration
    # ---------------------------------------------------------
    print("\n[D] Testing Hindsight Memory Integration...")
    try:
        mgr = HindsightManager()
        if not HINDSIGHT_API_KEY:
            # Test that credentials check fails cleanly without fake fallback
            try:
                mgr.get_client()
                results["D_hindsight"] = ("FAILED", "Expected ValueError for missing credentials, but none was raised")
            except ValueError as ve:
                results["D_hindsight"] = (
                    "PASSED (CREDENTIAL_CHECK)",
                    f"Correctly rejected missing key: {ve}",
                )
                print(f"    [OK] Passed: {results['D_hindsight'][1]}")
        else:
            # Test live calls
            mgr.retain_incident_outcome(
                incident_id="smoke_test",
                service="api-gateway",
                symptom="HTTP 502",
                evidence_summary="upstream 8099",
                root_cause="deployment mismatch",
                action_attempted="rollback_gateway_config",
                action_outcome="SUCCESS",
                verification_evidence="3/3 200s",
                duration_seconds=1.5,
                lesson="Config rollback resolves 502",
            )
            mems = mgr.recall_memories("HTTP 502 upstream")
            refl = mgr.reflect_on_incident("Compare rollback vs restart outcomes for gateway errors")
            results["D_hindsight"] = (
                "PASSED",
                f"Live retain, recall ({len(mems)} memories), and reflect ({len(refl)} chars) verified",
            )
            print(f"    [OK] Passed: {results['D_hindsight'][1]}")
    except Exception as e:
        results["D_hindsight"] = ("FAILED", str(e))
        print(f"    [X] Failed: {e}")

    # ---------------------------------------------------------
    # SUITE E: LLM Provider Integration & Structured Output
    # ---------------------------------------------------------
    print("\n[E] Testing LLM Provider Integration (OpenRouter)...")
    try:
        validate_llm_credentials()
        llm = LLMClient()
        resp = llm.call_json_completion([
            {"role": "system", "content": "You are OpsMind. Output JSON with keys: diagnosis, action."},
            {"role": "user", "content": "Gateway returned 502 because upstream port is 8099 instead of 8081."},
        ])
        assert isinstance(resp, dict), "Response must be a dict"
        assert "diagnosis" in resp and "action" in resp
        results["E_llm_integration"] = ("PASSED", f"Live OpenRouter ({llm.model}) returned valid structured JSON")
        print(f"    [OK] Passed: {results['E_llm_integration'][1]}")
    except Exception as e:
        results["E_llm_integration"] = ("FAILED", str(e))
        print(f"    [X] Failed: {e}")

    # ---------------------------------------------------------
    # SUITE F: Remediation Pitfall Test (Backend Restart Fails)
    # ---------------------------------------------------------
    print("\n[F] Testing Pitfall Remediation (Backend restart during bad config)...")
    try:
        rem_res = execute_remediation("restart_payment_backend")
        assert rem_res["success"] is True
        verif = verify_system(f"{GATEWAY_URL}/health", probe_count=2)
        assert verif["recovered"] is False, "Verification should fail"
        assert verif["status"] == "FAILED"
        results["F_remediation_pitfall"] = ("PASSED", "Backend restarted, verification correctly failed (gateway still 502)")
        print(f"    [OK] Passed: {results['F_remediation_pitfall'][1]}")
    except Exception as e:
        results["F_remediation_pitfall"] = ("FAILED", str(e))
        print(f"    [X] Failed: {e}")

    # ---------------------------------------------------------
    # SUITE G: Remediation Recovery Test (Rollback Succeeds)
    # ---------------------------------------------------------
    print("\n[G] Testing Recovery Remediation (Config rollback)...")
    try:
        rem_res = execute_remediation("rollback_gateway_config")
        assert rem_res["success"] is True
        time.sleep(0.3)
        verif = verify_system(f"{GATEWAY_URL}/health", probe_count=3)
        assert verif["recovered"] is True, f"Verification failed: {verif}"
        assert verif["status"] == "RESOLVED"
        results["G_recovery_verification"] = ("PASSED", "Config rolled back, 3/3 health probes confirmed 200 OK")
        print(f"    [OK] Passed: {results['G_recovery_verification'][1]}")
    except Exception as e:
        results["G_recovery_verification"] = ("FAILED", str(e))
        print(f"    [X] Failed: {e}")

    # ---------------------------------------------------------
    # SUITE H: Full Two-Incident Learning Loop
    # ---------------------------------------------------------
    print("\n[H] Testing Full End-to-End Orchestrator Learning Loop...")
    try:
        orch = AgentOrchestrator()
        # Incident 1: inject failure and test pitfall
        reset_sandbox()
        trigger_incident()
        inv1 = orch.start_investigation()
        res1 = orch.execute_and_verify(action="restart_payment_backend", operator_approved=True)
        assert res1["status"] == "FAILED"

        # Incident 2: inject failure and verify recovery
        reset_sandbox()
        trigger_incident()
        inv2 = orch.start_investigation()
        assert inv2["recommendation"]["recommended_action"] == "rollback_gateway_config"
        res2 = orch.execute_and_verify(action="rollback_gateway_config", operator_approved=True)
        assert res2["status"] == "RESOLVED"

        results["H_two_incident_loop"] = (
            "PASSED",
            f"Incident 1 failed ({res1['status']}) -> Incident 2 recovered ({res2['status']}) with {len(orch.execution_trace)} trace events",
        )
        print(f"    [OK] Passed: {results['H_two_incident_loop'][1]}")
    except Exception as e:
        results["H_two_incident_loop"] = ("FAILED", str(e))
        print(f"    [X] Failed: {e}")

    # Cleanup
    reset_sandbox()
    stop_sandbox()

    # ---------------------------------------------------------
    # SUMMARY REPORT
    # ---------------------------------------------------------
    print("\n" + "=" * 70)
    print("OPSMIND SMOKE TEST SUMMARY REPORT")
    print("=" * 70)
    all_passed = True
    for suite, (status, detail) in results.items():
        pass_flag = "PASS" if "PASSED" in status else "FAIL"
        print(f"[{pass_flag}] Suite {suite:<25} : {status:<15} - {detail}")
        if "FAILED" in status:
            all_passed = False
    print("=" * 70)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(run_smoke_tests())
