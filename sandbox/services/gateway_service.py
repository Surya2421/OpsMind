"""
Real API Gateway / Reverse Proxy Service
Runs on port 8080.
Reads upstream destination dynamically from sandbox/config/gateway.json.
Proxies actual requests to the upstream backend.
Returns actual HTTP 502 Bad Gateway when upstream is unreachable or misconfigured.
Writes real timestamped logs to sandbox/logs/gateway.log.
"""

import argparse
import json
import logging
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Setup logging
BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / "config" / "gateway.json"
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOGS_DIR / "gateway.log"

logger = logging.getLogger("APIGateway")
logger.setLevel(logging.INFO)

file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
file_handler.setFormatter(
    logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
)
logger.addHandler(file_handler)

stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(
    logging.Formatter("[%(asctime)s] [APIGateway] %(message)s", datefmt="%H:%M:%S")
)
logger.addHandler(stream_handler)


def load_gateway_config() -> dict:
    """Reads live gateway configuration from disk."""
    default_config = {
        "service": "api-gateway",
        "version": "v2.8",
        "upstream_name": "payment-backend",
        "upstream_url": "http://127.0.0.1:8081",
        "timeout_seconds": 3,
        "retries": 1,
    }
    if not CONFIG_FILE.exists():
        return default_config
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to read config {CONFIG_FILE}: {e}")
        return default_config


class GatewayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        pass

    def send_json_response(self, status_code: int, data: dict):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Connection", "close")
        self.end_headers()

    def proxy_request(self, method: str):
        config = load_gateway_config()
        upstream_base = config.get("upstream_url", "http://127.0.0.1:8081").rstrip("/")
        timeout = float(config.get("timeout_seconds", 3))
        upstream_target = f"{upstream_base}{self.path}"
        client_ip = self.client_address[0]
        start_time = time.time()

        # Read request body if POST/PUT
        content_length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_length) if content_length > 0 else None

        req = urllib.request.Request(
            upstream_target,
            data=body_bytes,
            headers={k: v for k, v in self.headers.items() if k.lower() not in ("host", "content-length")},
            method=method,
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                status_code = response.getcode()
                response_data = response.read()
                latency_ms = round((time.time() - start_time) * 1000, 2)

                logger.info(
                    f'{client_ip} - "{method} {self.path} HTTP/1.1" {status_code} '
                    f"-> upstream: {upstream_target} ({latency_ms}ms)"
                )

                self.send_response(status_code)
                for header, value in response.getheaders():
                    if header.lower() not in ("transfer-encoding", "content-length", "access-control-allow-origin"):
                        self.send_header(header, value)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(response_data)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(response_data)

        except urllib.error.HTTPError as e:
            # Upstream returned 4xx or 5xx
            status_code = e.code
            err_data = e.read()
            latency_ms = round((time.time() - start_time) * 1000, 2)
            logger.warning(
                f'{client_ip} - "{method} {self.path} HTTP/1.1" {status_code} '
                f"from upstream {upstream_target} ({latency_ms}ms)"
            )
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(err_data)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(err_data)

        except Exception as e:
            # Upstream connection failed -> Return REAL 502 Bad Gateway
            latency_ms = round((time.time() - start_time) * 1000, 2)
            error_msg = str(e)
            logger.error(
                f'upstream connection failed: connect ECONNREFUSED while connecting to upstream "{upstream_target}", '
                f'client: {client_ip}, request: "{method} {self.path} HTTP/1.1", error: {error_msg}'
            )

            error_payload = {
                "error": "Bad Gateway",
                "status": 502,
                "message": "Gateway failed to connect to upstream service",
                "upstream_target": upstream_target,
                "upstream_config": upstream_base,
                "detail": f"Connection refused or unreachable: {error_msg}",
                "timestamp": time.time(),
            }
            self.send_json_response(502, error_payload)

    def do_GET(self):
        # Even /health probes upstream backend to ensure end-to-end service availability
        self.proxy_request("GET")

    def do_POST(self):
        self.proxy_request("POST")


def run_gateway(port: int = 8080):
    server = ThreadingHTTPServer(("127.0.0.1", port), GatewayHandler)
    logger.info(f"API Gateway Service started on 127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("API Gateway Service shutting down...")
    finally:
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="API Gateway Service")
    parser.add_argument("--port", type=int, default=8080, help="Port to bind (default 8080)")
    args = parser.parse_args()
    run_gateway(args.port)
