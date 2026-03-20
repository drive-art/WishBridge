import json, urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

NODES_FILE = str(Path.home() / "AI/cluster_nodes.json")

def load_nodes():
    try: return json.loads(Path(NODES_FILE).read_text())
    except: return []

def get_node_load(node):
    try:
        url = f"http://{node['ip']}:9000/health"
        with urllib.request.urlopen(url, timeout=2) as r:
            return json.loads(r.read()).get("active", 9999)
    except: return 9999

def pick_node():
    nodes = load_nodes()
    return min(nodes, key=lambda n: get_node_load(n), default=None)

def forward(node, body):
    req = urllib.request.Request(
        f"http://{node['ip']}:9000/v1/chat/completions",
        data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _json(self, d, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(d if isinstance(d, bytes) else json.dumps(d).encode())
    def do_GET(self):
        if self.path == "/health": self._json({"status": "router ok", "nodes": len(load_nodes())})
    def do_POST(self):
        if self.path == "/v1/chat/completions":
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            node = pick_node()
            if not node: return self._json({"error": "no workers"}, 503)
            try: self._json(forward(node, body))
            except Exception as e: self._json({"error": str(e)}, 500)

print("🚀 Master Router: порт 8090")
HTTPServer(("0.0.0.0", 8090), Handler).serve_forever()
