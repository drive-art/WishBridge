#!/data/data/com.termux/files/usr/bin/bash
set -e
echo "=== WB UPDATE ==="
cd ~/WishBridge && git pull
cp aios_agent.py ~/agents/aios_agent.py 2>/dev/null || true
if [ -f wb ]; then cp wb ~/bin/wb && chmod +x ~/bin/wb && echo "wb updated"; fi
pkill -f aios_agent.py || true
sleep 2
nohup python3 ~/WishBridge/aios_agent.py > ~/WishBridge/logs/aios.log 2>&1 &
sleep 2
pgrep -f aios_agent.py && echo "✅ AIOS запущен" || echo "❌ не запустился"
echo "Version:"; head -3 aios_agent.py
echo "=== DONE ==="
