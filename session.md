# WishBridge — Память проекта Honor 90

## 🌵 CACTUS ENGINE (активен)
- lib: ~/AI/libcactus_android.so
- модель: ~/AI/cactus-models/qwen3-0.6b-int4
- bridge: ~/AI/cactus_bridge.py (порт 8080)
- скорость: 24 tok/s
- wb start = запуск Cactus + Noah

## 🌐 КЛАСТЕР (в разработке)
- auto_discover: ~/AI/auto_discover.py
- worker installer: в разработке
- master: Honor 90 (этот телефон)

## 🌵 Cactus (АКТИВЕН с 2026-03-20)
- libcactus_android.so: ~/AI/libcactus_android.so (42MB)
- Bridge: ~/AI/cactus_bridge.py (порт 8080)
- Модель: ~/AI/cactus-models/qwen3-0.6b-int4 (358MB)
- Скорость: 24 tok/s (vs 6 tok/s llama-server)
- wb start → запускает Cactus + Noah автоматически

## Железо
- Устройство: Honor 90 (REA-NX9)
- Процессор: Snapdragon 7 Gen 1 Accelerated Edition
- RAM: 12GB — доступно ~4GB при запущенном LLM (3B модель)
- Диск: 480GB свободно
- Android 15 / MagicOS 9.0

## Что установлено и работает
- llama-server:  ~/llama.cpp/build/bin/llama-server ✅
- noah_os.py:    ~/agents/noah_os.py ✅
- wb CLI:        ~/bin/wb ✅
- Сканеры:       ~/scans/ ✅
- config.json:   ~/.wishbridge/config.json ✅
- session.md:    ~/.wishbridge/session.md (этот файл) ✅

## Модели (все в ~/.wishbridge/models/)
- wb model light → smollm2-1.7b-q4.gguf     (1.0GB)
- wb model work  → nanbeige4.1-3b-q4_k_m.gguf (2.3GB) ⚠️ thinking модель
- wb model power → qwen3.5-4b-q4.gguf        (2.6GB) — ещё не тестировали

## Все команды wb
- wb start/stop/status/logs
- wb model light|work|power
- wb sc sys|ag|mod|proc|dup
- wb sc doctor
- wb ses          — показать эту память
- wb se           — редактировать память
- wb sa "текст"   — добавить заметку

## Известные проблемы
- Nanbeige 4.1 — thinking модель: даёт ~97 символов, content пустой
  Причина: за 2000 токенов не успевает закончить мышление
  Решение: нужен Cactus (70+ tok/s) или SmolLM2 для задач
- wb stop убивает LLM — после нужно wb model work
- Батарея: termux-api установлен но нужно приложение Termux:API
- Температура zone2: показывает -273°C (битый датчик) — игнорируем

## Движки LLM
- Сейчас: llama-server (~3 токена/сек на CPU)
- Цель:   Cactus (libcactus.so в ~/AI/) — до 70+ токенов/сек
- Cactus путь: ~/AI/libcactus.so (50MB) и ~/AI/cactus-runtime/
- Нужно: Python-мост через ctypes к libcactus.so

## Следующие шаги (по приоритету)
1. Переключить Noah на SmolLM2 для задач (он быстрее отвечает)
2. Подключить Cactus через ctypes — главный приоритет
3. Настроить автозапуск при старте телефона
4. Протестировать Qwen3.5-4B когда Cactus заработает
5. Подключить другие телефоны (X3, Asus) как Workers

## История сессий
- 2026-03-18: первый запуск Noah, установка всей системы


==================================================
🧠 ОБНОВЛЕНИЕ ПАМЯТИ: 2026-03-18 18:28
==================================================

## 🔧 Что было настроено сегодня

✔ Автофикс LLM (content + reasoning fallback)
✔ Sandbox сохранение кода (~/WishBridge/sandbox/)
✔ wb run — запуск sandbox
✔ wb doctor / wb doc — диагностика
✔ wb sc mg — morning check
✔ wb scan — полный скан
✔ wb start → теперь запускает LLM + Noah
✔ Автостарт после перезагрузки (Termux:Boot + sleep 10 + RAM check)

---

## 🧠 Поведение LLM (ВАЖНО)

- nanbeige4.1-3b → thinking модель
- content часто пустой
- ответ живёт в reasoning_content
- скорость ~3 токена/сек → не успевает за 2000 токенов
- итог: ~90–100 символов

📌 Вывод:
- для задач → использовать smollm2
- nanbeige → только для сложных reasoning задач
- нужен Cactus (приоритет №1)

---

## ⚙️ Текущие параметры LLM

- max_tokens: 2000
- timeout: 300
- endpoint: http://127.0.0.1:8080/v1/chat/completions

---

## 💣 Частые ошибки (и решения)

❌ content пустой  
✔ брать reasoning_content

❌ timeout  
✔ увеличить timeout до 300+

❌ ImportError: re из pathlib  
✔ import re отдельно

❌ bash ошибки с Python  
✔ всегда через python3 - << 'PYEOF'

---

## 🚀 ВСЕ КОМАНДЫ WB (АКТУАЛЬНО)

### ▶️ Основные
wb start
wb stop
wb status
wb logs

### 🧠 Модели
wb model light
wb model work
wb model power

### 🧪 Sandbox
wb run

### 🧠 Память
wb ses
wb se
wb sa "текст"

### 🔍 Сканеры
wb sc sys
wb sc ag
wb sc mod
wb sc proc
wb sc dup
wb sc mg

### 🩺 Диагностика
wb doctor
wb doc

### 💥 Полный скан
wb scan

---

## 📂 Ключевые пути

- ~/agents/noah_os.py
- ~/WishBridge/sandbox/
- ~/.wishbridge/session.md
- ~/.wishbridge/config.json
- ~/bin/wb
- ~/scans/

---

## 🧭 Состояние системы

✔ Noah работает стабильно  
✔ LLM запускается  
✔ Sandbox пишет код  
✔ wb CLI расширен  
✔ Автостарт есть  

⚠️ Узкое место:
→ скорость LLM (CPU)

---

## 🎯 Следующий шаг

1. Cactus (libcactus.so) — критично
2. Переключение задач на smollm2
3. Noah → wb run (автоисполнение)
4. Распределённые агенты (другие телефоны)

==================================================
2026-03-18 19:42 — SmolLM2 работает! LLM даёт 3000+ символов. Sandbox выполняет код. 2026-03-18
2026-03-18 22:15 — АРХИТЕКТУРА КЛАСТЕРА: Atlas(Honor90)=Master. Каждый телефон имеет свой device_id и device_name. Обновления с GitHub но config.json локальный — идентификация не перетирается. Оптимизация под железо хранится в device_profile.json
2026-03-18 22:17 — 2026-03-18 итог: Noah работает, SmolLM2 активна, sandbox пишет код, 7 файлов. Завтра: Cactus + tmux mon + кластер
2026-03-19 16:45 — 2026-03-19: ПРОРЫВ! Собрана libcactus.so Python FFI на GitHub Actions ARM. URL: https://github.com/drive-art/cactus-runtime/actions/runs/23300201856/artifacts/6007950830 — завтра скачать и подключить к Noah!
2026-03-19 17:24 — 2026-03-19 CACTUS СОБРАН! GitHub Actions ARM64. Для пересборки: github.com/drive-art/cactus-runtime → Actions → Build Cactus Python FFI → Run workflow. Release: github.com/drive-art/cactus-runtime/releases
2026-03-19 21:42 — 2026-03-19 вечер: RAM исчерпана (364MB), остановили всё. Завтра: Cactus NDK сборка + тест новой libcactus_new.so
2026-03-20 16:42 — 2026-03-20 ФИНАЛ: Noah работает на Cactus 24tok/s. LLM даёт 1495 символов. Система стабильна. Следующий шаг: кластер других телефонов
