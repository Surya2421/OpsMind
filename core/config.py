import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env if present
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
SANDBOX_DIR = BASE_DIR / "sandbox"
CONFIG_DIR = SANDBOX_DIR / "config"
LOGS_DIR = SANDBOX_DIR / "logs"

# Ensure runtime directories exist
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Hindsight Configuration
HINDSIGHT_API_URL = os.getenv("HINDSIGHT_API_URL", "https://api.hindsight.vectorize.io").rstrip("/")
HINDSIGHT_API_KEY = os.getenv("HINDSIGHT_API_KEY", "").strip()
HINDSIGHT_BANK_ID = os.getenv("HINDSIGHT_BANK_ID", "opsmind-demo").strip()

# OpenRouter LLM Configuration (OpenAI-compatible)
LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
LLM_MODEL = os.getenv("LLM_MODEL", "openrouter/free").strip()

# Network Ports
GATEWAY_PORT = int(os.getenv("GATEWAY_PORT", "8080"))
BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8081"))
UI_PORT = int(os.getenv("UI_PORT", "8000"))

# Service URLs
GATEWAY_URL = f"http://127.0.0.1:{GATEWAY_PORT}"
BACKEND_URL = f"http://127.0.0.1:{BACKEND_PORT}"


def validate_llm_credentials() -> None:
    """Raises ValueError if LLM credentials are not configured."""
    if not LLM_API_KEY:
        raise ValueError(
            "LLM API key is missing. Please set LLM_API_KEY in your .env file."
        )


def validate_hindsight_credentials() -> None:
    """Raises ValueError if Hindsight credentials are not configured."""
    if not HINDSIGHT_API_KEY:
        raise ValueError(
            "Hindsight API credentials are missing. Please set HINDSIGHT_API_KEY in your .env file."
        )


def get_status_summary() -> dict:
    """Returns safe status dictionary for health and UI checks."""
    return {
        "hindsight": {
            "configured": bool(HINDSIGHT_API_KEY),
            "api_url": HINDSIGHT_API_URL,
            "bank_id": HINDSIGHT_BANK_ID,
        },
        "llm": {
            "configured": bool(LLM_API_KEY),
            "provider_url": LLM_BASE_URL,
            "model": LLM_MODEL,
        },
        "sandbox": {
            "gateway_port": GATEWAY_PORT,
            "backend_port": BACKEND_PORT,
            "gateway_url": GATEWAY_URL,
            "backend_url": BACKEND_URL,
        },
    }
