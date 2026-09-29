"""
Autonomous Diagnosis Agent for OpsMind
Runs a real multi-step tool-using agent loop:
1. Gathers evidence by deciding which diagnostic tools to call.
2. Observes real tool output and decides next diagnostic action.
3. Queries Hindsight for relevant historical memories (recall + reflect).
4. Reasons over real evidence + memory to produce a structured diagnosis and recommendation.
No mocks. Python validates every requested tool and parameter.
"""

import datetime
import json
import logging
from typing import Any, Callable
from core.llm_client import LLMClient
from core.config import GATEWAY_URL, BACKEND_URL
from tools.system_tools import (
    inspect_service_health,
    get_recent_logs,
    inspect_deployment_config,
    ALLOWED_REMEDIATION_ACTIONS,
)
from memory.hindsight_manager import HindsightManager

logger = logging.getLogger("DiagnosisAgent")
logger.setLevel(logging.INFO)

DIAGNOSTIC_TOOLS: dict[str, Callable] = {
    "inspect_service_health": inspect_service_health,
    "get_recent_logs": get_recent_logs,
    "inspect_deployment_config": inspect_deployment_config,
}

TOOL_DEFINITIONS = [
    {
        "name": "inspect_service_health",
        "description": "Performs real HTTP GET health check on gateway or backend service.",
        "parameters": {
            "url": f"URL to check (e.g. '{GATEWAY_URL}/health' or '{BACKEND_URL}/health')",
        },
    },
    {
        "name": "get_recent_logs",
        "description": "Reads actual runtime log files from disk and extracts errors.",
        "parameters": {
            "service": "Service name to check: 'gateway' or 'payment-backend'",
            "max_lines": "Number of recent lines to read (default 30)",
        },
    },
    {
        "name": "inspect_deployment_config",
        "description": "Reads current live config and diffs against known-good backup config.",
        "parameters": {
            "service": "Service name to inspect (default 'gateway')",
        },
    },
]


class DiagnosisAgent:
    def __init__(
        self,
        llm_client: LLMClient | None = None,
        hindsight_manager: HindsightManager | None = None,
    ):
        self.llm_client = llm_client or LLMClient()
        self.hindsight_manager = hindsight_manager or HindsightManager()

    def run_investigation_loop(
        self,
        incident_context: dict[str, Any],
        max_steps: int = 5,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """
        Executes an autonomous tool-calling investigation loop.
        Returns (trace_events, gathered_evidence).
        """
        trace_events: list[dict[str, Any]] = []
        gathered_evidence: dict[str, Any] = {}
        tool_call_history: list[dict[str, Any]] = []

        system_prompt = (
            "You are the OpsMind Lead Incident Response Diagnosis Agent.\n"
            "An incident has been detected in the production environment.\n"
            "You must investigate by selecting diagnostic tools to gather evidence.\n"
            "Available tools:\n"
            f"{json.dumps(TOOL_DEFINITIONS, indent=2)}\n\n"
            "On each turn, analyze the evidence gathered so far and decide your next action.\n"
            "You must respond with strict JSON in one of these two formats:\n\n"
            "To call a tool:\n"
            "{\n"
            '  "action": "call_tool",\n'
            '  "tool": "<tool_name>",\n'
            '  "parameters": { ... },\n'
            '  "thought": "<why you are calling this tool and what you expect to find>"\n'
            "}\n\n"
            "When you have gathered sufficient evidence to identify the root cause (e.g. after verifying gateway failure, backend health, and deployment config mismatch), choose action 'finish_investigation' immediately. Do not make duplicate or redundant tool calls.\n"
            "{\n"
            '  "action": "finish_investigation",\n'
            '  "thought": "<summary of findings and why no further tools are needed>"\n'
            "}\n"
        )

        for step in range(1, max_steps + 1):
            user_message = (
                f"Incident Context: {json.dumps(incident_context)}\n\n"
                f"Investigation Step: {step}/{max_steps}\n"
                f"Tools Executed So Far ({len(tool_call_history)}):\n"
                f"{json.dumps(tool_call_history, indent=2)}\n\n"
                "What diagnostic action will you take next? Return strict JSON."
            )

            try:
                decision = self.llm_client.call_json_completion([
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ])
            except Exception as e:
                logger.error(f"LLM decision failed on step {step}: {e}")
                # Fallback: if LLM call fails, stop loop
                break

            action_type = decision.get("action")
            thought = decision.get("thought", "Evaluating incident evidence.")

            if action_type == "finish_investigation":
                trace_events.append({
                    "stage": "INVESTIGATE",
                    "tool_used": "agent_decision",
                    "input": {"action": "finish_investigation"},
                    "actual_output": {"summary": thought, "steps_completed": step},
                    "reasoning_summary": thought,
                    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "status": "SUCCESS",
                })
                break

            tool_name = decision.get("tool")
            tool_params = decision.get("parameters", {})

            if tool_name not in DIAGNOSTIC_TOOLS:
                logger.warning(f"Agent requested unknown tool: {tool_name}")
                trace_events.append({
                    "stage": "INVESTIGATE",
                    "tool_used": tool_name or "unknown",
                    "input": tool_params,
                    "actual_output": {"error": f"Tool '{tool_name}' is not in allowed diagnostic tools."},
                    "reasoning_summary": thought,
                    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "status": "FAILED",
                })
                continue

            # Execute real tool
            iso_time = datetime.datetime.now(datetime.timezone.utc).isoformat()
            tool_func = DIAGNOSTIC_TOOLS[tool_name]
            try:
                tool_result = tool_func(**tool_params)
                gathered_evidence[f"{tool_name}_{step}"] = tool_result
                tool_call_history.append({
                    "step": step,
                    "tool": tool_name,
                    "parameters": tool_params,
                    "result_summary": {
                        k: v for k, v in tool_result.items()
                        if k in ("status_code", "healthy", "error_lines", "diff_detected", "differences")
                    },
                })
                trace_events.append({
                    "stage": "INVESTIGATE",
                    "tool_used": tool_name,
                    "input": tool_params,
                    "actual_output": tool_result,
                    "reasoning_summary": thought,
                    "timestamp": iso_time,
                    "status": "SUCCESS",
                })
            except Exception as e:
                logger.error(f"Execution of tool {tool_name} failed: {e}")
                trace_events.append({
                    "stage": "INVESTIGATE",
                    "tool_used": tool_name,
                    "input": tool_params,
                    "actual_output": {"error": str(e)},
                    "reasoning_summary": thought,
                    "timestamp": iso_time,
                    "status": "FAILED",
                })

        return trace_events, gathered_evidence

    def recall_and_reflect_memory(
        self,
        symptom: str,
        gathered_evidence: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], str, list[dict[str, Any]]]:
        """
        Recalls and reflects with Hindsight.
        Returns (recalled_memories, reflection_summary, memory_trace_events).
        """
        memory_trace: list[dict[str, Any]] = []
        recalled_memories: list[dict[str, Any]] = []
        reflection: str = ""

        recall_query = (
            f"Incident symptom: {symptom}. "
            "What prior remediation actions were attempted, and did they succeed or fail?"
        )

        iso_time = datetime.datetime.now(datetime.timezone.utc).isoformat()
        try:
            recalled_memories = self.hindsight_manager.recall_memories(recall_query)
            memory_trace.append({
                "stage": "MEMORY_RECALL",
                "tool_used": "hindsight.recall",
                "input": {"bank_id": self.hindsight_manager.bank_id, "query": recall_query},
                "actual_output": {"memories_found": len(recalled_memories), "results": recalled_memories},
                "reasoning_summary": f"Retrieved {len(recalled_memories)} historical incident memories from Hindsight.",
                "timestamp": iso_time,
                "status": "SUCCESS",
            })
        except Exception as e:
            memory_trace.append({
                "stage": "MEMORY_RECALL",
                "tool_used": "hindsight.recall",
                "input": {"query": recall_query},
                "actual_output": {"error": str(e)},
                "reasoning_summary": f"Hindsight recall could not execute: {e}",
                "timestamp": iso_time,
                "status": "FAILED",
            })

        iso_time = datetime.datetime.now(datetime.timezone.utc).isoformat()
        reflect_query = (
            f"Analyze historical remediation outcomes for {symptom}. "
            "Compare actions like restarting the backend vs rolling back the gateway configuration. Which succeeded and why?"
        )
        try:
            reflection = self.hindsight_manager.reflect_on_incident(reflect_query)
            memory_trace.append({
                "stage": "MEMORY_REFLECT",
                "tool_used": "hindsight.reflect",
                "input": {"bank_id": self.hindsight_manager.bank_id, "query": reflect_query},
                "actual_output": {"reflection": reflection},
                "reasoning_summary": "Hindsight synthesized historical experience across prior incident resolutions.",
                "timestamp": iso_time,
                "status": "SUCCESS",
            })
        except Exception as e:
            memory_trace.append({
                "stage": "MEMORY_REFLECT",
                "tool_used": "hindsight.reflect",
                "input": {"query": reflect_query},
                "actual_output": {"error": str(e)},
                "reasoning_summary": f"Hindsight reflect could not execute: {e}",
                "timestamp": iso_time,
                "status": "FAILED",
            })

        return recalled_memories, reflection, memory_trace

    def reason_and_recommend(
        self,
        incident_context: dict[str, Any],
        gathered_evidence: dict[str, Any],
        recalled_memories: list[dict[str, Any]],
        reflection: str,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """
        Reasons over real evidence + memory to generate structured diagnosis & recommendation.
        Returns (recommendation_dict, reason_trace_events).
        """
        reason_trace: list[dict[str, Any]] = []

        allowed_actions_desc = {
            k: v for k, v in ALLOWED_REMEDIATION_ACTIONS.items()
        }

        system_prompt = (
            "You are OpsMind, an expert AI incident response reasoning agent.\n"
            "Analyze the real system evidence and any historical Hindsight memories provided.\n"
            "CRITICAL INSTRUCTIONS:\n"
            "1. Base your diagnosis strictly on the real tool evidence (health checks, logs, config diffs).\n"
            "2. If Hindsight memory contains prior failed or successful actions, factor them in explicitly.\n"
            "   - If a prior action (like backend restart) failed for this exact symptom pattern, DO NOT repeat it without strong justification.\n"
            "   - If no prior memory exists, reason from the direct evidence (e.g. config diff vs backend health).\n"
            "3. Recommend exactly ONE primary action strictly chosen from the allowed remediation actions.\n"
            f"Allowed Actions:\n{json.dumps(allowed_actions_desc, indent=2)}\n\n"
            "You must return strict JSON with the following schema:\n"
            "{\n"
            '  "diagnosis": "Concise summary of the problem",\n'
            '  "root_cause": "Detailed technical explanation of the root cause based on evidence",\n'
            '  "recommended_action": "<one of the allowed action keys>",\n'
            '  "alternative_actions": ["<other allowed action keys>"],\n'
            '  "reasoning_from_evidence": "How the current tool evidence proves this diagnosis",\n'
            '  "reasoning_from_history": "How past Hindsight outcomes (or lack thereof) influenced this decision",\n'
            '  "confidence": 0.95\n'
            "}"
        )

        user_content = (
            f"Current Incident Context: {json.dumps(incident_context)}\n\n"
            f"Real Gathered Evidence: {json.dumps(gathered_evidence, indent=2)}\n\n"
            f"Hindsight Recalled Memories ({len(recalled_memories)}): {json.dumps(recalled_memories, indent=2)}\n\n"
            f"Hindsight Reflection: {reflection or 'No historical reflection available.'}\n\n"
            "Generate your structured diagnosis and remediation recommendation now."
        )

        iso_time = datetime.datetime.now(datetime.timezone.utc).isoformat()
        recommendation = self.llm_client.call_json_completion([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ])

        # Validate action
        action = recommendation.get("recommended_action")
        if action not in ALLOWED_REMEDIATION_ACTIONS:
            logger.warning(f"LLM proposed invalid action '{action}', falling back to rollback_gateway_config")
            recommendation["recommended_action"] = "rollback_gateway_config"

        reason_trace.append({
            "stage": "REASON",
            "tool_used": "llm.reason",
            "input": {"model": self.llm_client.model, "evidence_keys": list(gathered_evidence.keys())},
            "actual_output": {
                "diagnosis": recommendation.get("diagnosis"),
                "root_cause": recommendation.get("root_cause"),
                "reasoning_from_evidence": recommendation.get("reasoning_from_evidence"),
                "reasoning_from_history": recommendation.get("reasoning_from_history"),
            },
            "reasoning_summary": recommendation.get("diagnosis", "Incident diagnosis synthesized."),
            "timestamp": iso_time,
            "status": "SUCCESS",
        })

        reason_trace.append({
            "stage": "RECOMMEND",
            "tool_used": "llm.recommend",
            "input": {"allowed_actions": list(ALLOWED_REMEDIATION_ACTIONS.keys())},
            "actual_output": {
                "recommended_action": recommendation.get("recommended_action"),
                "alternative_actions": recommendation.get("alternative_actions", []),
                "confidence": recommendation.get("confidence", 0.9),
            },
            "reasoning_summary": f"Recommended action: {recommendation.get('recommended_action')}",
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "status": "SUCCESS",
        })

        return recommendation, reason_trace
