#!/usr/bin/env python3
"""
wb_memory.py — Авто-память WishBridge
7 активных дней + долгосрочные темы навсегда.
"""
import json, sys, os, re
from pathlib import Path
from datetime import datetime

DB_FILE       = Path.home() / ".wishbridge" / "wb_memory.json"
HISTORY_FILE  = Path.home() / ".bash_history"
SNAPSHOT_FILE = Path.home() / ".wishbridge" / "wb_memory_snapshot.txt"
MAX_ACTIVE_DAYS  = 7
MAX_EVENTS_DAY   = 20
MAX_TOPICS       = 100

IMPORTANT_PATTERNS = [
    (r"python3?\s+.*\.py",          "🐍 python"),
    (r"git\s+(commit|push|pull|clone|add)", "📦 git"),
    (r"pip\s+install",              "📥 pip install"),
    (r"pkg\s+install",              "📥 pkg install"),
    (r"bash\s+.*install",           "⚙️  установка"),
    (r"wb\s+(start|stop|status)",   "🚀 wb команда"),
    (r"llama.server",                "🧠 LLM"),
    (r"pkill",                       "🛑 pkill"),
    (r"nano\s+|vim\s+|cat\s+>",   "✏️  редактирование"),
    (r"cp\s+|mv\s+|rm\s+",        "📁 файл"),
    (r"mkdir",                       "📁 mkdir"),
    (r"scan|doctor|check",           "🔍 диагностика"),
    (r"curl\s+http",                "🌐 curl/api"),
    (r"wget\s+",                    "⬇️  wget"),
]
SKIP_PATTERNS = [
    r"^ls\s*$", r"^cd\s", r"^pwd$", r"^echo\s+",
    r"^history", r"^clear$", r"^exit$", r"^\s*$", r"^#",
]

def load():
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    if DB_FILE.exists():
        try: return json.loads(DB_FILE.read_text())
        except: pass
    return {"days": [], "topics": [], "last_history_line": 0}

def save(data):
    DB_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))

def should_skip(cmd):
    for pat in SKIP_PATTERNS:
        if re.search(pat, cmd.strip()): return True
    return False

def classify(cmd):
    cmd = cmd.strip()
    for pattern, label in IMPORTANT_PATTERNS:
        if re.search(pattern, cmd, re.IGNORECASE):
            f = re.search(r"([\w_]+\.py|[\w_]+\.sh)", cmd)
            return f"{label} [{f.group(1)}]" if f else label
    return cmd[:50] if len(cmd) <= 50 else cmd[:47] + "…"

def auto_topic(events):
    text = " ".join(events).lower()
    if "cactus" in text: return "Cactus движок"
    if "install" in text or "установка" in text: return "установка / настройка"
    if "noah" in text: return "Noah агент"
    if "kernel" in text: return "Kernel NoahOS"
    if "scan" in text or "doctor" in text: return "диагностика системы"
    if "git" in text: return "git / синхронизация"
    if "llm" in text or "model" in text or "llama" in text: return "LLM / модели"
    if "wget" in text or "curl" in text: return "скачивание файлов"
    return "работа с WishBridge"

def read_history_new(last_line):
    if not HISTORY_FILE.exists(): return [], last_line
    lines = HISTORY_FILE.read_text(errors="ignore").splitlines()
    new_lines = lines[last_line:]
    events = []
    for cmd in new_lines:
        cmd = cmd.strip()
        if not cmd or should_skip(cmd): continue
        events.append(classify(cmd))
    seen, unique = set(), []
    for e in events:
        if e not in seen: seen.add(e); unique.append(e)
    return unique, len(lines)

def rotate_if_needed(data):
    while len(data["days"]) > MAX_ACTIVE_DAYS:
        oldest = data["days"].pop(0)
        data["topics"].append({
            "date": oldest["date"],
            "topic": oldest.get("topic", "WishBridge"),
            "events": len(oldest.get("events", [])),
        })
    if len(data["topics"]) > MAX_TOPICS:
        data["topics"] = data["topics"][-MAX_TOPICS:]

def get_or_create_today(data):
    today_str = datetime.now().strftime("%Y-%m-%d")
    for day in data["days"]:
        if day["date"] == today_str: return day
    new_day = {"date": today_str, "topic": "", "events": []}
    data["days"].append(new_day)
    rotate_if_needed(data)
    return data["days"][-1]

def cmd_update():
    data = load()
    new_events, new_last = read_history_new(data.get("last_history_line", 0))
    if not new_events:
        print("📋 Нет новых команд")
        return
    today = get_or_create_today(data)
    today["events"].extend(new_events)
    if len(today["events"]) > MAX_EVENTS_DAY:
        today["events"] = today["events"][-MAX_EVENTS_DAY:]
    today["topic"] = auto_topic(today["events"])
    data["last_history_line"] = new_last
    save(data)
    print(f"✅ {len(new_events)} новых событий | {today['date']} | {today['topic']}")

def cmd_add(text):
    data = load()
    today = get_or_create_today(data)
    today["events"].append(f"✋ {text[:150]}")
    today["topic"] = auto_topic(today["events"])
    save(data)
    print(f"✅ Добавлено: {text[:60]}")

def cmd_show():
    data = load()
    lines = [
        "╔══════════════════════════════════════════╗",
        "║     📋 WishBridge Memory — 7 дней        ║",
        "╚══════════════════════════════════════════╝",
        f"Снимок: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"Устройство: Poco X3 Pro | Noah Worker",
        "",
    ]
    if not data["days"]:
        lines.append("Память пуста. Запусти: python3 ~/wb_memory.py update")
    else:
        lines.append(f"━━━ АКТИВНАЯ ПАМЯТЬ ({len(data['days'])}/{MAX_ACTIVE_DAYS} дней) ━━━")
        for day in data["days"]:
            mark = " ◀ СЕГОДНЯ" if day["date"] == datetime.now().strftime("%Y-%m-%d") else ""
            lines.append(f"\n📅 {day['date']} | {day.get('topic','??')}{mark}")
            for e in day.get("events", [])[-10:]:
                lines.append(f"   • {e}")
    if data.get("topics"):
        lines += ["", f"━━━ ДОЛГОСРОЧНАЯ ПАМЯТЬ ({len(data['topics'])} тем) ━━━"]
        for t in data["topics"][-20:]:
            lines.append(f"  📌 {t['date']} | {t['topic']} ({t.get('events',0)} событий)")
    lines += ["", "══ КОНЕЦ ПАМЯТИ ══"]
    output = "\n".join(lines)
    print(output)
    SNAPSHOT_FILE.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_FILE.write_text(output, encoding="utf-8")
    print(f"\n💾 Снимок: {SNAPSHOT_FILE}")

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args: cmd_update(); print(); cmd_show()
    elif args[0] == "update": cmd_update()
    elif args[0] in ("show", "s"): cmd_show()
    elif args[0] == "add": cmd_add(" ".join(args[1:]))
    elif args[0] == "help": print(__doc__)
    else: cmd_add(" ".join(args))
