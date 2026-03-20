#!/usr/bin/env python3
import json, socket, http.client
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

NETWORK_PREFIX = "192.168.1."
PORT = 9000
TIMEOUT = 1.0
MAX_WORKERS = 64
SAVE_PATH = Path.home() / "AI/cluster_nodes.json"

def check_host(ip):
    try:
        conn = http.client.HTTPConnection(ip, PORT, timeout=TIMEOUT)
        conn.request("GET", "/health")
        resp = conn.getresponse()
        if resp.status == 200:
            data = json.loads(resp.read().decode())
            return {"ip": ip, "port": PORT, "status": "alive",
                    "free_ram_mb": data.get("free_ram_mb", 0)}
    except: pass
    return None

def main():
    print("🔍 Сканирую сеть 192.168.1.0/24...")
    found = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(check_host, f"{NETWORK_PREFIX}{i}"): i for i in range(1, 255)}
        for future in as_completed(futures):
            r = future.result()
            if r:
                print(f"✅ Cactus worker: {r['ip']} RAM:{r['free_ram_mb']}MB")
                found.append(r)
    SAVE_PATH.parent.mkdir(parents=True, exist_ok=True)
    SAVE_PATH.write_text(json.dumps(found, indent=2))
    print(f"\n💾 Найдено: {len(found)} нод → {SAVE_PATH}")

if __name__ == "__main__":
    main()
