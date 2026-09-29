"""
Real Hindsight Memory Manager for OpsMind
Integrates with the official hindsight-client Python SDK.
Uses retain, recall, and reflect.
Stores both SUCCESS and FAILED remediation outcomes from real incidents.
No fake memories. No pre-seeding of fictional historical incidents.
Fails clearly if credentials are missing or API fails.
"""

import datetime
import logging
from typing import Any
from core.config import (
    HINDSIGHT_API_KEY,
    HINDSIGHT_API_URL,
    HINDSIGHT_BANK_ID,
    validate_hindsight_credentials,
)

logger = logging.getLogger("HindsightManager")
logger.setLevel(logging.INFO)

try:
    from hindsight_client import Hindsight
except ImportError:
    Hindsight = None


class HindsightManager:
    def __init__(
        self,
        base_url: str = HINDSIGHT_API_URL,
        api_key: str = HINDSIGHT_API_KEY,
        bank_id: str = HINDSIGHT_BANK_ID,
    ):
        self.base_url = base_url
        self.api_key = api_key
        self.bank_id = bank_id
        self._client: Any = None

    def get_client(self) -> Any:
        """Returns the official Hindsight client or raises a clear error."""
        if Hindsight is None:
            raise RuntimeError(
                "The 'hindsight-client' package is not installed. Run: pip install hindsight-client"
            )
        if not self.api_key:
            raise ValueError(
                "Hindsight API credentials are missing. Please set HINDSIGHT_API_KEY in your .env file."
            )
        if self._client is None:
            self._client = Hindsight(base_url=self.base_url, api_key=self.api_key)
        return self._client

    def retain_incident_outcome(
        self,
        incident_id: str,
        service: str,
        symptom: str,
        evidence_summary: str,
        root_cause: str,
        action_attempted: str,
        action_outcome: str,  # "SUCCESS" or "FAILED"
        verification_evidence: str,
        duration_seconds: float,
        lesson: str,
        operator_approval: bool = True,
    ) -> dict:
        """
        Retains a real incident outcome (SUCCESS or FAILED) into Hindsight long-term memory.
        """
        client = self.get_client()
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

        content = (
            f"Incident ID: {incident_id}\n"
            f"Timestamp: {timestamp}\n"
            f"Service: {service}\n"
            f"Symptom: {symptom}\n"
            f"Evidence: {evidence_summary}\n"
            f"Root Cause: {root_cause}\n"
            f"Action Attempted: {action_attempted}\n"
            f"Outcome: {action_outcome.upper()}\n"
            f"Verification Proof: {verification_evidence}\n"
            f"Operator Approved: {operator_approval}\n"
            f"Duration: {duration_seconds:.2f} seconds\n"
            f"Lesson Learned: {lesson}"
        )

        context_label = f"opsmind-incident-{action_outcome.lower()}"
        try:
            res = client.retain(
                bank_id=self.bank_id,
                content=content,
                context=context_label,
            )
            return {
                "ok": True,
                "incident_id": incident_id,
                "outcome": action_outcome,
                "retained_content": content,
                "response": str(res),
            }
        except Exception as e:
            logger.error(f"Hindsight retain failed: {e}")
            raise RuntimeError(f"Failed to retain incident in Hindsight: {e}") from e

    def recall_memories(self, query: str, limit: int = 5) -> list[dict]:
        """
        Recalls historical incident experiences matching the query using Hindsight.
        """
        client = self.get_client()
        try:
            result = client.recall(bank_id=self.bank_id, query=query)
            memories = []
            for r in getattr(result, "results", [])[:limit]:
                memories.append({
                    "id": getattr(r, "id", None),
                    "text": getattr(r, "text", str(r)),
                    "type": getattr(r, "type", "experience"),
                    "context": getattr(r, "context", None),
                })
            return memories
        except Exception as e:
            logger.error(f"Hindsight recall failed: {e}")
            raise RuntimeError(f"Failed to recall from Hindsight: {e}") from e

    def reflect_on_incident(self, query: str) -> str:
        """
        Synthesizes historical lessons and patterns across stored incident experiences using Hindsight.
        """
        client = self.get_client()
        try:
            result = client.reflect(bank_id=self.bank_id, query=query)
            text = getattr(result, "text", "")
            return text if text else str(result)
        except Exception as e:
            logger.error(f"Hindsight reflect failed: {e}")
            raise RuntimeError(f"Failed to reflect with Hindsight: {e}") from e
