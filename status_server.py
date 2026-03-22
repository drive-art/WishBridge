#!/usr/bin/env python3
import json, time, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HOME = Path.home()
AGENTS_DIR = HOME / "WishBridge/agents"
START_TIME = time.time()
STATE = {"name":"unknown","cluster_role":"unknown","peers_func":lambda:0}

def get_ram_free_mb():
    try:
        for line in open("/proc/meminfo"):
            if line.startswith("MemAvailable"):
                return int(line.split()[1]) // 1024
    except: pass
    return -1

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type","application/json")
        self.end_headers()
        self.wfile.write(body)
    def do_GET(self):
        if self.path == "/status":
            self._json({"agent":STATE["name"],"cluster_role":STATE["cluster_role"],
                       "ram_free_mb":get_ram_free_mb(),
                       "uptime_sec":int(time.time()-START_TIME),
                       "peers_count":STATE["peers_func"]()})
        elif self.path == "/agents":
            files = [f.name for f in AGENTS_DIR.glob("*.json")] if AGENTS_DIR.exists() else []
            self._json(files)
        else:
            self._json({"error":"not found"},404)

def start_status_server(name, role, peers_func, port=8082):
    STATE["name"] = name
    STATE["cluster_role"] = role
    STATE["peers_func"] = peers_func
    t = threading.Thread(target=lambda: HTTPServer(("0.0.0.0",port),Handler).serve_forever(), daemon=True)
    t.start()
    return t
