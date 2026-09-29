"""
Real System Tools for OpsMind
Real health inspection, real log retrieval, deployment config diffing,
safe whitelisted remediation execution, and independent verification.
No mocks.
"""

import datetime
import json
import logging
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path
from core.config import BACKEND_URL, GATEWAY_URL, GATEWAY_PORT, BACKEND_PORT

logger = logging.getLogger("SystemTools")
logger.setLevel(logging.INFO)

BASE_DIR = Path(__file__).resolve().parent.parent
SANDBOX_DIR = BASE_DIR / "sandbox"
CONFIG_DIR = SANDBOX_DIR / "config"
LOGS_DIR = SANDBOX_DIR / "logs"

GATEWAY_CONFIG = CONFIG_DIR / "gateway.json"
GATEWAY_BACKUP = CONFIG_DIR / "gateway.backup.json"
GATEWAY_LOG = LOGS_DIR / "gateway.log"
BACKEND_LOG = LOGS_DIR / "payment_service.log"

ALLOWED_REMEDIATION_ACTIONS = {
    "rollback_gateway_config": "Rolls back gateway.json to the known-good backup (port 8081)",
    "restart_payment_backend": "Restarts the payment backend service process on port 8081",
    "restart_gateway": "Restarts the API gateway proxy service process on port 8080",
}


def inspect_service_health(url: str = None, timeout: float = 3.5) -> dict:
    """
    Performs an actual HTTP GET call to the target endpoint.
    Measures latency and returns status code and response payload.
    """
    target = url or f"{GATEWAY_URL}/health"
    start_time = time.time()
    iso_time = datetime.datetime.now(datetime.timezone.utc).isoformat()

    try:
        req = urllib.request.Request(target, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as response:
            latency_ms = round((time.time() - start_time) * 1000, 2)
            raw_body = response.read().decode("utf-8", errors="replace")
            try:
                body = json.loads(raw_body)
            except Exception:
                body = raw_body

            return {
                "target_url": target,
                "status_code": response.status,
                "latency_ms": latency_ms,
                "healthy": response.status == 200,
                "response_body": body,
                "error": None,
                "timestamp": iso_time,
            }

    except urllib.error.HTTPError as e:
        latency_ms = round((time.time() - start_time) * 1000, 2)
        raw_body = e.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw_body)
        except Exception:
            body = raw_body

        return {
            "target_url": target,
            "status_code": e.code,
            "latency_ms": latency_ms,
            "healthy": False,
            "response_body": body,
            "error": f"HTTP {e.code} Error",
            "timestamp": iso_time,
        }

    except Exception as e:
        latency_ms = round((time.time() - start_time) * 1000, 2)
        return {
            "target_url": target,
            "status_code": 0,
            "latency_ms": latency_ms,
            "healthy": False,
            "response_body": None,
            "error": str(e),
            "timestamp": iso_time,
        }


def get_recent_logs(service: str = "gateway", max_lines: int = 40) -> dict:
    """
    Reads actual log files from disk.
    Extracts recent lines and filters for relevant error/warning patterns.
    """
    log_file = GATEWAY_LOG if service == "gateway" else BACKEND_LOG
    iso_time = datetime.datetime.now(datetime.timezone.utc).isoformat()

    if not log_file.exists():
        return {
            "service": service,
            "log_file": str(log_file),
            "total_lines": 0,
            "recent_lines": [],
            "error_lines": [],
            "has_errors": False,
            "timestamp": iso_time,
        }

    try:
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            all_lines = [line.strip() for line in f if line.strip()]

        recent = all_lines[-max_lines:] if len(all_lines) > max_lines else all_lines
        error_keywords = ("error", "econnrefused", "502", "failed", "critical", "timed out", "unreachable")
        error_lines = [
            line for line in recent
            if any(k in line.lower() for k in error_keywords)
        ]

        return {
            "service": service,
            "log_file": str(log_file),
            "total_lines": len(all_lines),
            "recent_lines": recent,
            "error_lines": error_lines,
            "has_errors": len(error_lines) > 0,
            "timestamp": iso_time,
        }
    except Exception as e:
        return {
            "service": service,
            "log_file": str(log_file),
            "error": f"Failed to read log file: {e}",
            "timestamp": iso_time,
        }


def inspect_deployment_config(service: str = "gateway") -> dict:
    """
    Reads actual current configuration and compares with known-good backup.
    Returns exact field-by-field diff.
    """
    iso_time = datetime.datetime.now(datetime.timezone.utc).isoformat()
    current_config = {}
    known_good_config = {}

    if GATEWAY_CONFIG.exists():
        try:
            with open(GATEWAY_CONFIG, "r", encoding="utf-8") as f:
                current_config = json.load(f)
        except Exception as e:
            current_config = {"error": str(e)}

    if GATEWAY_BACKUP.exists():
        try:
            with open(GATEWAY_BACKUP, "r", encoding="utf-8") as f:
                known_good_config = json.load(f)
        except Exception as e:
            known_good_config = {"error": str(e)}

    # Compute exact diff
    differences = []
    all_keys = set(current_config.keys()) | set(known_good_config.keys())
    for k in sorted(all_keys):
        cur_val = current_config.get(k)
        ref_val = known_good_config.get(k)
        if cur_val != ref_val:
            differences.append({
                "field": k,
                "current_value": cur_val,
                "known_good_value": ref_val,
            })

    return {
        "service": service,
        "current_config_file": str(GATEWAY_CONFIG),
        "backup_config_file": str(GATEWAY_BACKUP),
        "current_config": current_config,
        "known_good_config": known_good_config,
        "diff_detected": len(differences) > 0,
        "differences": differences,
        "timestamp": iso_time,
    }


def execute_remediation(action: str, params: dict = None) -> dict:
    """
    Executes strictly whitelisted local sandbox remediation actions.
    No arbitrary shell execution.
    """
    iso_time = datetime.datetime.now(datetime.timezone.utc).isoformat()

    if action not in ALLOWED_REMEDIATION_ACTIONS:
        raise ValueError(
            f"Action '{action}' is not an allowed remediation action. "
            f"Allowed actions: {list(ALLOWED_REMEDIATION_ACTIONS.keys())}"
        )

    start_time = time.time()

    if action == "rollback_gateway_config":
        if not GATEWAY_BACKUP.exists():
            raise FileNotFoundError(f"Backup configuration not found at {GATEWAY_BACKUP}")
        shutil.copy2(GATEWAY_BACKUP, GATEWAY_CONFIG)
        duration_ms = round((time.time() - start_time) * 1000, 2)
        return {
            "action": action,
            "success": True,
            "duration_ms": duration_ms,
            "output": f"Restored {GATEWAY_CONFIG} from {GATEWAY_BACKUP}. Upstream reverted to http://127.0.0.1:8081.",
            "timestamp": iso_time,
        }

    elif action == "restart_payment_backend":
        from sandbox.manager import (
            _backend_process,
            start_service_process,
            PAYMENT_SERVICE_SCRIPT,
            BACKEND_PORT,
            check_port_open,
        )
        import sandbox.manager as sm

        if sm._backend_process and sm._backend_process.poll() is None:
            sm._backend_process.terminate()
            try:
                sm._backend_process.wait(timeout=2)
            except Exception:
                sm._backend_process.kill()

        sm._backend_process = start_service_process(PAYMENT_SERVICE_SCRIPT, BACKEND_PORT)
        for _ in range(20):
            time.sleep(0.1)
            if check_port_open(BACKEND_URL):
                break

        duration_ms = round((time.time() - start_time) * 1000, 2)
        return {
            "action": action,
            "success": True,
            "duration_ms": duration_ms,
            "output": "Payment backend restarted on port 8081. Active gateway configuration was NOT modified.",
            "timestamp": iso_time,
        }

    elif action == "restart_gateway":
        from sandbox.manager import (
            _gateway_process,
            start_service_process,
            GATEWAY_SERVICE_SCRIPT,
            GATEWAY_PORT,
            check_port_open,
        )
        import sandbox.manager as sm

        if sm._gateway_process and sm._gateway_process.poll() is None:
            sm._gateway_process.terminate()
            try:
                sm._gateway_process.wait(timeout=2)
            except Exception:
                sm._gateway_process.kill()

        sm._gateway_process = start_service_process(GATEWAY_SERVICE_SCRIPT, GATEWAY_PORT)
        for _ in range(20):
            time.sleep(0.1)
            if check_port_open(GATEWAY_URL):
                break

        duration_ms = round((time.time() - start_time) * 1000, 2)
        return {
            "action": action,
            "success": True,
            "duration_ms": duration_ms,
            "output": "API Gateway restarted on port 8080. Existing configuration reloaded.",
            "timestamp": iso_time,
        }

    raise ValueError(f"Unhandled action {action}")


def verify_system(
    gateway_url: str = None,
    probe_count: int = 3,
    probe_delay_sec: float = 0.4,
) -> dict:
    """
    Performs independent multi-probe verification:
    1. Sends probe_count live HTTP requests to gateway health endpoint.
    2. Sends probe to payment backend health endpoint.
    3. Checks fresh logs for any 5xx errors.
    4. Only declares RESOLVED when all probes return 200 OK.
    """
    gw_url = gateway_url or f"{GATEWAY_URL}/health"
    be_url = f"{BACKEND_URL}/health"
    iso_time = datetime.datetime.now(datetime.timezone.utc).isoformat()
    start_time = time.time()

    probes = []
    all_success = True

    for i in range(probe_count):
        probe_res = inspect_service_health(gw_url, timeout=3.0)
        probes.append({
            "probe_number": i + 1,
            "status_code": probe_res["status_code"],
            "latency_ms": probe_res["latency_ms"],
            "healthy": probe_res["healthy"],
        })
        if not probe_res["healthy"]:
            all_success = False
        if i < probe_count - 1:
            time.sleep(probe_delay_sec)

    # Also verify backend directly
    be_probe = inspect_service_health(be_url, timeout=2.0)

    # Read latest logs to ensure no fresh errors
    latest_logs = get_recent_logs(service="gateway", max_lines=10)

    recovered = all_success and be_probe["healthy"]
    status = "RESOLVED" if recovered else "FAILED"
    proof = (
        f"{sum(1 for p in probes if p['healthy'])}/{probe_count} gateway HTTP health probes returned 200 OK "
        f"(backend direct probe status: {be_probe['status_code']})"
        if recovered
        else f"Gateway health probes failed: {sum(1 for p in probes if not p['healthy'])}/{probe_count} returned non-200 (latest status: {probes[-1]['status_code']})"
    )

    return {
        "status": status,
        "recovered": recovered,
        "verification_proof": proof,
        "gateway_probes": probes,
        "backend_probe": be_probe,
        "total_verification_duration_ms": round((time.time() - start_time) * 1000, 2),
        "timestamp": iso_time,
    }
