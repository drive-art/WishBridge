# Noah OS — WishBridge AI Operating System

Distributed AI inference system for Android phones using Cactus engine.

## Hardware
- Master: Honor 90 (Snapdragon 7 Gen 1, 12GB RAM)
- Workers: any Android phone with Termux

## Speed
- Cactus + Qwen3-0.6B INT4: **24 tok/s** (vs 6 tok/s with llama.cpp)

## Quick Start
```bash
git clone https://github.com/drive-art/WishBridge.git
cd WishBridge
# Edit config_example.json → save as ~/.wishbridge/config.json
wb start
Commands
wb start — start Cactus + Noah
wb stop — stop all
wb status — system status
wb doctor — auto-fix issues
wb scan — full system scan
wb mem — show 7-day memory
wb cluster — start cluster mode
wb dashboard — cluster dashboard

## Модели для Cactus

| Модель | Телефон | Ссылка |
|--------|---------|--------|
| Qwen3-0.6B INT4 | X3 Pro (6GB) | https://huggingface.co/Cactus-Compute/Qwen3-0.6B/resolve/main/weights/qwen3-0.6b-int4.zip |
| Qwen3-1.7B INT4 | Honor 90 (12GB) | https://huggingface.co/Cactus-Compute/Qwen3-1.7B/resolve/main/weights/qwen3-1.7b-int4.zip |
