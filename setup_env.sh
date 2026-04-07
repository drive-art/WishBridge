#!/data/data/com.termux/files/usr/bin/bash
echo "Восстановление окружения STAGE 0..."
pkg update -y && pkg upgrade -y
pkg install python git nano htop wget -y
termux-setup-storage
echo "Окружение готово."
