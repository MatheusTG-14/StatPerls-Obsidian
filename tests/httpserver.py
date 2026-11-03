"""Tiny threaded HTTP file server with Range support, for installer tests."""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def serve(directory, ignore_range=False):
    """-> (base_url ending in '/', log list of (method, path, range header), stop function)."""
    root = Path(directory)
    log = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, body_needed):
            p = root / self.path.lstrip("/")
            log.append((self.command, self.path, self.headers.get("Range")))
            if not p.is_file():
                self.send_response(404)
                self.end_headers()
                return
            data = p.read_bytes()
            rng = self.headers.get("Range")
            start = 0
            if rng and not ignore_range and rng.startswith("bytes="):
                start = int(rng[6:].split("-")[0])
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
            else:
                self.send_response(200)
            self.send_header("Content-Length", str(len(data) - start))
            self.end_headers()
            if body_needed:
                self.wfile.write(data[start:])

        def do_GET(self):
            self._send(True)

        def do_HEAD(self):
            self._send(False)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()

    def stop():
        srv.shutdown()
        srv.server_close()
    return f"http://127.0.0.1:{srv.server_address[1]}/", log, stop
