"""
Independent Verification Agent for OpsMind
Verifies system health using repeated live HTTP probes and log analysis.
Never trusts AI claims of recovery; only declares RESOLVED after socket-level proof.
"""

import datetime
import logging
from typing import Any
from tools.system_tools import verify_system
from core.config import GATEWAY_URL

logger = logging.getLogger("VerificationAgent")
logger.setLevel(logging.INFO)


class VerificationAgent:
    def __init__(self, probe_count: int = 3, probe_delay_sec: float = 0.4):
        self.probe_count = probe_count
        self.probe_delay_sec = probe_delay_sec

    def verify_recovery(
        self,
        gateway_url: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """
        Runs independent verification of the recovered system.
        Returns (verification_result, trace_event).
        """
        target_url = gateway_url or f"{GATEWAY_URL}/health"
        iso_time = datetime.datetime.now(datetime.timezone.utc).isoformat()

        raw_verification = verify_system(
            gateway_url=target_url,
            probe_count=self.probe_count,
            probe_delay_sec=self.probe_delay_sec,
        )

        recovered = raw_verification.get("recovered", False)
        status = "RESOLVED" if recovered else "FAILED"
        trace_status = "SUCCESS" if recovered else "FAILED"

        trace_event = {
            "stage": "VERIFY",
            "tool_used": "verification.verify_system",
            "input": {
                "target_url": target_url,
                "probe_count": self.probe_count,
                "probe_delay_sec": self.probe_delay_sec,
            },
            "actual_output": raw_verification,
            "reasoning_summary": (
                f"Independent verification {status}: {raw_verification.get('verification_proof')}"
            ),
            "timestamp": iso_time,
            "status": trace_status,
        }

        return raw_verification, trace_event
