"""
Remediation Agent for OpsMind
Executes operator-approved remediation actions strictly against the allowed whitelist.
Never executes arbitrary shell commands.
"""

import datetime
import logging
from typing import Any
from tools.system_tools import execute_remediation, ALLOWED_REMEDIATION_ACTIONS

logger = logging.getLogger("RemediationAgent")
logger.setLevel(logging.INFO)


class RemediationAgent:
    def __init__(self):
        self.allowed_actions = ALLOWED_REMEDIATION_ACTIONS

    def execute_action(
        self,
        action: str,
        operator_approved: bool = True,
        parameters: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """
        Validates and executes an approved remediation action on the local sandbox.
        Returns (remediation_result, execution_trace_event).
        """
        if not operator_approved:
            raise PermissionError("Remediation rejected: Operator approval is required.")

        # Server-side validation of action id
        if action not in self.allowed_actions:
            raise ValueError(
                f"Unauthorized remediation action '{action}'. "
                f"Allowed actions: {list(self.allowed_actions.keys())}"
            )

        iso_time = datetime.datetime.now(datetime.timezone.utc).isoformat()
        try:
            result = execute_remediation(action, parameters)
            trace_event = {
                "stage": "EXECUTE",
                "tool_used": f"remediation.{action}",
                "input": {"action": action, "operator_approved": True, "parameters": parameters or {}},
                "actual_output": result,
                "reasoning_summary": f"Executed approved remediation: {action} ({result.get('output', '')})",
                "timestamp": iso_time,
                "status": "SUCCESS" if result.get("success") else "FAILED",
            }
            return result, trace_event
        except Exception as e:
            logger.error(f"Remediation action '{action}' execution failed: {e}")
            trace_event = {
                "stage": "EXECUTE",
                "tool_used": f"remediation.{action}",
                "input": {"action": action, "operator_approved": True},
                "actual_output": {"error": str(e)},
                "reasoning_summary": f"Execution of {action} failed: {e}",
                "timestamp": iso_time,
                "status": "FAILED",
            }
            return {"success": False, "error": str(e)}, trace_event
