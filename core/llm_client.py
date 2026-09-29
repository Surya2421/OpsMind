"""
OpenRouter LLM Client for OpsMind
Connects exclusively to OpenRouter's OpenAI-compatible endpoint.
Enforces strict JSON parsing, handles reasoning model tags, and validates outputs.
No mocks. Fails clearly if credentials are missing or API fails.
"""

import json
import logging
import re
import time
import requests
from typing import Any
from core.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, validate_llm_credentials

logger = logging.getLogger("LLMClient")
logger.setLevel(logging.INFO)


class LLMClient:
    def __init__(
        self,
        base_url: str = LLM_BASE_URL,
        api_key: str = LLM_API_KEY,
        model: str = LLM_MODEL,
        timeout: float = 45.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def call_chat_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.1,
        enforce_json: bool = True,
    ) -> str:
        """Sends chat completion request to OpenRouter."""
        if not self.api_key:
            raise ValueError(
                "LLM API key is missing. Please set LLM_API_KEY in your .env file."
            )

        endpoint = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8000",
            "X-Title": "OpsMind AI Incident Response Agent",
        }

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 2048,
        }
        if enforce_json:
            payload["response_format"] = {"type": "json_object"}

        max_retries = 4
        last_error = None

        for attempt in range(max_retries):
            try:
                resp = requests.post(endpoint, headers=headers, json=payload, timeout=self.timeout)
                if resp.status_code == 200:
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                    return content.strip()

                error_detail = resp.text
                # Handle transient 429, 502, 503, or 504 from OpenRouter or upstream model providers
                if resp.status_code in (429, 500, 502, 503, 504) and attempt < max_retries - 1:
                    sleep_time = 3.0 * (attempt + 1)
                    if resp.status_code == 429:
                        sleep_time = 6.0 * (attempt + 1)
                    logger.warning(
                        f"OpenRouter returned status {resp.status_code} (attempt {attempt + 1}/{max_retries}). "
                        f"Retrying in {sleep_time}s... Response: {error_detail[:150]}"
                    )
                    time.sleep(sleep_time)
                    continue

                logger.error(f"OpenRouter API returned error status {resp.status_code}: {error_detail}")
                raise RuntimeError(
                    f"OpenRouter API error (status {resp.status_code}): {error_detail}"
                )

            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                last_error = e
                if attempt < max_retries - 1:
                    sleep_time = 2.5 * (attempt + 1)
                    logger.warning(
                        f"Transient connection error to OpenRouter (attempt {attempt + 1}/{max_retries}). "
                        f"Retrying in {sleep_time}s... Error: {e}"
                    )
                    time.sleep(sleep_time)
                    continue
                logger.error(f"Failed to communicate with OpenRouter at {endpoint}: {e}")
                raise RuntimeError(f"Failed to connect to OpenRouter: {e}") from e
            except requests.exceptions.RequestException as e:
                logger.error(f"Request exception to OpenRouter at {endpoint}: {e}")
                raise RuntimeError(f"Failed to connect to OpenRouter: {e}") from e

        raise RuntimeError(f"OpenRouter failed after {max_retries} attempts: {last_error}")

    def call_json_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.1,
        max_attempts: int = 4,
    ) -> dict[str, Any]:
        """Calls OpenRouter and parses the response strictly as a JSON dictionary, retrying on transient router mismatches."""
        last_err = None

        for attempt in range(max_attempts):
            try:
                content = self.call_chat_completion(messages, temperature=temperature, enforce_json=True)

                clean_text = content

                # Strip any <think>...</think> reasoning blocks emitted by thinking/reasoning models
                clean_text = re.sub(r"<think>[\s\S]*?</think>", "", clean_text, flags=re.DOTALL)

                # Strip markdown fences if present
                clean_text = clean_text.strip()
                if "```" in clean_text:
                    match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", clean_text)
                    if match:
                        clean_text = match.group(1)
                    else:
                        clean_text = re.sub(r"^```(?:json)?\s*", "", clean_text)
                        clean_text = re.sub(r"\s*```$", "", clean_text)

                clean_text = clean_text.strip()

                # Handle safety-classifier models occasionally selected by openrouter/free
                if clean_text.lower().startswith("user safety:") or not clean_text:
                    logger.warning(
                        f"OpenRouter routed to non-instruction model ('{clean_text[:40]}'). "
                        f"Retrying (attempt {attempt + 1}/{max_attempts})..."
                    )
                    time.sleep(1.0)
                    continue

                # If there is extra leading/trailing text, extract outermost JSON object { ... }
                if not (clean_text.startswith("{") and clean_text.endswith("}")):
                    brace_match = re.search(r"(\{[\s\S]*\})", clean_text)
                    if brace_match:
                        clean_text = brace_match.group(1)

                try:
                    parsed = json.loads(clean_text)
                    if not isinstance(parsed, dict):
                        raise ValueError(f"Expected JSON object, got {type(parsed).__name__}")
                    return parsed
                except (json.JSONDecodeError, ValueError) as parse_err:
                    # Attempt repairs on common LLM JSON syntax issues
                    repaired = re.sub(r",\s*([\]}])", r"\1", clean_text)
                    open_curly = repaired.count("{") - repaired.count("}")
                    open_square = repaired.count("[") - repaired.count("]")
                    if open_curly > 0 or open_square > 0:
                        repaired = repaired + ("]" * max(0, open_square)) + ("}" * max(0, open_curly))
                    try:
                        parsed = json.loads(repaired)
                        if isinstance(parsed, dict):
                            logger.info("Successfully recovered JSON from LLM response via structural repair.")
                            return parsed
                    except Exception:
                        pass
                    last_err = parse_err
                    logger.warning(f"JSON parsing attempt {attempt + 1}/{max_attempts} failed: {parse_err}. Retrying...")
                    time.sleep(1.0)
                    continue

            except Exception as e:
                last_err = e
                logger.warning(f"Request attempt {attempt + 1}/{max_attempts} failed: {e}. Retrying...")
                time.sleep(1.0)
                continue

        raise ValueError(f"OpenRouter failed to return valid JSON after {max_attempts} attempts: {last_err}")
