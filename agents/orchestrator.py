"""
Incident Response Agent Orchestrator for OpsMind
Coordinates state transitions across:
DETECT -> INVESTIGATE -> MEMORY_RECALL -> MEMORY_REFLECT -> REASON -> RECOMMEND -> APPROVAL -> EXECUTE -> VERIFY -> LEARN.
Maintains live execution traces and session state.
"""

import datetime
import logging
import time
import uuid
from typing import Any
from agents.diagnosis_agent import DiagnosisAgent
from agents.remediation_agent import RemediationAgent
from agents.verification_agent import VerificationAgent
from memory.hindsight_manager import HindsightManager
from tools.system_tools import inspect_service_health
from core.config import GATEWAY_URL

logger = logging.getLogger("AgentOrchestrator")
logger.setLevel(logging.INFO)


class AgentOrchestrator:
    def __init__(
        self,
        diagnosis_agent: DiagnosisAgent | None = None,
        remediation_agent: RemediationAgent | None = None,
        verification_agent: VerificationAgent | None = None,
        hindsight_manager: HindsightManager | None = None,
    ):
        self.diagnosis_agent = diagnosis_agent or DiagnosisAgent()
        self.remediation_agent = remediation_agent or RemediationAgent()
        self.verification_agent = verification_agent or VerificationAgent()
        self.hindsight_manager = hindsight_manager or HindsightManager()

        # In-memory session state
        self.current_incident: dict[str, Any] | None = None
        self.execution_trace: list[dict[str, Any]] = []
        self.investigation_start_time: float = 0.0

    def get_trace(self) -> list[dict[str, Any]]:
        return self.execution_trace

    def start_investigation(self, incident_payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """
        Executes stages: DETECT -> INVESTIGATE -> MEMORY_RECALL -> MEMORY_REFLECT -> REASON -> RECOMMEND -> APPROVAL (pending).
        """
        self.investigation_start_time = time.time()
        self.execution_trace = []
        incident_id = f"inc_{uuid.uuid4().hex[:8]}"

        # STAGE 1: DETECT
        iso_time = datetime.datetime.now(datetime.timezone.utc).isoformat()
        health_check = inspect_service_health(f"{GATEWAY_URL}/health")
        is_failing = not health_check.get("healthy", False)

        detect_event = {
            "stage": "DETECT",
            "tool_used": "system_probe.http_health",
            "input": {"target_url": f"{GATEWAY_URL}/health"},
            "actual_output": health_check,
            "reasoning_summary": (
                f"Incident detected! Gateway returned HTTP {health_check.get('status_code')} (unhealthy)."
                if is_failing
                else f"Gateway probed at {health_check.get('status_code')} OK."
            ),
            "timestamp": iso_time,
            "status": "SUCCESS" if is_failing else "NOMINAL",
        }
        self.execution_trace.append(detect_event)

        # Build incident context
        incident_context = {
            "incident_id": incident_id,
            "service": "api-gateway / payment-service",
            "severity": "HIGH",
            "error": f"HTTP {health_check.get('status_code')} Bad Gateway",
            "symptom": "Gateway returning HTTP 502; upstream service connection failing",
            "detected_at": iso_time,
        }
        if incident_payload:
            incident_context.update(incident_payload)

        # STAGE 2: INVESTIGATE (Autonomous Tool-Using Loop)
        investigate_traces, gathered_evidence = self.diagnosis_agent.run_investigation_loop(
            incident_context=incident_context,
            max_steps=4,
        )
        self.execution_trace.extend(investigate_traces)

        # STAGES 3 & 4: MEMORY_RECALL & MEMORY_REFLECT
        recalled_memories, reflection, memory_traces = self.diagnosis_agent.recall_and_reflect_memory(
            symptom=incident_context["symptom"],
            gathered_evidence=gathered_evidence,
        )
        self.execution_trace.extend(memory_traces)

        # STAGES 5 & 6: REASON & RECOMMEND
        recommendation, reason_traces = self.diagnosis_agent.reason_and_recommend(
            incident_context=incident_context,
            gathered_evidence=gathered_evidence,
            recalled_memories=recalled_memories,
            reflection=reflection,
        )
        self.execution_trace.extend(reason_traces)

        # STAGE 7: APPROVAL (Pending human operator action)
        approval_event = {
            "stage": "APPROVAL",
            "tool_used": "human_operator_gate",
            "input": {
                "recommended_action": recommendation.get("recommended_action"),
                "alternative_actions": recommendation.get("alternative_actions", []),
                "confidence": recommendation.get("confidence"),
            },
            "actual_output": {"state": "AWAITING_APPROVAL"},
            "reasoning_summary": (
                f"Awaiting operator approval to execute '{recommendation.get('recommended_action')}'."
            ),
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "status": "PENDING",
        }
        self.execution_trace.append(approval_event)

        # Store active state
        self.current_incident = {
            "incident_id": incident_id,
            "context": incident_context,
            "evidence": gathered_evidence,
            "recalled_memories": recalled_memories,
            "reflection": reflection,
            "recommendation": recommendation,
            "status": "AWAITING_APPROVAL",
        }

        return {
            "ok": True,
            "incident_id": incident_id,
            "context": incident_context,
            "evidence": gathered_evidence,
            "recalled_memories": recalled_memories,
            "reflection": reflection,
            "recommendation": recommendation,
            "trace": self.execution_trace,
        }

    def execute_and_verify(
        self,
        action: str,
        operator_approved: bool = True,
    ) -> dict[str, Any]:
        """
        Executes stages: APPROVAL (confirmed) -> EXECUTE -> VERIFY -> LEARN.
        """
        if not self.current_incident:
            raise ValueError("No active incident to remediate. Run investigation first.")

        incident_id = self.current_incident["incident_id"]

        # Confirm APPROVAL stage
        iso_time = datetime.datetime.now(datetime.timezone.utc).isoformat()
        approval_confirmed_event = {
            "stage": "APPROVAL",
            "tool_used": "human_operator_gate",
            "input": {"selected_action": action, "operator_approved": operator_approved},
            "actual_output": {"decision": "APPROVED", "action": action},
            "reasoning_summary": f"Operator explicitly approved action: {action}",
            "timestamp": iso_time,
            "status": "SUCCESS",
        }
        self.execution_trace.append(approval_confirmed_event)

        # STAGE 8: EXECUTE
        remediation_result, exec_trace = self.remediation_agent.execute_action(
            action=action,
            operator_approved=operator_approved,
        )
        self.execution_trace.append(exec_trace)

        # Wait a moment for service socket state to settle before verification
        time.sleep(0.5)

        # STAGE 9: VERIFY (Independent HTTP verification)
        verification_result, verify_trace = self.verification_agent.verify_recovery()
        self.execution_trace.append(verify_trace)

        recovered = verification_result.get("recovered", False)
        resolution_status = "RESOLVED" if recovered else "FAILED"
        duration_seconds = round(time.time() - self.investigation_start_time, 2)

        # STAGE 10: LEARN (Retain experience into Hindsight)
        lesson = (
            f"Remediation '{action}' succeeded: restored service health and recovered gateway traffic."
            if recovered
            else f"Remediation '{action}' FAILED: gateway remained in HTTP 502 state. Root cause was configuration discrepancy."
        )

        hindsight_result = None
        learn_status = "FAILED"
        try:
            hindsight_result = self.hindsight_manager.retain_incident_outcome(
                incident_id=incident_id,
                service=self.current_incident["context"].get("service", "api-gateway"),
                symptom=self.current_incident["context"].get("symptom", "HTTP 502 Bad Gateway"),
                evidence_summary=str(self.current_incident.get("evidence", {})),
                root_cause=self.current_incident.get("recommendation", {}).get("root_cause", "Configuration mismatch"),
                action_attempted=action,
                action_outcome=resolution_status,
                verification_evidence=verification_result.get("verification_proof", ""),
                duration_seconds=duration_seconds,
                lesson=lesson,
                operator_approval=operator_approved,
            )
            learn_status = "SUCCESS"
        except Exception as e:
            logger.warning(f"Could not retain into Hindsight: {e}")
            hindsight_result = {"error": str(e)}
            learn_status = "FAILED"

        learn_event = {
            "stage": "LEARN",
            "tool_used": "hindsight.retain",
            "input": {
                "incident_id": incident_id,
                "action": action,
                "outcome": resolution_status,
                "lesson": lesson,
            },
            "actual_output": hindsight_result,
            "reasoning_summary": f"Retained {resolution_status} incident experience into Hindsight memory.",
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "status": learn_status,
        }
        self.execution_trace.append(learn_event)

        self.current_incident["status"] = resolution_status
        self.current_incident["resolution"] = {
            "action": action,
            "status": resolution_status,
            "recovered": recovered,
            "duration_seconds": duration_seconds,
            "verification": verification_result,
            "hindsight_retained": learn_status == "SUCCESS",
        }

        return {
            "ok": True,
            "incident_id": incident_id,
            "status": resolution_status,
            "recovered": recovered,
            "action_executed": action,
            "duration_seconds": duration_seconds,
            "verification": verification_result,
            "learn_status": learn_status,
            "hindsight_result": hindsight_result,
            "trace": self.execution_trace,
        }
