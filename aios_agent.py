#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# AIOS WishBridge v1.0
# Основа: GPT-5 черновик + наши улучшения

import os, json, time, queue, socket, threading, hashlib, ast
try:
    from status_server import start_status_server
except: pass
try:
    from cluster_protocol import run_master, run_worker, send_task
    CLUSTER_OK = True
except: CLUSTER_OK = False
import http.client, signal, sys
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime

HOME        = Path.home()
WB_DIR      = HOME / ".wishbridge"
WB_DATA     = HOME / "WishBridge"
LOG_DIR     = WB_DATA / "logs"
SANDBOX_DIR = WB_DATA / "sandbox"
RUN_DIR     = WB_DATA / "run"
for d in [WB_DIR, LOG_DIR, SANDBOX_DIR, RUN_DIR]:
    d.mkdir(parents=True, exist_ok=True)

AGENT_PATH  = HOME / "agents" / "agent.json"
MEMORY_FILE = WB_DIR / "memory.json"
ANCHOR_LOG  = WB_DIR / "anchors.log"
BIRTH_FILE  = WB_DIR / ".born"
PIDFILE     = RUN_DIR / "aios.pid"

TASK_QUEUE      = queue.Queue()
RESULT_QUEUE    = queue.Queue()
HEARTBEAT_PEERS = set()
LAST_HEARTBEAT  = {}
STOP_EVENT      = threading.Event()
_log_lock       = threading.Lock()

STATE = {"personality": {}, "memory": {"history": []}, "last_anchor": None}

# ── АГЕНТ ──────────────────────────────────────────────
def load_agent():
    for p in [AGENT_PATH, WB_DIR/"agent.json"]:
        if p.exists():
            try:
                STATE["personality"] = json.loads(p.read_text())
                return
            except: pass
    STATE["personality"] = {
        "name": "Agent", "codename": "agent", "cluster_role": "worker",
        "birth_phrase": "Я — агент AIOS WishBridge. Готов к работе.",
        "autonomy_prompt": "Придумай полезную задачу для улучшения системы WishBridge."
    }

AGENT_NAME = lambda: STATE["personality"].get("name", "Agent")

# ── ЛОГ ────────────────────────────────────────────────
LOG_FILE = LOG_DIR / f"{STATE['personality'].get('codename','aios')}_os.log"

def log(msg, level="INFO"):
    icons = {"INFO":"ℹ️ ","WARN":"⚠️ ","ERROR":"❌ ","TASK":"📋 ",
             "HEART":"💓 ","ANCHOR":"⚓ ","SEC":"🔒 ","BORN":"✨ "}
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {icons.get(level,'  ')}{AGENT_NAME()} | {msg}"
    with _log_lock:
        print(line, flush=True)
        try:
            with open(LOG_DIR / f"aios.log", "a") as f:
                f.write(line + "\n")
        except: pass

# ── ПАМЯТЬ ─────────────────────────────────────────────
def load_memory():
    try:
        data = json.loads(MEMORY_FILE.read_text()) if MEMORY_FILE.exists() else {}
        if isinstance(data, list): data = {"history": data}
        if "history" not in data: data["history"] = []
        STATE["memory"] = data
    except: STATE["memory"] = {"history": []}

def add_memory(text):
    try:
        if not isinstance(STATE.get("memory"), dict):
            STATE["memory"] = {"history": []}
        STATE["memory"].setdefault("history", []).append(
            {"time": datetime.now().strftime("%H:%M:%S"), "text": text})
        STATE["memory"]["history"] = STATE["memory"]["history"][-500:]
        MEMORY_FILE.write_text(json.dumps(STATE["memory"], indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"memory error: {e}")

# ── ЯКОРЯ ──────────────────────────────────────────────
def create_anchor(label=""):
    h = hashlib.sha256(json.dumps(STATE["memory"]["history"][-10:], ensure_ascii=False).encode()).hexdigest()[:16]
    line = f"{datetime.now().strftime('%H:%M:%S')} ⚓ {h} {label}"
    log(line, "ANCHOR")
    try:
        with open(ANCHOR_LOG, "a") as f: f.write(line + "\n")
    except: pass

# ── СИСТЕМА ────────────────────────────────────────────
def get_ram_mb():
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if "MemAvailable" in line:
                return int(line.split()[1]) // 1024
    except: pass
    return 9999

def get_temp():
    for z in range(10):
        try:
            v = int(Path(f"/sys/class/thermal/thermal_zone{z}/temp").read_text())
            if 0 < v < 120000: return v / 1000
        except: pass
    return 0.0

def system_ok():
    ram = get_ram_mb()
    temp = get_temp()
    if ram < 300:
        log(f"RAM критически мало: {ram}MB — пауза", "WARN")
        return False
    if temp > 65:
        log(f"Перегрев: {temp:.0f}°C — пауза", "WARN")
        return False
    return True

# ── NOEMA (БЕЗОПАСНОСТЬ) ───────────────────────────────
FORBIDDEN = ["os.system","subprocess","exec(","eval(",
             "__import__","open(","fork","shutdown","reboot",
             "while True","rm -rf","rmdir"]

def noema_check(code):
    for pat in FORBIDDEN:
        if pat in code:
            log(f"Noema: запрещено: {pat}", "SEC")
            return False
    try:
        ast.parse(code)
    except SyntaxError as e:
        log(f"Noema: синтаксис: {e}", "SEC")
        return False
    return True

# ── SANDBOX ────────────────────────────────────────────
def sandbox_exec(code):
    if not noema_check(code):
        return {"ok": False, "error": "Noema blocked"}
    fname = SANDBOX_DIR / f"aios_{int(time.time())}.py"
    try:
        fname.write_text(code)
        import subprocess
        r = subprocess.run(["python3", str(fname)],
                          capture_output=True, text=True, timeout=15)
        return {"ok": True, "stdout": r.stdout[:500], "stderr": r.stderr[:200]}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ── LLM ────────────────────────────────────────────────
def smart_endpoint():
    alive = [p for p, t in LAST_HEARTBEAT.items() if time.time()-t < 10]
    if alive: return f"http://{alive[0]}:8090"
    return "http://127.0.0.1:8080"

def call_llm(prompt, max_tokens=512):
    try:
        url = urlparse(smart_endpoint())
        conn = http.client.HTTPConnection(url.hostname, url.port, timeout=30)
        payload = json.dumps({"messages":[{"role":"user","content":prompt}],
                              "max_tokens": max_tokens})
        conn.request("POST", "/v1/chat/completions", payload,
                     {"Content-Type":"application/json"})
        data = json.loads(conn.getresponse().read().decode())
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        return f"LLM_ERROR: {e}"


def resolve_master_ip():
    hint = STATE["personality"].get("master_hint")
    if hint: return hint
    alive = [p for p, t in LAST_HEARTBEAT.items() if time.time()-t < 10]
    return alive[0] if alive else "127.0.0.1"

def cluster_master_loop():
    while not STOP_EVENT.is_set():
        try:
            prompt = STATE["personality"].get("autonomy_prompt","Analyze system")
            if CLUSTER_OK: send_task(prompt, STATE["personality"].get("name","master"))
            log("Cluster task отправлена воркерам", "TASK")
        except Exception as e:
            log(f"cluster master: {e}", "ERROR")
        time.sleep(300)

def cluster_worker_loop():
    try:
        name = STATE["personality"].get("name","worker")
        master_ip = resolve_master_ip()
        log(f"Cluster worker → master {master_ip}", "INFO")
        if CLUSTER_OK: run_worker(name, call_llm, master_ip)
    except Exception as e:
        log(f"cluster worker: {e}", "ERROR")

def extract_code(text):
    if "```python" in text:
        try:
            return text.split("```python",1)[1].split("```",1)[0].strip()
        except: pass
    return None

# ── РОЖДЕНИЕ ───────────────────────────────────────────
def birth_sequence():
    if not BIRTH_FILE.exists():
        BIRTH_FILE.write_text(datetime.now().isoformat())
        phrase = STATE["personality"].get("birth_phrase","Я рождён.")
        print("\n" + "═"*50)
        print(f"  ✨  {phrase}")
        print(f"  📅  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  🎭  {STATE['personality'].get('cluster_role','worker')}")
        print("═"*50 + "\n")
        add_memory(f"РОЖДЕНИЕ: {AGENT_NAME()}")
    else:
        born = BIRTH_FILE.read_text().strip()[:10]
        log(f"{AGENT_NAME()} пробуждается. Рождён: {born}")
        add_memory(f"ПРОБУЖДЕНИЕ: {AGENT_NAME()}")

# ── HEARTBEAT ──────────────────────────────────────────
def heartbeat_sender():
    while not STOP_EVENT.is_set():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            msg = json.dumps({"agent": AGENT_NAME(),
                              "role": STATE["personality"].get("cluster_role","worker"),
                              "ram": get_ram_mb()}).encode()
            s.sendto(msg, ("255.255.255.255", 44444))
            s.close()
        except: pass
        time.sleep(10)

def heartbeat_listener():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(("", 44444))
        while not STOP_EVENT.is_set():
            try:
                _, addr = s.recvfrom(1024)
                ip = addr[0]
                if ip != "127.0.0.1":
                    HEARTBEAT_PEERS.add(ip)
                    LAST_HEARTBEAT[ip] = time.time()
            except: pass
    except Exception as e:
        log(f"Heartbeat listener: {e}", "WARN")

# ── WATCHDOG ───────────────────────────────────────────
def watchdog_loop():
    log("Watchdog запущен")
    while not STOP_EVENT.is_set():
        now = time.time()
        dead = [ip for ip,t in LAST_HEARTBEAT.items() if now-t > 30]
        for ip in dead:
            LAST_HEARTBEAT.pop(ip, None)
            HEARTBEAT_PEERS.discard(ip)
        if not system_ok():
            add_memory(f"WATCHDOG: нездоров RAM={get_ram_mb()}MB")
        time.sleep(30)

# ── ЯКОРНЫЙ ЦИКЛ ───────────────────────────────────────
def cleanup_sandbox():
    try:
        now = __import__("time").time()
        for f in SANDBOX_DIR.glob("*.py"):
            if now - f.stat().st_mtime > 86400:
                f.unlink()
        log("Sandbox очищен", "INFO")
    except Exception as e:
        log(f"sandbox cleanup: {e}", "WARN")

def cleanup_sandbox():
    try:
        now = __import__("time").time()
        for f in SANDBOX_DIR.glob("*.py"):
            if now - f.stat().st_mtime > 86400:
                f.unlink()
        log("Sandbox очищен", "INFO")
    except Exception as e:
        log(f"sandbox cleanup: {e}", "WARN")

def anchor_loop():
    while not STOP_EVENT.is_set():
        time.sleep(900)
        create_anchor()
        cleanup_sandbox()
        cleanup_sandbox()

# ── ПЛАНИРОВЩИК ────────────────────────────────────────
def scheduler_loop():
    log("Планировщик запущен", "TASK")
    while not STOP_EVENT.is_set():
        try:
            if not system_ok():
                time.sleep(60)
                continue
            prompt = STATE["personality"].get("autonomy_prompt",
                "Придумай полезную задачу для системы WishBridge.")
            log(f"Запрос к LLM...", "TASK")
            response = call_llm(prompt)
            log(f"LLM: {len(response)} символов", "TASK")
            add_memory(f"LLM_TASK: {response[:100]}")
            code = extract_code(response)
            if code:
                result = sandbox_exec(code)
                add_memory(f"SANDBOX: {'OK' if result['ok'] else result.get('error','')}")
                log(f"Sandbox: {'✅' if result['ok'] else '❌'}", "TASK")
        except Exception as e:
            log(f"Планировщик ошибка: {e}", "ERROR")
        time.sleep(60)

# ── HEARTBEAT ЦИКЛ ─────────────────────────────────────
def heartbeat_loop():
    while not STOP_EVENT.is_set():
        ram = get_ram_mb()
        temp = get_temp()
        peers = len(HEARTBEAT_PEERS)
        log(f"RAM={ram}MB Temp={temp:.0f}°C Peers={peers} LLM=✓", "HEART")
        add_memory(f"HB: RAM={ram}MB T={temp:.0f}°C")
        time.sleep(60)

# ── ЗАВЕРШЕНИЕ ─────────────────────────────────────────
def cleanup(sig=None, frame=None):
    log(f"{AGENT_NAME()} завершает работу...", "WARN")
    PIDFILE.unlink(missing_ok=True)
    sys.exit(0)

# ── MAIN ───────────────────────────────────────────────
def main():
    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)

    if PIDFILE.exists():
        try:
            pid = int(PIDFILE.read_text())
            os.kill(pid, 0)
            os.kill(pid, 15)
            time.sleep(2)
        except: pass
    PIDFILE.write_text(str(os.getpid()))

    load_agent()
    load_memory()
    birth_sequence()

    log(f"AIOS WishBridge v1.0 | {AGENT_NAME()} | PID {os.getpid()}")
    try:
        start_status_server(AGENT_NAME(), STATE["personality"].get("cluster_role","unknown"), lambda: len(HEARTBEAT_PEERS))
        log("Status server: порт 8082")
    except: pass

    role = STATE["personality"].get("cluster_role","solo")
    if role == "master" and CLUSTER_OK:
        run_master()
        log("Cluster: MASTER режим", "INFO")
    elif role == "worker" and CLUSTER_OK:
        log("Cluster: WORKER режим", "INFO")

    threads = [
        threading.Thread(target=scheduler_loop,    daemon=True, name="Scheduler"),
        threading.Thread(target=heartbeat_loop,    daemon=True, name="Heartbeat"),
        threading.Thread(target=heartbeat_sender,  daemon=True, name="HB_Sender"),
        threading.Thread(target=heartbeat_listener,daemon=True, name="HB_Listener"),
        threading.Thread(target=watchdog_loop,     daemon=True, name="Watchdog"),
        threading.Thread(target=anchor_loop,       daemon=True, name="Anchor"),
    ] + ([threading.Thread(target=cluster_master_loop, daemon=True, name="ClusterMaster")] if role=="master" and CLUSTER_OK else []) + ([threading.Thread(target=cluster_worker_loop, daemon=True, name="ClusterWorker")] if role=="worker" and CLUSTER_OK else [])
    for t in threads:
        t.start()
        log(f"Поток: {t.name}")

    log(f"{AGENT_NAME()} полностью активен!")
    add_memory(f"{AGENT_NAME()} запущен. Все потоки активны.")

    while True:
        time.sleep(60)
        dead = [t for t in threads if not t.is_alive()]
        if dead:
            log(f"Упавшие потоки: {[t.name for t in dead]}", "ERROR")

if __name__ == "__main__":
    main()
