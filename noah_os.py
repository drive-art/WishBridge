#!/usr/bin/env python3
# NoahOS v1.0 — Honor 90 | WishBridge Project

import json, os, sys, ast, time, signal, socket
import hashlib, threading, subprocess
from pathlib import Path
from datetime import datetime

try:
    import requests
    REQUESTS_OK = True
except ImportError:
    REQUESTS_OK = False

HOME        = Path.home()
WB_DIR      = HOME / ".wishbridge"
WB_DATA     = HOME / "WishBridge"
LOG_DIR     = WB_DATA / "logs"
SANDBOX_DIR = WB_DATA / "sandbox"
RUN_DIR     = WB_DATA / "run"
CFG_FILE    = WB_DIR / "config.json"
MEMORY_FILE = WB_DIR / "memory.json"
PLAN_FILE   = WB_DIR / "plan.json"
ANCHOR_LOG  = WB_DIR / "anchors.log"
PIDFILE     = RUN_DIR / "noah.pid"
BIRTH_FILE  = WB_DIR / ".born"
LOG_FILE    = LOG_DIR / "noah_os.log"

for d in [WB_DIR, LOG_DIR, SANDBOX_DIR, RUN_DIR]:
    d.mkdir(parents=True, exist_ok=True)

DEFAULT_CFG = {
    "active_model": "", "llm_port": 8080,
    "llm_threads": 4, "llm_ctx": 2048,
    "ram_low_mb": 200, "thermal_limit": 68,
    "battery_min": 20, "device_name": "noah_honor90",
    "device_role": "master", "agent_name": "Noah",
}


def smart_endpoint():
    """Автоматически выбирает кластер или локальный Cactus"""
    import urllib.request as ur
    try:
        with ur.urlopen("http://127.0.0.1:8090/health", timeout=1) as r:
            if json.loads(r.read()).get("status") == "router ok":
                return "http://127.0.0.1:8090/v1/chat/completions"
    except: pass
    return "http://127.0.0.1:8080/v1/chat/completions"

def load_cfg():
    try:
        if CFG_FILE.exists():
            cfg = json.loads(CFG_FILE.read_text())
            for k, v in DEFAULT_CFG.items():
                cfg.setdefault(k, v)
            return cfg
    except:
        pass
    return DEFAULT_CFG.copy()

CFG           = load_cfg()
LLM_PORT      = CFG["llm_port"]
DEVICE_NAME   = CFG["device_name"]
AGENT_NAME    = CFG["agent_name"]
LLM_URL       = f"http://127.0.0.1:{LLM_PORT}/v1/chat/completions"
_log_lock     = threading.Lock()

ICONS = {
    "INFO":"ℹ️ ","WARN":"⚠️ ","ERROR":"❌ ","LLM":"🧠 ",
    "ANCHOR":"⚓ ","TASK":"📋 ","HEART":"💓 ","BORN":"✨ ",
    "SYS":"🖥️ ","SEC":"🔒 ","PLAN":"📌 ",
}

def log(msg, level="INFO"):
    ts   = datetime.now().strftime("%H:%M:%S")
    icon = ICONS.get(level, "   ")
    line = f"[{ts}] {icon} {msg}"
    with _log_lock:
        print(line)
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            lines = LOG_FILE.read_text().splitlines()
            if len(lines) > 2000:
                LOG_FILE.write_text("\n".join(lines[-2000:]) + "\n")
        except:
            pass

def get_ram_mb():
    # Используем MemAvailable — реальная доступная память
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    except:
        pass
    try:
        r = subprocess.run(["free","-m"], capture_output=True, text=True)
        for line in r.stdout.splitlines():
            if line.startswith("Mem:"):
                return int(line.split()[6])  # available колонка
    except:
        pass
    return 999

def get_temp():
    for zone in range(15):
        try:
            t = int(Path(f"/sys/class/thermal/thermal_zone{zone}/temp").read_text())
            t = t / 1000
            if 0 < t < 120:
                return t
        except:
            continue
    return 0.0

def get_battery():
    try:
        for p in Path("/sys/class/power_supply").iterdir():
            cap = p / "capacity"
            sta = p / "status"
            if cap.exists():
                pct = int(cap.read_text().strip())
                charging = sta.exists() and sta.read_text().strip() in ("Charging","Full")
                return pct, charging
    except:
        pass
    return 100, True

def system_ok():
    cfg  = load_cfg()
    ram  = get_ram_mb()
    temp = get_temp()
    bat, charging = get_battery()
    if ram < cfg.get("ram_low_mb", 200):
        log(f"RAM {ram}MB — пауза", "WARN"); return False
    if temp > cfg.get("thermal_limit", 68):
        log(f"Temp {temp:.0f}°C — пауза", "WARN"); return False
    if bat < cfg.get("battery_min", 20) and not charging:
        log(f"Батарея {bat}% — пауза", "WARN"); return False
    return True

def llm_alive():
    s = socket.socket()
    s.settimeout(2)
    try:
        s.connect(("127.0.0.1", LLM_PORT)); return True
    except:
        return False
    finally:
        s.close()

def ask_llm(messages, max_tokens=2000):
    if not llm_alive():
        return "# LLM_OFFLINE"

    try:
        r = requests.post(LLM_URL,
            json={"messages": messages, "max_tokens": max_tokens, "temperature": 0.2},
            timeout=300)
        r.raise_for_status()

        msg = r.json()["choices"][0]["message"]

        content = msg.get("content", "").strip()
        reasoning = msg.get("reasoning_content", "").strip()

        if content:
            return content

        if "```" in reasoning:
            parts = reasoning.split("```")
            if len(parts) >= 3:
                return parts[1].strip()

        return reasoning[-800:] if reasoning else "# EMPTY"

    except Exception as e:
        return f"# ERROR: {e}"

def load_memory():
    try:
        return json.loads(MEMORY_FILE.read_text()) if MEMORY_FILE.exists() else []
    except:
        return []

def save_memory(mem):
    MEMORY_FILE.write_text(json.dumps(mem[-500:], indent=2, ensure_ascii=False))

def add_memory(text, mem):
    mem.append({"time": datetime.now().isoformat(), "text": text})
    save_memory(mem)

def create_anchor(mem):
    snap = json.dumps(mem[-10:], sort_keys=True)
    h    = hashlib.sha256(snap.encode()).hexdigest()[:16]
    with open(ANCHOR_LOG, "a") as f:
        f.write(f"{datetime.now().isoformat()} {h}\n")
    log(f"Anchor: {h}", "ANCHOR")

def load_plan():
    try:
        return json.loads(PLAN_FILE.read_text()) if PLAN_FILE.exists() else []
    except:
        return []

def save_plan(plan):
    PLAN_FILE.write_text(json.dumps(plan, indent=2, ensure_ascii=False))

def default_plan():
    return [
        {"task": "Проверить состояние системы и написать отчёт в лог", "done": False},
        {"task": "Создать скрипт мониторинга RAM в WishBridge/sandbox/", "done": False},
        {"task": "Проверить доступность LLM и записать результат в память", "done": False},
    ]

FORBIDDEN = [
    "input(", "os.system(", "__import__", "exec(", "eval(",
    "fork(", "shutdown", "reboot", "rm -rf",
]

def noema_check(code):
    for pat in FORBIDDEN:
        if pat in code:
            return False, f"запрещено: {pat}"
    if "while True:" in code and "break" not in code:
        return False, "while True без break"
    return True, "ok"

def syntax_check(code):
    try:
        ast.parse(code); return True, "ok"
    except SyntaxError as e:
        return False, str(e)

def clean_code(raw):
    if "```python" in raw:
        return raw.split("```python")[1].split("```")[0].strip()
    if "```" in raw:
        return raw.split("```")[1].split("```")[0].strip()
    return raw.strip()

def sandbox_run(code):
    ts   = int(time.time())
    path = SANDBOX_DIR / f"noah_{ts}.py"
    path.write_text(code)
    try:
        r = subprocess.run(["python3", str(path)],
            capture_output=True, text=True, timeout=30)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return 1, "", "TimeoutExpired"
    except Exception as e:
        return 1, "", str(e)

def check_single():
    if PIDFILE.exists():
        try:
            pid = int(PIDFILE.read_text().strip())
            os.kill(pid, 0)
            log(f"Уже запущен PID {pid} — останавливаю", "WARN")
            os.kill(pid, 15)
            time.sleep(3)
        except:
            pass
    PIDFILE.write_text(str(os.getpid()))

def cleanup(sig=None, frame=None):
    log("Noah завершает работу...", "WARN")
    PIDFILE.unlink(missing_ok=True)
    sys.exit(0)

def scheduler_loop(mem):
    log("Планировщик запущен", "PLAN")
    plan = load_plan() or default_plan()
    save_plan(plan)
    while True:
        try:
            if not system_ok():
                time.sleep(180); continue
            task = next((t for t in plan if not t.get("done")), None)
            if task:
                log(f"Задача: {task['task']}", "TASK")
                if llm_alive():
                    msgs = [
                        {"role":"system","content":"Ты Python разработчик WishBridge AI-OS. Пиши код без input()."},
                        {"role":"user","content":task["task"]}
                    ]
                    ans = ask_llm(msgs)
                    log(f"LLM: {len(ans)} символов", "LLM")
                    if "```" in ans:
                        code = clean_code(ans)
                        ok, reason = noema_check(code)
                        if ok:
                            syn_ok, _ = syntax_check(code)
                            if syn_ok:
                                rc, out, err = sandbox_run(code)
                                log(f"Sandbox: {'ok' if rc==0 else 'error'}", "SEC")
                                if out.strip(): log(out[:150])
                        else:
                            log(f"Noema: {reason}", "SEC")
                    add_memory(f"TASK: {task['task'][:60]}", mem)
                task["done"] = True
                save_plan(plan)
                time.sleep(10)
            else:
                log("Все задачи выполнены — новый план", "PLAN")
                add_memory("Все задачи выполнены", mem)
                create_anchor(mem)
                plan = default_plan()
                save_plan(plan)
                time.sleep(60)
        except Exception as e:
            log(f"Ошибка: {e}", "ERROR")
            time.sleep(30)

def heartbeat_loop(mem):
    while True:
        try:
            ram  = get_ram_mb()
            temp = get_temp()
            bat, charging = get_battery()
            llm  = "✓" if llm_alive() else "✗"
            log(f"RAM={ram}MB Temp={temp:.0f}°C Bat={bat}% LLM={llm}", "HEART")
            add_memory(f"HB: RAM={ram}MB T={temp:.0f}°C Bat={bat}%", mem)
        except Exception as e:
            log(f"Heartbeat: {e}", "ERROR")
        time.sleep(60)

def watchdog_loop(mem):
    log("Watchdog запущен", "SYS")
    while True:
        try:
            if not system_ok():
                add_memory("WATCHDOG: система нездорова", mem)
        except Exception as e:
            log(f"Watchdog: {e}", "ERROR")
        time.sleep(30)

def anchor_loop(mem):
    while True:
        time.sleep(900)
        try:
            create_anchor(mem)
        except Exception as e:
            log(f"Anchor: {e}", "ERROR")

def main():
    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT,  cleanup)
    check_single()
    mem = load_memory()

    is_first = not BIRTH_FILE.exists()
    if is_first:
        BIRTH_FILE.write_text(datetime.now().isoformat())
        log(f"✨ Первый запуск Noah на {DEVICE_NAME}!", "BORN")
        add_memory("NoahOS рождён на Honor 90", mem)
    else:
        log(f"Noah пробуждается на {DEVICE_NAME}", "INFO")
        add_memory("Noah проснулся", mem)

    log(f"LLM: {'✅ онлайн' if llm_alive() else '❌ офлайн'}", "INFO")
    log(f"RAM: {get_ram_mb()}MB | Temp: {get_temp():.0f}°C", "SYS")

    threads = [
        threading.Thread(target=scheduler_loop, args=(mem,), daemon=True, name="Scheduler"),
        threading.Thread(target=heartbeat_loop, args=(mem,), daemon=True, name="Heartbeat"),
        threading.Thread(target=watchdog_loop,  args=(mem,), daemon=True, name="Watchdog"),
        threading.Thread(target=anchor_loop,    args=(mem,), daemon=True, name="Anchor"),
    ]
    for t in threads:
        t.start()
        log(f"Поток: {t.name}", "INFO")

    log("Noah полностью запущен. Все системы активны.", "INFO")
    add_memory("NoahOS запущен. Все потоки активны.", mem)

    while True:
        time.sleep(60)
        dead = [t for t in threads if not t.is_alive()]
        if dead:
            log(f"Упавшие потоки: {[t.name for t in dead]}", "ERROR")

if __name__ == "__main__":
    main()


from pathlib import Path
import time

def save_to_sandbox(content):
    if not content or content.startswith("#"):
        return
    sandbox = Path.home() / "WishBridge/sandbox"
    sandbox.mkdir(exist_ok=True)
    fname = sandbox / f"task_{int(time.time())}.py"
    fname.write_text(content)
    print(f"[SANDBOX] сохранено: {fname}")
