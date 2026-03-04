import telebot
import os
from core.immutable_log import ImmutableLog

# === путь к секретному файлу ===
TOKEN_FILE = os.path.expanduser("~/.wishbridge/secrets/telegram_token")
if not os.path.exists(TOKEN_FILE):
    raise Exception("Файл с Telegram токеном не найден")

with open(TOKEN_FILE, "r") as f:
    TOKEN = f.read().strip()

bot = telebot.TeleBot(TOKEN)
log = ImmutableLog()

@bot.message_handler(commands=['start'])
def start(msg):
    bot.reply_to(msg, "WishBridge Bot активен")

@bot.message_handler(func=lambda m: True)
def echo(msg):
    log.add_entry({"telegram": msg.text})
    bot.reply_to(msg, "Записано в ImmutableLog")

if __name__ == "__main__":
    print("🤖 Telegram bot запущен")
    bot.polling()
