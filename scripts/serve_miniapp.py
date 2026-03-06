from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MINIAPP_DIR = PROJECT_ROOT / "miniapp"


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the JO AI mini app locally.")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind. Default: 127.0.0.1")
    parser.add_argument("--port", type=int, default=5500, help="Port to bind. Default: 5500")
    args = parser.parse_args()

    if not MINIAPP_DIR.exists():
        raise SystemExit(f"Mini app directory not found: {MINIAPP_DIR}")

    handler = partial(SimpleHTTPRequestHandler, directory=str(MINIAPP_DIR))
    server = ThreadingHTTPServer((args.host, args.port), handler)

    print(f"Serving JO AI mini app from: {MINIAPP_DIR}")
    print(f"Open: http://{args.host}:{args.port}")
    print("Stop with Ctrl+C")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nMini app server stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
