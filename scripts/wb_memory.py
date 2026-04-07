#!/usr/bin/env python3
"""
wb_memory.py v2.0 — Семантическая память WishBridge
════════════════════════════════════════════════════
Хранит не команды, а «состояния системы» и «решения».

Каждая запись = {
    "cmd": "что сделано",
    "context": "зачем / в какой ситуации",  
    "outcome": "успех / провал / результат",
    "tags": ["git", "rollback", "working"],
    "milestone": true/false
}

Теперь поиск «рабочая версия без моста» вернёт:
📅 2026-04-05 | git rollback
   • Откат до pre-cactus: git checkout 2dbb8a1 (работает стабильно)
   ⚠️ НЕ ИСПОЛЬЗОВАТЬ: коммиты после a1b2c3d — сломанный bridge
"""

import json, sys, os, re, subprocess
from pathlib import Path
from datetime import datetime
from collections import Counter

DB_FILE = Path.home() / ".wishbridge" / "wb_memory_v2.json"
SNAPSHOT_FILE = Path.home() / ".wishbridge" / "wb_memory_annotated.txt"

MAX_ACTIVE_DAYS = 7
MAX_EVENTS_DAY = 15  # Меньше, но качественнее

# ═══════════════════════════════════════════════════════
# СЕМАНТИЧЕСКИЕ ПАТТЕРНЫ (не просто классификация — смысл)
# ═══════════════════════════════════════════════════════

SEMANTIC_PATTERNS = [
    # Git с контекстом
    (r"git\s+checkout\s+([a-f0-9]+)", "git_rollback", 
     "Откат до {match}", "critical"),
    (r"git\s+reset\s+--hard", "git_nuclear", 
     "Жёсткий сброс изменений", "danger"),
    (r"git\s+revert", "git_revert", 
     "Отмена коммита", "milestone"),
    
    # Мосты и движки (критично!)
    (r"cactus_bridge.*--model\s+(\S+)", "bridge_start", 
     "Запуск моста: {match}", "milestone"),
    (r"pkill.*cactus|pkill.*bridge", "bridge_kill", 
     "Остановка моста", "critical"),
    (r"python3.*cactus_bridge.*py", "bridge_run", 
     "Запуск bridge (устаревший способ)", "deprecated"),
    
    # Модели (что работало, что нет)
    (r"lfm2-8b", "model_lfm2_8b", 
     "Модель LFM2-8B (тяжёлая, ~7.5GB)", "heavy"),
    (r"lfm2-2.6b", "model_lfm2_2b", 
     "Модель LFM2-2.6B (средняя, ~3.5GB)", "optimal"),
    (r"qwen3-0.6b", "model_qwen_small", 
     "Модель Qwen3-0.6B (лёгкая, ~1.5GB)", "light"),
    
    # Диагностика
    (r"wishbridge_doctor|wb_morning", "diagnostic", 
     "Диагностика системы", "routine"),
    (r"mem(\s|$)", "memory_check", 
     "Проверка памяти (wb_memory)", "meta"),
    
    # Установка/слом
    (r"pip\s+install|pkg\s+install", "install", 
     "Установка пакетов", "setup"),
    (r"chmod\s+777|chmod\s+\+x", "permissions", 
     "Изменение прав доступа", "setup"),
]

SKIP_PATTERNS = [
    r"^ls\s", r"^cd\s", r"^pwd$", r"^echo\s", r"^cat\s",
    r"^clear$", r"^history", r"^exit$", r"^\s*$", r"^#",
    r"^source\s+~/.bashrc"
]

# ═══════════════════════════════════════════════════════
# ЯДРО СИСТЕМЫ
# ═══════════════════════════════════════════════════════

class SemanticMemory:
    def __init__(self):
        self.data = self._load()
    
    def _load(self):
        if DB_FILE.exists():
            try:
                return json.loads(DB_FILE.read_text())
            except:
                pass
        return {
            "days": [],
            "milestones": [],  # Важные вехи (откаты, запуски)
            "knowledge": {},   # Накопленные факты: {"bridge_v3": "работает стабильно"}
        }
    
    def save(self):
        DB_FILE.parent.mkdir(parents=True, exist_ok=True)
        DB_FILE.write_text(json.dumps(self.data, indent=2, ensure_ascii=False))
    
    def get_today(self):
        today_str = datetime.now().strftime("%Y-%m-%d")
        for day in self.data["days"]:
            if day["date"] == today_str:
                return day
        
        # Ротация
        while len(self.data["days"]) >= MAX_ACTIVE_DAYS:
            old = self.data["days"].pop(0)
            # Сохраняем milestones в долгосрочную память
            for ev in old.get("events", []):
                if ev.get("milestone"):
                    self.data["milestones"].append({
                        "date": old["date"],
                        "event": ev
                    })
        
        new_day = {"date": today_str, "events": [], "summary": ""}
        self.data["days"].append(new_day)
        return new_day
    
    def parse_command(self, cmd: str) -> dict:
        """Превращает команду в семантическое событие."""
        cmd = cmd.strip()
        if not cmd or any(re.match(p, cmd) for p in SKIP_PATTERNS):
            return None
        
        event = {
            "cmd": cmd[:100],
            "time": datetime.now().isoformat(),
            "context": "",
            "outcome": "unknown",
            "tags": [],
            "milestone": False,
            "weight": 1
        }
        
        # Ищем семантический паттерн
        for pattern, tag, template, importance in SEMANTIC_PATTERNS:
            match = re.search(pattern, cmd, re.I)
            if match:
                event["tags"].append(tag)
                event["context"] = template.format(match=match.group(1) if match.groups() else "...")
                
                if importance == "critical":
                    event["milestone"] = True
                    event["weight"] = 5
                elif importance == "milestone":
                    event["milestone"] = True
                    event["weight"] = 3
                elif importance == "danger":
                    event["outcome"] = "⚠️ рискованная операция"
                    event["weight"] = 4
                
                break
        else:
            # Не распознано — обобщаем
            event["context"] = "Команда: " + cmd[:50]
            event["tags"].append("other")
        
        # Дедупликация серий (git push x3 → git push (x3))
        event = self._deduplicate_series(event)
        
        return event
    
    def _deduplicate_series(self, event):
        """Если последние 3 события — то же самое, склеиваем."""
        today = self.get_today()
        events = today["events"]
        
        if not events:
            return event
        
        # Смотрим последнее событие
        last = events[-1]
        if last["cmd"] == event["cmd"] and not event["milestone"]:
            # Увеличиваем счётчик
            last["repeat"] = last.get("repeat", 1) + 1
            last["weight"] += 1
            return None  # Не добавляем новое, обновили старое
        
        return event
    
    def add_outcome(self, cmd_hint: str, outcome: str, note: str = ""):
        """Добавить результат к событию (ручная аннотация)."""
        today = self.get_today()
        for ev in reversed(today["events"]):
            if cmd_hint in ev["cmd"]:
                ev["outcome"] = outcome
                if note:
                    ev["note"] = note
                # Обновляем знания
                if "работает" in outcome or "stable" in outcome:
                    for tag in ev["tags"]:
                        self.data["knowledge"][tag] = "✅ " + note
                elif "сломан" in outcome or "fail" in outcome:
                    for tag in ev["tags"]:
                        self.data["knowledge"][tag] = "❌ " + note
                self.save()
                return True
        return False
    
    def find_working_state(self, **filters):
        """Поиск: find_working_state(tag="bridge_start", outcome="успех")"""
        results = []
        
        # Сначала в активных днях
        for day in self.data["days"]:
            for ev in day["events"]:
                if all(t in ev["tags"] for t in filters.get("tags", [])):
                    if filters.get("outcome") in ev.get("outcome", ""):
                        results.append((day["date"], ev))
        
        # Потом в milestones
        for ms in self.data["milestones"]:
            ev = ms["event"]
            if all(t in ev["tags"] for t in filters.get("tags", [])):
                results.append((ms["date"], ev))
        
        return results
    
    def generate_summary(self):
        """Генерирует human-readable сводку."""
        lines = []
        lines.append("╔══════════════════════════════════════════════════════╗")
        lines.append("║     📋 WishBridge Semantic Memory v2.0               ║")
        lines.append("╚══════════════════════════════════════════════════════╝")
        lines.append(f"Обновлено: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append("")
        
        # Активные дни
        lines.append(f"━━━ АКТИВНАЯ ПАМЯТЬ ({len(self.data['days'])} дней) ━━━")
        for day in self.data["days"]:
            today_mark = " ◀ СЕГОДНЯ" if day["date"] == datetime.now().strftime("%Y-%m-%d") else ""
            lines.append(f"\n📅 {day['date']}{today_mark}")
            
            for ev in day["events"]:
                icon = "🔴" if ev.get("milestone") else "📝"
                repeat = f" (×{ev.get('repeat', 1)})" if ev.get("repeat", 1) > 1 else ""
                outcome = f" → {ev['outcome']}" if ev.get("outcome") != "unknown" else ""
                note = f"\n      💡 {ev['note']}" if ev.get("note") else ""
                
                lines.append(f"   {icon} {ev['context']}{repeat}{outcome}{note}")
        
        # Знания (что работает, что нет)
        if self.data["knowledge"]:
            lines.append(f"\n━━━ НАКОПЛЕННЫЕ ЗНАНИЯ ━━━")
            for key, val in list(self.data["knowledge"].items())[-10:]:
                lines.append(f"   {val} ({key})")
        
        # Milestones (важные вехи)
        if self.data["milestones"]:
            lines.append(f"\n━━━ КЛЮЧЕВЫЕ ВЕХИ ━━━")
            for ms in self.data["milestones"][-5:]:
                ev = ms["event"]
                lines.append(f"   📌 {ms['date']}: {ev['context']}")
        
        return "\n".join(lines)

# ═══════════════════════════════════════════════════════
# КОМАНДЫ CLI
# ═══════════════════════════════════════════════════════

memory = SemanticMemory()

def cmd_update():
    """Читает bash_history и создаёт семантические записи."""
    history = Path.home() / ".bash_history"
    if not history.exists():
        print("❌ Нет .bash_history")
        return
    
    lines = history.read_text(errors="ignore").splitlines()
    # Берём последние 50 непрочитанных (упрощённо — в проде нужен offset)
    new_lines = lines[-50:]
    
    added = 0
    for cmd in new_lines:
        event = memory.parse_command(cmd)
        if event:
            today = memory.get_today()
            today["events"].append(event)
            added += 1
    
    # Авто-итог дня
    today = memory.get_today()
    if today["events"]:
        tags = [t for ev in today["events"] for t in ev["tags"]]
        top_tag = Counter(tags).most_common(1)[0][0]
        today["summary"] = f"Работа с {top_tag}"
    
    memory.save()
    print(f"✅ Добавлено событий: {added}")
    print(f"📊 Сегодня: {len(today['events'])} записей")

def cmd_annotate(cmd_hint, outcome, note=""):
    """Ручная аннотация: wb_memory.py note 'bridge' '❌ сломан' 'не грузит LFM2'"""
    if memory.add_outcome(cmd_hint, outcome, note):
        print(f"✅ Аннотация добавлена: {cmd_hint} → {outcome}")
    else:
        print(f"⚠️ Команда не найдена: {cmd_hint}")

def cmd_find(tag):
    """Поиск: wb_memory.py find bridge_start"""
    results = memory.find_working_state(tags=[tag])
    print(f"🔍 Найдено {len(results)} записей с тегом '{tag}':")
    for date, ev in results[-10:]:
        status = ev.get("outcome", "?")
        print(f"   {date}: {ev['context']} [{status}]")

def cmd_show():
    """Полная сводка."""
    print(memory.generate_summary())
    SNAPSHOT_FILE.write_text(memory.generate_summary(), encoding="utf-8")
    print(f"\n💾 Сохранено: {SNAPSHOT_FILE}")

def cmd_status():
    """Кратко: дней, событий, знаний."""
    d = memory.data
    print(f"📋 Дней: {len(d['days'])}/{MAX_ACTIVE_DAYS} | "
          f"Вех: {len(d['milestones'])} | "
          f"Знаний: {len(d['knowledge'])}")

# ═══════════════════════════════════════════════════════

if __name__ == "__main__":
    args = sys.argv[1:]
    
    if not args or args[0] == "update":
        cmd_update()
        if not args:
            cmd_show()
    elif args[0] == "note" and len(args) >= 3:
        cmd_annotate(args[1], args[2], " ".join(args[3:]))
    elif args[0] == "find":
        cmd_find(args[1] if len(args) > 1 else "bridge")
    elif args[0] in ("show", "s"):
        cmd_show()
    elif args[0] in ("status", "st"):
        cmd_status()
    else:
        # Всё остальное — поиск
        cmd_find(args[0])
