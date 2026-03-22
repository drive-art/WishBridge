# WishBridge — Подбор моделей Cactus

## Наши тесты (март 2026)

| Телефон | CPU | RAM | Модель | Скорость | Качество RU |
|---------|-----|-----|--------|----------|-------------|
| Honor 90 | SD 7 Gen1 | 12GB | Qwen3-1.7B INT4 | 22 tok/s | хорошее |
| Poco X3 Pro | SD 860 | 6GB | Qwen3-0.6B INT8 | 12 tok/s | среднее |
| Poco F1 | SD 845 | 6GB | Qwen3-0.6B INT8 | 10 tok/s | среднее |
| Asus ZB631KL | SD 660 | 3.7GB | не рекомендуется | — | мало RAM |

## Правило выбора

- RAM меньше 4GB — LLM не рекомендуется
- RAM 4-6GB — Qwen3-0.6B INT8
- RAM 6-8GB — Qwen3-0.6B INT8
- RAM 12GB+ — Qwen3-1.7B INT4

## Ссылки для скачивания

Qwen3-0.6B INT4 (358MB):
https://huggingface.co/Cactus-Compute/Qwen3-0.6B/resolve/main/weights/qwen3-0.6b-int4.zip

Qwen3-0.6B INT8 (573MB) — лучше для русского:
https://huggingface.co/Cactus-Compute/Qwen3-0.6B/resolve/main/weights/qwen3-0.6b-int8.zip

Qwen3-1.7B INT4 — для 12GB RAM:
https://huggingface.co/Cactus-Compute/Qwen3-1.7B/resolve/main/weights/qwen3-1.7b-int4.zip

## Движок Cactus (42MB)

https://github.com/drive-art/cactus-runtime/releases/download/Tagv3.0-android/libcactus.so

## INT4 vs INT8

- INT4 = меньше размер, быстрее, хуже качество
- INT8 = больше размер, медленнее, лучше русский язык
