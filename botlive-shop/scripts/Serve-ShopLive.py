from __future__ import annotations

import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

class SpaHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory: str, **kwargs):
        super().__init__(*args, directory=directory, **kwargs)

    def send_head(self):
        path = Path(self.translate_path(self.path.split("?", 1)[0]))
        if not path.exists():
            self.path = "/index.html"
        return super().send_head()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", required=True)
    parser.add_argument("--port", type=int, default=3017)
    args = parser.parse_args()
    root = Path(args.directory).resolve(strict=True)
    handler = lambda *a, **kw: SpaHandler(*a, directory=str(root), **kw)
    ThreadingHTTPServer(("127.0.0.1", args.port), handler).serve_forever()
