#!/data/data/com.termux/files/usr/bin/bash
# ╔══════════════════════════════════════════════════════╗
# ║   WISHBRIDGE DOCTOR — Honor 90 / Atlas               ║
# ║   Cactus v1 + qwen3 + core_engine v4                 ║
# ╚══════════════════════════════════════════════════════╝

echo
echo "╔══════════════════════════════════════════╗"
echo "║      WISHBRIDGE DOCTOR — Atlas           ║"
echo "╚══════════════════════════════════════════╝"
echo "$(date '+%Y-%m-%d %H:%M:%S')"
echo

# ── 1. ДВИЖОК ─────────────────────────────────────────
echo "── 1. CACTUS ENGINE ──"
SO=~/AI/libcactus_android.so
if [ -f "$SO" ]; then
    SIZE=$(du -h "$SO" | cut -f1)
    echo "  ✅ libcactus_android.so  $SIZE"
else
    echo "  ❌ libcactus_android.so НЕ НАЙДЕН"
fi

# Симлинк
LINK=~/WishBridge/engines/cactus/libcactus.so
if [ -L "$LINK" ]; then
    echo "  ✅ Симлинк: $LINK → $(readlink $LINK)"
else
    echo "  ⚠️  Симлинк отсутствует (движок ищет .so напрямую)"
fi

# ── 2. МОДЕЛИ ─────────────────────────────────────────
echo
echo "── 2. CACTUS MODELS ──"
MODELS_DIR=~/AI/cactus-models
if [ -d "$MODELS_DIR" ]; then
    for m in "$MODELS_DIR"/*/; do
        NAME=$(basename "$m")
        if [ -f "$m/config.txt" ]; then
            SIZE=$(du -sh "$m" 2>/dev/null | cut -f1)
            echo "  ✅ $NAME  ($SIZE)"
        else
            echo "  ⚠️  $NAME — нет config.txt"
        fi
    done
else
    echo "  ❌ Папка моделей не найдена: $MODELS_DIR"
fi

# ── 3. HTTP API ───────────────────────────────────────
echo
echo "── 3. HTTP API (порт 8080) ──"
HEALTH=$(curl -s --max-time 3 http://127.0.0.1:8080/health 2>/dev/null)
if [ -n "$HEALTH" ]; then
    MODEL=$(echo "$HEALTH" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('model','?'))" 2>/dev/null)
    TEMP=$(echo "$HEALTH"  | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"{d.get('temp',0):.1f}°C\")" 2>/dev/null)
    TPS=$(echo "$HEALTH"   | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('metrics',{}).get('avg_tps',0))" 2>/dev/null)
    echo "  ✅ LLM работает"
    echo "     Модель : $MODEL"
    echo "     Темп   : $TEMP"
    echo "     Avg TPS: $TPS"
else
    echo "  ❌ LLM не отвечает на порту 8080"
fi

# ── 4. ПРОЦЕССЫ ───────────────────────────────────────
echo
echo "── 4. AI ПРОЦЕССЫ ──"
PROCS=$(ps aux | grep -E "core_engine|cactus_bridge|aios_agent|noah" | grep -v grep)
if [ -n "$PROCS" ]; then
    echo "$PROCS" | awk '{printf "  PID:%-7s CPU:%-5s MEM:%-5s %s\n",$2,$3,$4,$11}'
else
    echo "  ℹ️  AI процессы не запущены"
fi

# ── 5. RAM И ТЕМПЕРАТУРА ──────────────────────────────
echo
echo "── 5. RAM / TEMP ──"
awk '/MemAvailable/{a=$2}/MemTotal/{t=$2}END{
    printf "  RAM: %d MB свободно из %d MB (%.0f%%)\n",a/1024,t/1024,a/t*100
}' /proc/meminfo

MAXTEMP=0
for i in $(seq 0 9); do
    T=$(cat /sys/class/thermal/thermal_zone${i}/temp 2>/dev/null)
    [ -n "$T" ] && [ "$T" -gt "$MAXTEMP" ] && MAXTEMP=$T
done
echo "  Temp: $((MAXTEMP/1000))°C (max по зонам)"

# ── 6. АГЕНТ ATLAS ────────────────────────────────────
echo
echo "── 6. AGENT CONFIG ──"
AGENT=~/agents/agent.json
if [ -f "$AGENT" ]; then
    NAME=$(python3 -c "import json; d=json.load(open('$AGENT')); print(d.get('name','?'))" 2>/dev/null)
    ROLE=$(python3 -c "import json; d=json.load(open('$AGENT')); print(d.get('cluster_role','?'))" 2>/dev/null)
    echo "  ✅ $NAME ($ROLE)"
else
    echo "  ❌ ~/agents/agent.json не найден"
fi

# ── 7. GIT СТАТУС ─────────────────────────────────────
echo
echo "── 7. GIT ──"
cd ~/WishBridge 2>/dev/null && {
    BRANCH=$(git branch --show-current 2>/dev/null)
    LAST=$(git log --oneline -1 2>/dev/null)
    echo "  Branch : $BRANCH"
    echo "  Last   : $LAST"
    UNTRACKED=$(git status --short 2>/dev/null | wc -l)
    [ "$UNTRACKED" -gt 0 ] && echo "  ⚠️  Незапушенных файлов: $UNTRACKED"
}

# ── 8. АВТОЗАПУСК ─────────────────────────────────────
echo
echo "── 8. АВТОЗАПУСК ──"
if grep -q "core_engine" ~/.bashrc 2>/dev/null; then
    echo "  ✅ Автозапуск в .bashrc настроен"
else
    echo "  ⚠️  Автозапуск в .bashrc НЕ настроен"
fi

BOOT=~/.termux/boot/wishbridge_start.sh
if [ -f "$BOOT" ]; then
    echo "  ✅ Termux:Boot скрипт найден"
else
    echo "  ℹ️  Termux:Boot скрипт отсутствует"
fi

# ── 9. GOOGLE DRIVE ───────────────────────────────────
echo
echo "── 9. GOOGLE DRIVE BACKUP ──"
REMOTES=$(rclone listremotes 2>/dev/null)
if [ -n "$REMOTES" ]; then
    echo "  Remotes: $REMOTES"
    # Показать последний бэкап
    LAST_BACKUP=$(rclone ls drive:WishBridge 2>/dev/null | tail -3)
    if [ -n "$LAST_BACKUP" ]; then
        echo "  Последний бэкап в drive:WishBridge:"
        echo "$LAST_BACKUP" | awk '{print "    "$0}'
    else
        echo "  ℹ️  Папка drive:WishBridge пуста или не существует"
    fi
else
    echo "  ℹ️  rclone не настроен"
fi

echo
echo "╔══════════════════════════════════════════╗"
echo "║           Doctor finished ✅              ║"
echo "╚══════════════════════════════════════════╝"
echo
