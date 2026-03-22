#!/data/data/com.termux/files/usr/bin/bash
# AIOS WishBridge — Auto Installer
# Использование: curl -s https://raw.githubusercontent.com/drive-art/WishBridge/main/install.sh | bash

echo "🚀 AIOS WishBridge Installer"
echo "=============================="

# 1. Базовые пакеты
pkg update -y && pkg install -y python git wget unzip

# 2. Скачиваем WishBridge
cd ~
git clone https://github.com/drive-art/WishBridge.git
cd WishBridge

# 3. Устанавливаем wb CLI
mkdir -p ~/bin
cp wb ~/bin/wb
chmod +x ~/bin/wb
echo 'export PATH="$HOME/bin:$PATH"' >> ~/.bashrc

# 4. Создаём папки
mkdir -p ~/.wishbridge/models ~/AI ~/WishBridge/logs ~/WishBridge/sandbox ~/agents

# 5. Копируем агента
cp noah_os.py ~/agents/
cp cactus_bridge.py ~/AI/
cp master_router.py ~/AI/
cp auto_discover.py ~/AI/
cp wb_memory.py ~/

# 6. Скачиваем Cactus
wget -q "https://github.com/drive-art/cactus-runtime/releases/download/Tagv3.0-android/libcactus.so" -O ~/AI/libcactus_android.so
echo "✅ Cactus engine скачан"

# 7. Автозапуск
mkdir -p ~/.termux/boot
cat > ~/.termux/boot/wishbridge_start.sh << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash
sleep 15
export PATH="$HOME/bin:$PATH"
termux-wake-lock
wb start
EOF
chmod +x ~/.termux/boot/wishbridge_start.sh

echo ""
echo "✅ AIOS WishBridge установлен!"
echo "👉 Перезапусти Termux и введи: wb start"
