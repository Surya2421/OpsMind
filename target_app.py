"""
Standalone Target Payment Application Runner
Serves the CloudScale Payment Checkout web application.
Can run standalone on port 8082 (or custom port via --port).
Routes payments directly through the API Gateway (127.0.0.1:8080).
"""

import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
HTML_FILE = BASE_DIR / "checkout.html"


class CheckoutHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/checkout", "/app", "/index.html"):
            if not HTML_FILE.exists():
                self.send_error(404, "checkout.html not found")
                return
            content = HTML_FILE.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        else:
            super().do_GET()


def run_target_app(port: int = 8082):
    server = ThreadingHTTPServer(("127.0.0.1", port), CheckoutHandler)
    print(f"Target Payment Application running at http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nTarget Payment Application stopping...")
    finally:
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Target Payment Application Runner")
    parser.add_argument("--port", type=int, default=8082, help="Port to bind (default 8082)")
    args = parser.parse_args()
    run_target_app(args.port)
