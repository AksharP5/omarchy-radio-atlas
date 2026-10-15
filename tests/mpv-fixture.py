"""Serve playlist commands for tests that stub the remaining mpv operations."""
import json
from pathlib import Path
import socketserver
import sys


class PlaylistHandler(socketserver.StreamRequestHandler):
    def handle(self):
        for line in self.rfile:
            request = json.loads(line)
            command = request["command"]
            error = "property not found"
            if command[0] == "loadlist":
                rejected = Path(self.server.server_address).with_name("reject-playlist").exists()
                error = "loading failed" if rejected else "success"
            reply = dict(request_id=request["request_id"], error=error)
            self.wfile.write((json.dumps(reply) + "\n").encode())


with socketserver.UnixStreamServer(sys.argv[1], PlaylistHandler) as server:
    print("ready", flush=True)
    server.serve_forever()
