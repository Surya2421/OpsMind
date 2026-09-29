"""
Real Payment Backend Service
Runs on port 8081. Serves real HTTP health, payment processing, and metrics.
Writes real timestamped logs to sandbox/logs/payment_service.log.
"""

import argparse
import json
import logging
import sys
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Setup logging
LOGS_DIR = Path(__file__).resolve().parent.parent / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOGS_DIR / "payment_service.log"

logger = logging.getLogger("PaymentBackend")
logger.setLevel(logging.INFO)

file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
file_handler.setFormatter(
    logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
)
logger.addHandler(file_handler)

stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(
    logging.Formatter("[%(asctime)s] [PaymentBackend] %(message)s", datefmt="%H:%M:%S")
)
logger.addHandler(stream_handler)

START_TIME = time.time()
REQUEST_COUNT = 0
ERROR_COUNT = 0


class PaymentHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        # Prevent default stderr logging, handled via our logger
        pass

    def send_json(self, status_code: int, data: dict):
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

    def do_GET(self):
        global REQUEST_COUNT, ERROR_COUNT
        REQUEST_COUNT += 1
        client_ip = self.client_address[0]

        if self.path in ("/health", "/", "/api/v1/payments/health"):
            data = {
                "status": "UP",
                "service": "payment-backend",
                "version": "v2.8",
                "healthy": True,
                "uptime_seconds": round(time.time() - START_TIME, 1),
            }
            logger.info(f"{client_ip} - GET {self.path} 200 OK (Backend Healthy)")
            self.send_json(200, data)

        elif self.path == "/metrics":
            data = {
                "service": "payment-backend",
                "requests_total": REQUEST_COUNT,
                "errors_total": ERROR_COUNT,
                "uptime_seconds": round(time.time() - START_TIME, 1),
                "status": "nominal",
            }
            logger.info(f"{client_ip} - GET /metrics 200 OK")
            self.send_json(200, data)

        else:
            ERROR_COUNT += 1
            logger.warning(f"{client_ip} - GET {self.path} 404 Not Found")
            self.send_json(404, {"error": "Not Found", "path": self.path})

    def do_POST(self):
        global REQUEST_COUNT, ERROR_COUNT
        REQUEST_COUNT += 1
        client_ip = self.client_address[0]

        content_length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_length) if content_length > 0 else b"{}"

        try:
            payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
        except Exception:
            payload = {}

        if self.path in ("/api/v1/payments/process", "/payments/charge"):
            tx_id = f"tx_{uuid.uuid4().hex[:12]}"
            amount = payload.get("amount", 99.00)
            data = {
                "transaction_id": tx_id,
                "status": "APPROVED",
                "amount": amount,
                "currency": payload.get("currency", "USD"),
                "timestamp": time.time(),
            }
            logger.info(f"{client_ip} - POST {self.path} 200 APPROVED tx={tx_id} amount={amount}")
            self.send_json(200, data)
        else:
            ERROR_COUNT += 1
            logger.warning(f"{client_ip} - POST {self.path} 404 Not Found")
            self.send_json(404, {"error": "Not Found", "path": self.path})


def run_service(port: int = 8081):
    server = ThreadingHTTPServer(("127.0.0.1", port), PaymentHandler)
    logger.info(f"Payment Backend Service started on 127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Payment Backend Service shutting down...")
    finally:
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Payment Backend Service")
    parser.add_argument("--port", type=int, default=8081, help="Port to bind (default 8081)")
    args = parser.parse_args()
    run_service(args.port)
