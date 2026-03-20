#!/usr/bin/env python3
import json, urllib.request, time, os, sys

NODES_FILE = os.path.expanduser("~/AI/cluster_nodes.json")
LOG_FILE = os.path.expanduser("~/WishBridge/logs/router.log")
REFRESH = 2
CLEAR = "\033[2J"
HOME = "\033[H"

def color(t, c): return f"\033[{c}m{t}\033[0m"
def fetch(url):
    try:
        with urllib.request.urlopen(url, timeout=1) as r:
            return json.loads(r.read())
    except: return None

def load_nodes():
    try: return json.loads(open(NODES_FILE).read())
    except: return []

def tail_log(n=5):
    try:
        lines = open(LOG_FILE).readlines()
        return lines[-n:]
    except: return []

def draw(nodes_data, logs):
    out = [HOME]
    out.append(color("╔══ WB CLUSTER DASHBOARD ══╗\n", "1;36"))
    out.append(f"  {time.strftime('%H:%M:%S')} | Нод: {len(nodes_data)}\n\n")
    total_tps = 0
    for n in nodes_data:
        ip, h = n["ip"], n["health"]
        if h is None:
            out.append(f"  {ip:15} | " + color("● OFFLINE", "31") + "\n")
        else:
            tps = h.get("tps", 0)
            total_tps += tps
            ram = h.get("ram", "?")
            temp = h.get("temp", "?")
            load = h.get("active", 0)
            c = "32" if load == 0 else "33"
            out.append(f"  {ip:15} | " + color(f"● ONLINE", c) +
                      f" | load={load} | {ram} | {temp} | {tps}tok/s\n")
    out.append(f"\n  " + color(f"Суммарно: {total_tps} tok/s", "1;32") + "\n")
    out.append(color("\n  Последние логи:\n", "90"))
    for l in tail_log():
        out.append(color(f"  {l.strip()}", "90") + "\n")
    sys.stdout.write("".join(out))
    sys.stdout.flush()

def main():
    sys.stdout.write(CLEAR)
    while True:
        nodes = load_nodes()
        nodes_data = [{"ip": n["ip"], "health": fetch(f"http://{n['ip']}:9000/health")} for n in nodes]
        draw(nodes_data, tail_log())
        time.sleep(REFRESH)

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: print("\n👋 Выход")
