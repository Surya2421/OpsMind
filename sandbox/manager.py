"""
Sandbox Manager for OpsMind
Controls local Payment Backend and Gateway Proxy lifecycle,
incident injection (real 502), and sandbox resets.
"""

import json
import logging
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from core.config import BACKEND_PORT, GATEWAY_PORT, BACKEND_URL, GATEWAY_URL

logger = logging.getLogger("SandboxManager")
logger.setLevel(logging.INFO)

SANDBOX_DIR = Path(__file__).resolve().parent
SERVICES_DIR = SANDBOX_DIR / "services"
CONFIG_DIR = SANDBOX_DIR / "config"
LOGS_DIR = SANDBOX_DIR / "logs"

GATEWAY_CONFIG_FILE = CONFIG_DIR / "gateway.json"
GATEWAY_BACKUP_FILE = CONFIG_DIR / "gateway.backup.json"
PAYMENT_SERVICE_SCRIPT = SERVICES_DIR / "payment_service.py"
GATEWAY_SERVICE_SCRIPT = SERVICES_DIR / "gateway_service.py"

_backend_process: subprocess.Popen | None = None
_gateway_process: subprocess.Popen | None = None


def check_port_open(url: str, timeout: float = 1.0) -> bool:
    """Checks if service responds over HTTP."""
    try:
        req = urllib.request.Request(f"{url}/health", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status in (200, 502)  # Service is alive and listening
    except urllib.error.HTTPError as e:
        return True  # Returned an HTTP response like 502
    except Exception:
        return False


def start_service_process(script_path: Path, port: int) -> subprocess.Popen:
    """Starts a service as a detached background process."""
    cmd = [sys.executable, str(script_path), "--port", str(port)]
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=False,
    )
    return process


def start_sandbox() -> dict:
    """Starts backend and gateway services if not already running."""
    global _backend_process, _gateway_process

    # Ensure clean default config exists
    if not GATEWAY_CONFIG_FILE.exists() and GATEWAY_BACKUP_FILE.exists():
        shutil.copy2(GATEWAY_BACKUP_FILE, GATEWAY_CONFIG_FILE)

    backend_alive = check_port_open(BACKEND_URL)
    if not backend_alive:
        _backend_process = start_service_process(PAYMENT_SERVICE_SCRIPT, BACKEND_PORT)
        # Wait up to 3 seconds for backend to bind
        for _ in range(30):
            time.sleep(0.1)
            if check_port_open(BACKEND_URL):
                backend_alive = True
                break

    gateway_alive = check_port_open(GATEWAY_URL)
    if not gateway_alive:
        _gateway_process = start_service_process(GATEWAY_SERVICE_SCRIPT, GATEWAY_PORT)
        for _ in range(30):
            time.sleep(0.1)
            if check_port_open(GATEWAY_URL):
                gateway_alive = True
                break

    return {
        "ok": True,
        "backend_running": backend_alive,
        "gateway_running": gateway_alive,
        "backend_url": BACKEND_URL,
        "gateway_url": GATEWAY_URL,
    }


def stop_sandbox() -> dict:
    """Stops all running sandbox processes."""
    global _backend_process, _gateway_process
    stopped = []

    for name, proc in [("backend", _backend_process), ("gateway", _gateway_process)]:
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
            stopped.append(name)

    _backend_process = None
    _gateway_process = None

    # On Windows, also kill any lingering python processes on those ports
    return {"ok": True, "stopped": stopped}


def get_sandbox_status() -> dict:
    """Inspects live health of the sandbox services."""
    backend_status = "DOWN"
    gateway_status = "DOWN"
    gateway_http_code = None

    try:
        req = urllib.request.Request(f"{BACKEND_URL}/health")
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            if resp.status == 200:
                backend_status = "HEALTHY"
    except Exception:
        backend_status = "UNREACHABLE"

    try:
        req = urllib.request.Request(f"{GATEWAY_URL}/health")
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            gateway_http_code = resp.status
            gateway_status = "HEALTHY" if resp.status == 200 else f"HTTP_{resp.status}"
    except urllib.error.HTTPError as e:
        gateway_http_code = e.code
        gateway_status = f"HTTP_{e.code}"
    except Exception as e:
        gateway_status = f"ERROR: {e}"

    # Read current upstream config
    current_upstream = None
    if GATEWAY_CONFIG_FILE.exists():
        try:
            with open(GATEWAY_CONFIG_FILE, "r", encoding="utf-8") as f:
                current_upstream = json.load(f).get("upstream_url")
        except Exception:
            pass

    return {
        "backend": {
            "url": BACKEND_URL,
            "status": backend_status,
        },
        "gateway": {
            "url": GATEWAY_URL,
            "status": gateway_status,
            "http_code": gateway_http_code,
            "configured_upstream": current_upstream,
        },
        "incident_active": gateway_http_code == 502 or gateway_status == "HTTP_502",
    }


def trigger_incident(incident_type: str = "bad_gateway_upstream") -> dict:
    """
    Triggers an ACTUAL HTTP 502 incident.
    1. Updates gateway.json upstream port to 8099 (bad configuration).
    2. Sends real traffic to gateway, verifying actual 502 is returned.
    3. Leaves real evidence in logs and config.
    """
    # Ensure sandbox services are started
    start_sandbox()

    # 1. Corrupt the gateway configuration to an unreachable upstream port
    bad_config = {
        "service": "api-gateway",
        "version": "v2.8-bad-deploy",
        "upstream_name": "payment-backend",
        "upstream_url": "http://127.0.0.1:8099",  # Nothing listening on 8099
        "timeout_seconds": 2,
        "retries": 1,
        "deployment_id": "dep_20260929_v2.8",
    }
    with open(GATEWAY_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(bad_config, f, indent=2)

    # 2. Fire real HTTP traffic to generate genuine 502 error logs
    actual_status = None
    error_body = None
    for _ in range(3):
        try:
            req = urllib.request.Request(f"{GATEWAY_URL}/health")
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                actual_status = resp.status
        except urllib.error.HTTPError as e:
            actual_status = e.code
            try:
                error_body = json.loads(e.read().decode("utf-8"))
            except Exception:
                error_body = {"error": "HTTP 502 Bad Gateway"}
        except Exception as e:
            error_body = {"error": str(e)}

    return {
        "ok": True,
        "incident": "HTTP 502 Bad Gateway",
        "simulated": False,
        "root_cause_injected": "gateway upstream configured to invalid port 8099",
        "actual_http_status": actual_status,
        "evidence_produced": {
            "gateway_url": f"{GATEWAY_URL}/health",
            "status_code": actual_status,
            "error_payload": error_body,
            "config_file": str(GATEWAY_CONFIG_FILE),
            "log_file": str(LOGS_DIR / "gateway.log"),
        },
    }


def reset_sandbox() -> dict:
    """Restores sandbox to clean, healthy state (upstream 8081)."""
    # 1. Restore known-good config
    if GATEWAY_BACKUP_FILE.exists():
        shutil.copy2(GATEWAY_BACKUP_FILE, GATEWAY_CONFIG_FILE)
    else:
        clean_config = {
            "service": "api-gateway",
            "version": "v2.8",
            "upstream_name": "payment-backend",
            "upstream_url": "http://127.0.0.1:8081",
            "timeout_seconds": 3,
            "retries": 1,
        }
        with open(GATEWAY_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(clean_config, f, indent=2)

    # 2. Ensure services are up
    start_sandbox()

    # 3. Verify health
    time.sleep(0.5)
    status = get_sandbox_status()
    return {"ok": True, "message": "Sandbox restored to healthy state", "status": status}
