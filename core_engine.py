#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║                    CORE ENGINE v4.0 "ATLAS"                                  ║
# ║              WishBridge AI OS — Production Engine                            ║
# ║                                                                              ║
# ║  Архитектура (слои снизу вверх):                                             ║
# ║                                                                              ║
# ║  ┌─────────────────────────────────────────────────────┐                    ║
# ║  │  libcactus_android.so  (42MB, ARM64, NDK r26d)      │  ← C движок        ║
# ║  │  cactus_init / cactus_complete / cactus_destroy      │                    ║
# ║  └──────────────────┬──────────────────────────────────┘                    ║
# ║                     │ ctypes                                                 ║
# ║  ┌──────────────────▼──────────────────────────────────┐                    ║
# ║  │  CactusEngine  (Python биндинг, thread-safe)        │  ← этот файл       ║
# ║  └──────────────────┬──────────────────────────────────┘                    ║
# ║                     │                                                        ║
# ║  ┌──────────────────▼──────────────────────────────────┐                    ║
# ║  │  Scheduler  (очередь задач + воркеры)               │                    ║
# ║  └──────────────────┬──────────────────────────────────┘                    ║
# ║                     │                                                        ║
# ║  ┌──────────────────▼──────────────────────────────────┐                    ║
# ║  │  HttpServer  (OpenAI-совместимый, порт из config)   │  ← агенты сюда     ║
# ║  └─────────────────────────────────────────────────────┘                    ║
# ║                                                                              ║
# ║  Дополнительно (необязательные, не ломают запуск):                           ║
# ║  • ThermalManager  — следит за температурой                                 ║
# ║  • NetworkStack    — UDP heartbeat + TCP между телефонами кластера           ║
# ║  • SecureSandbox   — AST whitelist для кода от агентов                      ║
# ║  • Metrics         — latency / TPS / error rate                             ║
# ║                                                                              ║
# ║  Что исправлено относительно v3.x:                                           ║
# ║  • cactus_free → cactus_destroy (правильное имя)                            ║
# ║  • buf_size: c_size_t → c_int                                               ║
# ║  • ответ Cactus — JSON {"response":..., "decode_tps":...}, не plain text    ║
# ║  • Packet.deserialize получает raw[4:], не raw.split(b':',1)[1]             ║
# ║  • /tmp → CONFIG.sandbox_dir (на Android нет /tmp)                          ║
# ║  • HTTP сервер вместо raw TCP (совместимость с aios_agent.py)               ║
# ║  • NetworkStack необязателен — не ломает запуск если порт занят             ║
# ║  • Self-test честный — не врёт "All systems nominal" при ошибках            ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

# ── Манифест ──────────────────────────────────────────────────────────────────
# Версия:   4.0
# Агент:    Atlas (Honor 90 — мастер-узел кластера)
# Кластер:  Atlas (Honor 90) · Noah (Poco X3 Pro) · Noema (Poco F1)
# Порты:    HTTP API 8080 · UDP Discovery 45454 · TCP Tasks 45455
# Модели:   qwen3-1.7b-int4 (Honor 90) · qwen3-0.6b-int8 (Poco X3/F1)
# Формат:   .weights папки (НЕ GGUF) — ~/AI/cactus-models/<name>/
# ─────────────────────────────────────────────────────────────────────────────

import ast
import ctypes
import hashlib
import hmac
import json
import logging
import os
import queue
import re
import resource
import secrets
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
import zlib
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

try:
    import requests
    REQUESTS_OK = True
except ImportError:
    REQUESTS_OK = False


# ══════════════════════════════════════════════════════════════════════════════
# КОНФИГУРАЦИЯ
# Все параметры в одном месте. Нет магических чисел в коде.
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class Config:
    """
    Единственный источник правды для всех параметров системы.
    Читается из config.json если он есть, иначе — умные дефолты.
    """
    home: Path = field(default_factory=Path.home)

    # ── Пути ──────────────────────────────────────────────────────────────────
    @property
    def wb_root(self) -> Path:
        return self.home / "WishBridge"

    @property
    def engine_dir(self) -> Path:
        return self.wb_root / "engines" / "cactus"

    @property
    def memory_dir(self) -> Path:
        return self.wb_root / "memory"

    @property
    def log_dir(self) -> Path:
        return self.wb_root / "logs"

    @property
    def sandbox_dir(self) -> Path:
        # Важно: Android не имеет /tmp — используем папку в home
        return self.wb_root / "sandbox"

    @property
    def config_file(self) -> Path:
        return self.wb_root / "config.json"

    @property
    def libcactus(self) -> Path:
        """
        Порядок поиска libcactus:
        1. engines/cactus/libcactus.so  (симлинк — рекомендуемый путь)
        2. ~/AI/libcactus_android.so    (прямой путь к рабочей 42MB сборке)
        """
        candidates = [
            self.engine_dir / "libcactus.so",
            self.home / "AI" / "libcactus_android.so",
        ]
        for c in candidates:
            if c.exists():
                return c
        return candidates[0]  # вернём первый даже если нет — ошибка будет внятная

    @property
    def model(self) -> Path:
        """
        Cactus читает ПАПКУ с файлами .weights + config.txt
        НЕ .gguf файл — это важно.

        Приоритет для Honor 90 (12GB RAM): qwen3-1.7b-int4
        Приоритет для Poco X3/F1 (6GB RAM): qwen3-0.6b-int8
        """
        models_dir = self.home / "AI" / "cactus-models"
        priority = [
            "qwen3-1.7b-int4",   # Honor 90 — лучше для русского
            "qwen3-0.6b-int8",   # Poco X3 Pro / Poco F1
            "qwen3-0.6b-int4",   # минимум
        ]
        for name in priority:
            p = models_dir / name
            if p.is_dir() and (p / "config.txt").exists():
                return p
        # Fallback — первая найденная папка с config.txt
        for p in models_dir.iterdir() if models_dir.exists() else []:
            if p.is_dir() and (p / "config.txt").exists():
                return p
        return models_dir / "qwen3-0.6b-int8"

    # ── Сеть (читается из config.json если есть) ──────────────────────────────
    HTTP_PORT:        int   = 8080    # OpenAI-совместимый HTTP API
    DISCOVERY_PORT:   int   = 45454   # UDP broadcast для heartbeat кластера
    TASK_PORT:        int   = 45455   # TCP для задач между агентами
    TCP_TIMEOUT:      int   = 30
    MAX_PACKET_SIZE:  int   = 1_048_576  # 1MB
    COMPRESSION:      int   = 6
    SECRET_ENV:       str   = "WB_SECRET"  # переменная окружения для HMAC

    # ── Cactus ────────────────────────────────────────────────────────────────
    # buf_size в cactus_complete — c_int, не c_size_t!
    RESPONSE_BUF:  int = 524288   # 512KB — буфер для записи ответа
    INFER_BUF:     int = 131072   # 128KB — передаётся как buf_size аргумент

    # ── Инференс ──────────────────────────────────────────────────────────────
    DEFAULT_MAX_TOKENS:  int   = 512
    DEFAULT_TEMPERATURE: float = 0.7
    DEFAULT_THREADS:     int   = 4

    # ── Термальная защита ─────────────────────────────────────────────────────
    THERMAL_WARN:     float = 45.0   # °C — предупреждение
    THERMAL_CRITICAL: float = 48.0   # °C — блокировка инференса
    THERMAL_INTERVAL: int   = 3      # сек между проверками

    # ── Очередь задач ─────────────────────────────────────────────────────────
    QUEUE_SIZE: int = 50
    WORKERS:    int = 2

    # ── Метрики ───────────────────────────────────────────────────────────────
    METRICS_WINDOW: int = 100  # последние N запросов для скользящего среднего

    # ── Sandbox ───────────────────────────────────────────────────────────────
    SANDBOX_TIMEOUT:    int = 30
    SANDBOX_MAX_RAM_MB: int = 256

    def load_json(self):
        """
        Загрузить переопределения из config.json.
        Позволяет менять порты без редактирования кода.
        """
        if not self.config_file.exists():
            return
        try:
            data = json.loads(self.config_file.read_text())
            for k, v in data.items():
                if hasattr(self, k):
                    setattr(self, k, v)
        except Exception as e:
            pass  # не критично

    @property
    def secret(self) -> str:
        """HMAC секрет из переменной окружения или дефолт"""
        return os.getenv(self.SECRET_ENV, "wishbridge_default_secret_change_me")


CONFIG = Config()
CONFIG.load_json()

# Создаём нужные директории
for _dir in [CONFIG.wb_root, CONFIG.engine_dir, CONFIG.memory_dir,
             CONFIG.log_dir, CONFIG.sandbox_dir]:
    _dir.mkdir(parents=True, exist_ok=True)


# ══════════════════════════════════════════════════════════════════════════════
# ИСКЛЮЧЕНИЯ
# ══════════════════════════════════════════════════════════════════════════════

class CactusError(Exception):
    """Ошибка движка Cactus — библиотека или модель"""
    pass

class ThermalError(Exception):
    """Инференс заблокирован из-за перегрева"""
    pass

class NetworkError(Exception):
    """Ошибка сетевого стека"""
    pass


# ══════════════════════════════════════════════════════════════════════════════
# ЛОГИРОВАНИЕ
# ══════════════════════════════════════════════════════════════════════════════

class _ColorFormatter(logging.Formatter):
    _C = {
        'DEBUG':    '\033[36m',
        'INFO':     '\033[32m',
        'WARNING':  '\033[33m',
        'ERROR':    '\033[31m',
        'CRITICAL': '\033[35m',
        'CACTUS':   '\033[96m',
        'THERMAL':  '\033[91m',
        'NETWORK':  '\033[34m',
        'SECURITY': '\033[93m',
    }
    _R = '\033[0m'

    def format(self, record):
        ctx = getattr(record, 'ctx', record.levelname)
        c = self._C.get(ctx, self._C.get(record.levelname, ''))
        record.ctx_str = f"{c}[{ctx}]{self._R}"
        return super().format(record)


_logger = logging.getLogger("WB")
_logger.setLevel(logging.DEBUG)
_logger.propagate = False

_ch = logging.StreamHandler(sys.stdout)
_ch.setLevel(logging.INFO)
_ch.setFormatter(_ColorFormatter('%(asctime)s | %(ctx_str)s %(message)s'))
_logger.addHandler(_ch)

_fh = logging.FileHandler(CONFIG.log_dir / "core_engine_v4.log")
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(logging.Formatter('%(asctime)s | [%(ctx)s] %(message)s'))
_logger.addHandler(_fh)


def log(msg: str, ctx: str = "INFO", level: str = "info"):
    r = _logger.makeRecord(
        _logger.name,
        getattr(logging, level.upper(), logging.INFO),
        "", 0, msg, (), None
    )
    r.ctx = ctx
    _logger.handle(r)


# ══════════════════════════════════════════════════════════════════════════════
# МЕТРИКИ  (thread-safe скользящее среднее)
# ══════════════════════════════════════════════════════════════════════════════

class Metrics:

    def __init__(self):
        self._lock = threading.Lock()
        self.lat  = deque(maxlen=CONFIG.METRICS_WINDOW)
        self.tps  = deque(maxlen=CONFIG.METRICS_WINDOW)
        self.total  = 0
        self.errors = 0

    def record(self, latency: float, tps: float = 0):
        with self._lock:
            self.total += 1
            self.lat.append(latency)
            if tps > 0:
                self.tps.append(tps)

    def error(self):
        with self._lock:
            self.total += 1
            self.errors += 1

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "total":      self.total,
                "errors":     self.errors,
                "error_rate": self.errors / self.total if self.total else 0,
                "avg_lat":    sum(self.lat) / len(self.lat) if self.lat else 0,
                "avg_tps":    sum(self.tps) / len(self.tps) if self.tps else 0,
            }


METRICS = Metrics()


# ══════════════════════════════════════════════════════════════════════════════
# THERMAL MANAGER  (синглтон, daemon thread)
# ══════════════════════════════════════════════════════════════════════════════

class Thermal:
    """
    Читает температуру из /sys/class/thermal/thermal_zoneN/temp.
    На Android обычно 10-15 зон — берём максимум.
    """

    def __init__(self):
        self.temp = 0.0
        self._lock = threading.Lock()
        self._running = False

    def start(self):
        self._running = True
        t = threading.Thread(target=self._loop, daemon=True)
        t.start()
        log(f"ThermalManager запущен (warn={CONFIG.THERMAL_WARN}°C "
            f"critical={CONFIG.THERMAL_CRITICAL}°C)", "THERMAL")

    def _read(self) -> float:
        temps = []
        for i in range(15):
            try:
                raw = Path(f"/sys/class/thermal/thermal_zone{i}/temp").read_text()
                t = int(raw.strip()) / 1000
                if 0 < t < 120:
                    temps.append(t)
            except:
                continue
        return max(temps) if temps else 0.0

    def _loop(self):
        while self._running:
            with self._lock:
                self.temp = self._read()
            time.sleep(CONFIG.THERMAL_INTERVAL)

    def can_run(self, heavy: bool = True) -> Tuple[bool, str]:
        with self._lock:
            t = self.temp
        if t >= CONFIG.THERMAL_CRITICAL:
            log(f"Инференс заблокирован: {t:.1f}°C (критично)", "THERMAL", "warning")
            return False, f"CRITICAL ({t:.1f}°C)"
        if heavy and t >= CONFIG.THERMAL_WARN:
            log(f"Инференс заблокирован: {t:.1f}°C (предупреждение)", "THERMAL", "warning")
            return False, f"WARNING ({t:.1f}°C)"
        return True, "OK"

    def stop(self):
        self._running = False


THERMAL = Thermal()


# ══════════════════════════════════════════════════════════════════════════════
# HARDWARE DETECTOR
# ══════════════════════════════════════════════════════════════════════════════

class DeviceType(Enum):
    HONOR_90   = "honor_90"
    POCO_X3PRO = "poco_x3_pro"
    POCO_F1    = "poco_f1"
    GENERIC    = "generic"

@dataclass
class DeviceProfile:
    name:         str
    device_type:  DeviceType
    threads:      int
    context_size: int
    thermal_warn: float
    ram_mb:       int

class Hardware:

    @staticmethod
    def detect() -> DeviceProfile:
        cpuinfo = Hardware._cpuinfo()
        hw  = cpuinfo.get("Hardware", "").lower()
        cpu = cpuinfo.get("Processor", "").lower()
        hst = socket.gethostname().lower()
        ram = Hardware._ram()

        if "sm7325" in hw or "snapdragon 7 gen 1" in cpu or "honor" in hst:
            return DeviceProfile("Atlas-Honor90",  DeviceType.HONOR_90,   4, 4096, 45.0, ram)
        if "sm8150" in hw or "snapdragon 860" in cpu or "x3" in hst:
            return DeviceProfile("Noah-PocoX3Pro", DeviceType.POCO_X3PRO, 4, 3072, 42.0, ram)
        if "sdm845" in hw or "snapdragon 845" in cpu or "f1" in hst:
            return DeviceProfile("Noema-PocoF1",   DeviceType.POCO_F1,    4, 2048, 42.0, ram)

        threads = 4 if ram > 6000 else 2
        return DeviceProfile(f"Generic-{ram}MB",  DeviceType.GENERIC,    threads, 2048, 40.0, ram)

    @staticmethod
    def _cpuinfo() -> Dict[str, str]:
        out = {}
        try:
            for line in open("/proc/cpuinfo"):
                if ":" in line:
                    k, v = line.split(":", 1)
                    out[k.strip()] = v.strip()
        except:
            pass
        return out

    @staticmethod
    def _ram() -> int:
        try:
            for line in open("/proc/meminfo"):
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
        except:
            pass
        return 4000


# ══════════════════════════════════════════════════════════════════════════════
# CACTUS ENGINE
#
# Что такое Cactus (выяснено через nm + эксперименты):
#
# libcactus_android.so — C++ движок с тремя plain-C функциями:
#
#   void* cactus_init(const char* model_dir, const char* rag_dir, bool verbose)
#     • model_dir — ПАПКА с .weights файлами и config.txt
#     • НЕ путь к .gguf файлу — именно папка
#     • возвращает handle (непрозрачный указатель) или NULL
#
#   int cactus_complete(void* handle,
#                       const char* messages_json,
#                       char* buf,          ← сюда запишется JSON-ответ
#                       int   buf_size,     ← ВАЖНО: c_int, не c_size_t!
#                       const char* options_json,
#                       const char* tools_json,  ← NULL если не нужно
#                       void* callback,          ← NULL
#                       void* userdata)          ← NULL
#     • messages_json — формат OpenAI: [{"role":"user","content":"..."}]
#     • buf после вызова содержит JSON: {"response":"...", "decode_tps":22.5}
#     • возвращает >= 0 при успехе, < 0 при ошибке
#
#   void cactus_destroy(void* handle)
#     • ВАЖНО: cactus_DESTROY, не cactus_free
#     • cactus_free в .so не существует — отсюда была ошибка undefined symbol
#
# ══════════════════════════════════════════════════════════════════════════════

class CactusEngine:
    """
    Thread-safe синглтон.
    Загружает .so один раз, держит handle модели, обслуживает параллельные запросы.
    """
    _instance: Optional['CactusEngine'] = None
    _new_lock = threading.Lock()

    def __new__(cls):
        if not cls._instance:
            with cls._new_lock:
                if not cls._instance:
                    obj = super().__new__(cls)
                    obj._ready = False
                    cls._instance = obj
        return cls._instance

    def __init__(self):
        if self._ready:
            return
        self._lock   = threading.RLock()
        self._lib    = None
        self._handle = None
        self._closed = False
        self._load_lib()
        self._ready  = True

    # ── Загрузка библиотеки ───────────────────────────────────────────────────

    def _load_lib(self):
        path = CONFIG.libcactus
        if not path.exists():
            raise CactusError(
                f"libcactus не найдена: {path}\n"
                f"Проверь симлинк: ln -sf ~/AI/libcactus_android.so {path}"
            )

        try:
            self._lib = ctypes.CDLL(str(path))
        except OSError as e:
            raise CactusError(f"Ошибка загрузки .so: {e}")

        # cactus_init: (model_dir, rag_dir, verbose) → handle
        self._lib.cactus_init.argtypes = [
            ctypes.c_char_p,   # model_dir — папка с весами
            ctypes.c_char_p,   # rag_dir   — папка для RAG (или None)
            ctypes.c_bool,     # verbose
        ]
        self._lib.cactus_init.restype = ctypes.c_void_p

        # cactus_complete: 8 аргументов
        self._lib.cactus_complete.argtypes = [
            ctypes.c_void_p,   # handle
            ctypes.c_char_p,   # messages JSON
            ctypes.c_char_p,   # output buffer
            ctypes.c_int,      # buffer size — ВАЖНО: c_int, не c_size_t
            ctypes.c_char_p,   # options JSON
            ctypes.c_char_p,   # tools JSON (None)
            ctypes.c_void_p,   # callback (None)
            ctypes.c_void_p,   # userdata (None)
        ]
        self._lib.cactus_complete.restype = ctypes.c_int

        # cactus_destroy — НЕ cactus_free
        self._lib.cactus_destroy.argtypes = [ctypes.c_void_p]
        self._lib.cactus_destroy.restype  = None

        sz = path.stat().st_size // 1024 // 1024
        log(f"Загружена {path.name} ({sz}MB)", "CACTUS")
        log("API: cactus_init / cactus_complete / cactus_destroy", "CACTUS")

    # ── Загрузка модели ───────────────────────────────────────────────────────

    def load_model(self, model_path: Optional[str] = None):
        """
        Загружает модель из папки.
        Если model_path не указан — берёт CONFIG.model (автовыбор по RAM).
        """
        path = Path(model_path) if model_path else CONFIG.model

        if not path.is_dir():
            raise CactusError(
                f"Папка модели не найдена: {path}\n"
                f"Cactus ожидает ПАПКУ с .weights файлами, не .gguf файл"
            )
        if not (path / "config.txt").exists():
            raise CactusError(
                f"config.txt не найден в {path}\n"
                f"Это не папка Cactus-модели"
            )

        with self._lock:
            if self._handle:
                self._lib.cactus_destroy(self._handle)
                self._handle = None

            log(f"Загружаю модель: {path.name} ...", "CACTUS")
            self._handle = self._lib.cactus_init(
                str(path).encode("utf-8"),
                None,   # rag_dir — не используем
                False,  # verbose — не нужен в production
            )

            if not self._handle:
                raise CactusError(
                    f"cactus_init вернул NULL для {path}\n"
                    f"Возможные причины: нехватка RAM, повреждённые файлы весов"
                )

            log(f"Модель загружена: {path.name}", "CACTUS")

    # ── Инференс ──────────────────────────────────────────────────────────────

    def infer(self,
              messages:     List[Dict],
              max_tokens:   int   = CONFIG.DEFAULT_MAX_TOKENS,
              temperature:  float = CONFIG.DEFAULT_TEMPERATURE,
              strip_think:  bool  = True) -> Tuple[str, float]:
        """
        Генерирует ответ.
        Возвращает: (текст, decode_tps)

        strip_think=True — убирает <think>...</think> из ответа.
        Qwen3 в режиме reasoning добавляет эти блоки — для агентов они не нужны.
        """
        if self._closed:
            raise CactusError("Engine закрыт")
        if not self._handle:
            raise CactusError("Модель не загружена — вызови load_model()")

        ok, reason = THERMAL.can_run(heavy=True)
        if not ok:
            raise ThermalError(reason)

        msgs_json = json.dumps(messages, ensure_ascii=False).encode("utf-8")
        opts_json = json.dumps({
            "max_tokens":  max_tokens,
            "temperature": temperature,
            "threads":     CONFIG.DEFAULT_THREADS,
        }).encode("utf-8")

        buf = ctypes.create_string_buffer(CONFIG.RESPONSE_BUF)

        with self._lock:
            t0  = time.time()
            ret = self._lib.cactus_complete(
                self._handle,
                msgs_json,
                buf,
                CONFIG.INFER_BUF,  # c_int — размер буфера
                opts_json,
                None, None, None,  # tools, callback, userdata
            )
            lat = time.time() - t0

        if ret < 0:
            METRICS.error()
            raise CactusError(f"cactus_complete вернул {ret}")

        # Ответ — JSON строка внутри буфера
        raw = buf.value.decode("utf-8", errors="ignore")
        try:
            data = json.loads(raw)
            text = data.get("response", "")
            tps  = float(data.get("decode_tps", 0))
        except (json.JSONDecodeError, ValueError):
            # Если вдруг не JSON — возвращаем как есть
            log(f"Ответ Cactus не JSON, возвращаем raw текст", "CACTUS", "warning")
            text = raw.strip()
            tps  = 0.0

        # Убираем блоки <think>...</think>
        if strip_think:
            text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

        METRICS.record(lat, tps)
        log(f"Инференс: {lat:.2f}s · {tps:.1f} tok/s", "CACTUS")
        return text, tps

    # ── Освобождение ──────────────────────────────────────────────────────────

    def close(self):
        with self._lock:
            if not self._closed:
                if self._handle and self._lib:
                    try:
                        self._lib.cactus_destroy(self._handle)
                        log("cactus_destroy OK", "CACTUS")
                    except Exception as e:
                        log(f"cactus_destroy ошибка: {e}", "CACTUS", "warning")
                self._handle = None
                self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


# ══════════════════════════════════════════════════════════════════════════════
# SCHEDULER  (очередь задач + воркеры)
# ══════════════════════════════════════════════════════════════════════════════

class Task:
    def __init__(self,
                 messages:    List[Dict],
                 max_tokens:  int = CONFIG.DEFAULT_MAX_TOKENS,
                 temperature: float = CONFIG.DEFAULT_TEMPERATURE,
                 callback:    Optional[Callable] = None):
        self.id          = secrets.token_hex(6)
        self.messages    = messages
        self.max_tokens  = max_tokens
        self.temperature = temperature
        self.callback    = callback
        self.created_at  = time.time()
        self.attempts    = 0


class Scheduler:
    """
    Принимает задачи, раздаёт воркерам.
    Воркеры проверяют температуру перед каждым инференсом.
    """

    def __init__(self, engine: CactusEngine):
        self._engine  = engine
        self._queue:  queue.Queue = queue.Queue(maxsize=CONFIG.QUEUE_SIZE)
        self._workers: List[threading.Thread] = []

    def start(self):
        for i in range(CONFIG.WORKERS):
            t = threading.Thread(
                target=self._worker_loop,
                name=f"wb-worker-{i}",
                daemon=True
            )
            t.start()
            self._workers.append(t)
        log(f"Scheduler запущен ({CONFIG.WORKERS} воркеров)", "INFO")

    def _worker_loop(self):
        while True:
            task: Task = self._queue.get()
            try:
                ok, reason = THERMAL.can_run(heavy=True)
                if not ok:
                    raise ThermalError(reason)

                text, tps = self._engine.infer(
                    task.messages,
                    task.max_tokens,
                    task.temperature,
                )
                if task.callback:
                    task.callback({"ok": True, "text": text, "tps": tps})

            except ThermalError as e:
                log(f"Task {task.id} заблокирован: {e}", "THERMAL", "warning")
                if task.callback:
                    task.callback({"ok": False, "error": f"ThermalBlock: {e}"})

            except Exception as e:
                METRICS.error()
                log(f"Task {task.id} ошибка: {e}", "CACTUS", "error")
                if task.callback:
                    task.callback({"ok": False, "error": str(e)})

            finally:
                self._queue.task_done()

    def submit(self, task: Task) -> bool:
        """Добавить задачу. Возвращает False если очередь переполнена."""
        try:
            self._queue.put_nowait(task)
            return True
        except queue.Full:
            log("Очередь переполнена — задача отброшена", "INFO", "warning")
            return False

    def submit_sync(self, messages: List[Dict],
                    max_tokens:  int   = CONFIG.DEFAULT_MAX_TOKENS,
                    temperature: float = CONFIG.DEFAULT_TEMPERATURE,
                    timeout:     float = 120.0) -> Tuple[str, float]:
        """
        Синхронная отправка — блокирует до получения ответа.
        Используется HTTP-сервером.
        """
        result: Dict = {}
        event = threading.Event()

        def cb(r: Dict):
            result.update(r)
            event.set()

        task = Task(messages, max_tokens, temperature, callback=cb)
        if not self.submit(task):
            raise RuntimeError("Очередь задач переполнена")

        if not event.wait(timeout=timeout):
            raise TimeoutError(f"Инференс не завершился за {timeout}с")

        if not result.get("ok"):
            raise CactusError(result.get("error", "Неизвестная ошибка"))

        return result["text"], result.get("tps", 0.0)


# ══════════════════════════════════════════════════════════════════════════════
# HTTP SERVER  (OpenAI-совместимый, тот же порт что ждёт aios_agent.py)
# ══════════════════════════════════════════════════════════════════════════════

class _Handler(BaseHTTPRequestHandler):

    sched: 'Scheduler' = None  # инжектируется при создании сервера
    profile: DeviceProfile = None

    def log_message(self, fmt, *args):
        pass  # не спамим в stdout на каждый запрос

    # GET /health — статус системы
    def do_GET(self):
        if self.path != "/health":
            self._send(404, {"error": "not found"})
            return

        m = METRICS.snapshot()
        self._send(200, {
            "status":  "ok",
            "device":  self.profile.name if self.profile else "unknown",
            "model":   CONFIG.model.name,
            "temp":    THERMAL.temp,
            "metrics": m,
        })

    # POST /v1/chat/completions — OpenAI API
    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self._send(404, {"error": "not found"})
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            body   = json.loads(self.rfile.read(length))
        except Exception as e:
            self._send(400, {"error": f"bad request: {e}"})
            return

        messages    = body.get("messages", [])
        max_tokens  = int(body.get("max_tokens",  CONFIG.DEFAULT_MAX_TOKENS))
        temperature = float(body.get("temperature", CONFIG.DEFAULT_TEMPERATURE))

        # Если нет системного промпта — добавляем дефолтный
        # /no_think — команда Qwen3 отключить режим рассуждений
        has_system = any(m.get("role") == "system" for m in messages)
        if not has_system:
            messages = [{
                "role":    "system",
                "content": "Ты Atlas — AI агент WishBridge. "
                           "Отвечай кратко и только по-русски. /no_think"
            }] + messages

        try:
            text, tps = self.sched.submit_sync(messages, max_tokens, temperature)
        except ThermalError as e:
            self._send(503, {"error": f"Thermal block: {e}"})
            return
        except Exception as e:
            self._send(500, {"error": str(e)})
            return

        self._send(200, {
            "choices": [{
                "message":       {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens":     0,
                "completion_tokens": max_tokens,
                "total_tokens":      max_tokens,
            },
            "decode_tps": tps,
        })

    def _send(self, code: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type",   "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class HttpServer:

    def __init__(self, scheduler: Scheduler, profile: DeviceProfile):
        _Handler.sched   = scheduler
        _Handler.profile = profile
        self._server = HTTPServer(("127.0.0.1", CONFIG.HTTP_PORT), _Handler)

    def start(self):
        log(f"HTTP API запущен: http://127.0.0.1:{CONFIG.HTTP_PORT}", "INFO")
        log(f"  GET  /health", "INFO")
        log(f"  POST /v1/chat/completions", "INFO")
        self._server.serve_forever()

    def stop(self):
        self._server.shutdown()


# ══════════════════════════════════════════════════════════════════════════════
# NETWORK STACK  (необязательный — UDP heartbeat + TCP задачи кластера)
#
# Необязательность важна: aios_agent.py уже работает на тех же портах.
# NetworkStack запускается только если порты свободны.
# Если занят — логируем предупреждение и продолжаем без сети.
# ══════════════════════════════════════════════════════════════════════════════

class Packet:
    """
    Формат: [4 bytes length][hmac_hex:compressed_json]
    serialize()   → bytes с length-prefix
    deserialize() → принимает raw[4:] — без length-prefix
    """

    def __init__(self, msg_type: str, payload: dict, seq: int = 0):
        self.type      = msg_type
        self.payload   = payload
        self.seq       = seq
        self.timestamp = time.time()

    def serialize(self, secret: str = "") -> bytes:
        data = {
            "t":  self.type,
            "p":  self.payload,
            "s":  self.seq,
            "ts": self.timestamp,
        }
        compressed = zlib.compress(
            json.dumps(data, ensure_ascii=False).encode(),
            level=CONFIG.COMPRESSION
        )
        if secret:
            sig = hmac.new(secret.encode(), compressed, hashlib.sha256).hexdigest()
            compressed = sig.encode() + b":" + compressed

        return struct.pack("!I", len(compressed)) + compressed

    @staticmethod
    def deserialize(data: bytes, secret: str = "") -> Optional['Packet']:
        """
        data — payload БЕЗ 4-байтового length-prefix.
        Если читаем из сокета: передавать raw[4:], не raw.split(b':',1)[1]
        """
        try:
            if secret:
                parts = data.split(b":", 1)
                if len(parts) != 2:
                    log("Неверный формат HMAC", "SECURITY", "warning")
                    return None
                sig, compressed = parts
                expected = hmac.new(
                    secret.encode(), compressed, hashlib.sha256
                ).hexdigest().encode()
                if not hmac.compare_digest(sig, expected):
                    log("HMAC не совпал — пакет отклонён", "SECURITY", "warning")
                    return None
            else:
                compressed = data

            obj = json.loads(zlib.decompress(compressed))
            p = Packet(obj["t"], obj["p"], obj.get("s", 0))
            p.timestamp = obj.get("ts", 0)
            return p
        except Exception as e:
            log(f"Ошибка разбора пакета: {e}", "NETWORK", "error")
            return None


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Соединение закрыто")
        buf += chunk
    return buf


class NetworkStack:
    """
    UDP broadcast — heartbeat каждые 10с (другие агенты видят нас).
    TCP listener — принимает задачи от других агентов кластера.

    Запускается только если порты свободны.
    """

    def __init__(self, profile: DeviceProfile, role: str = "worker"):
        self._profile = profile
        self._role    = role
        self._secret  = CONFIG.secret
        self._peers:  Dict[str, dict] = {}
        self._handlers: Dict[str, Callable] = {}
        self._running = False
        self._udp:    Optional[socket.socket] = None
        self._tcp:    Optional[socket.socket] = None

    def start(self) -> bool:
        """
        Запускает стек. Возвращает True если успешно, False если порты заняты.
        Не бросает исключение — сделано намеренно для совместимости с aios_agent.py
        """
        try:
            self._udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._udp.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self._udp.bind(("", CONFIG.DISCOVERY_PORT))
            self._udp.settimeout(1.0)
        except OSError as e:
            log(f"UDP порт {CONFIG.DISCOVERY_PORT} занят ({e}) — NetworkStack отключён",
                "NETWORK", "warning")
            return False

        try:
            self._tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._tcp.bind(("", CONFIG.TASK_PORT))
            self._tcp.listen(5)
            self._tcp.settimeout(1.0)
        except OSError as e:
            log(f"TCP порт {CONFIG.TASK_PORT} занят ({e}) — NetworkStack отключён",
                "NETWORK", "warning")
            self._udp.close()
            return False

        self._running = True
        threading.Thread(target=self._udp_loop,  daemon=True).start()
        threading.Thread(target=self._tcp_loop,  daemon=True).start()
        threading.Thread(target=self._heartbeat, daemon=True).start()

        log(f"NetworkStack запущен "
            f"(UDP:{CONFIG.DISCOVERY_PORT} TCP:{CONFIG.TASK_PORT})", "NETWORK")
        return True

    def _heartbeat(self):
        """Раз в 10с рассылаем UDP broadcast с нашим статусом"""
        while self._running:
            try:
                m = METRICS.snapshot()
                pkt = Packet("heartbeat", {
                    "device":  self._profile.name,
                    "role":    self._role,
                    "temp":    THERMAL.temp,
                    "metrics": m,
                })
                self._udp.sendto(
                    pkt.serialize(self._secret),
                    ("<broadcast>", CONFIG.DISCOVERY_PORT)
                )
            except Exception as e:
                log(f"Heartbeat ошибка: {e}", "NETWORK", "error")
            time.sleep(10)

    def _udp_loop(self):
        while self._running:
            try:
                data, addr = self._udp.recvfrom(8192)
                pkt = Packet.deserialize(data[4:], self._secret)
                if pkt and pkt.type in self._handlers:
                    self._handlers[pkt.type](addr[0], pkt.payload)
                elif pkt and pkt.type == "heartbeat":
                    self._peers[addr[0]] = {**pkt.payload, "seen": time.time()}
            except socket.timeout:
                continue
            except Exception as e:
                log(f"UDP ошибка: {e}", "NETWORK", "error")

    def _tcp_loop(self):
        while self._running:
            try:
                conn, addr = self._tcp.accept()
                threading.Thread(
                    target=self._handle_tcp,
                    args=(conn, addr),
                    daemon=True
                ).start()
            except socket.timeout:
                continue
            except Exception as e:
                log(f"TCP accept ошибка: {e}", "NETWORK", "error")

    def _handle_tcp(self, conn: socket.socket, addr: tuple):
        try:
            conn.settimeout(CONFIG.TCP_TIMEOUT)
            length = struct.unpack("!I", _recv_exact(conn, 4))[0]
            if length > CONFIG.MAX_PACKET_SIZE:
                log(f"Слишком большой пакет от {addr[0]}", "SECURITY", "warning")
                return
            data = _recv_exact(conn, length)
            pkt  = Packet.deserialize(data, self._secret)
            if pkt and pkt.type in self._handlers:
                resp = self._handlers[pkt.type](addr[0], pkt.payload)
                if resp:
                    r = Packet("response", resp)
                    conn.sendall(r.serialize(self._secret))
        except Exception as e:
            log(f"TCP handler ошибка: {e}", "NETWORK", "error")
        finally:
            conn.close()

    def register(self, msg_type: str, handler: Callable):
        """Зарегистрировать обработчик для типа сообщения"""
        self._handlers[msg_type] = handler

    def peers(self) -> Dict[str, dict]:
        """Список известных агентов кластера"""
        now = time.time()
        return {ip: p for ip, p in self._peers.items() if now - p["seen"] < 30}

    def stop(self):
        self._running = False
        for s in [self._udp, self._tcp]:
            if s:
                try:
                    s.close()
                except:
                    pass


# ══════════════════════════════════════════════════════════════════════════════
# SECURE SANDBOX  (AST whitelist для кода от агентов)
# ══════════════════════════════════════════════════════════════════════════════

class SecureSandbox:

    _ALLOWED = {
        ast.Module, ast.Interactive, ast.Expression,
        ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Return,
        ast.Delete, ast.Assign, ast.AugAssign, ast.AnnAssign,
        ast.For, ast.While, ast.If, ast.With, ast.Raise, ast.Try,
        ast.Assert, ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal,
        ast.Expr, ast.Pass, ast.Break, ast.Continue,
        ast.BoolOp, ast.BinOp, ast.UnaryOp, ast.Lambda, ast.IfExp,
        ast.Dict, ast.Set, ast.ListComp, ast.SetComp, ast.DictComp,
        ast.GeneratorExp, ast.Await, ast.Yield, ast.YieldFrom,
        ast.Compare, ast.Call, ast.FormattedValue, ast.JoinedStr,
        ast.Constant, ast.Attribute, ast.Subscript, ast.Starred,
        ast.Name, ast.List, ast.Tuple,
        ast.Load, ast.Store, ast.Del,
        ast.And, ast.Or, ast.Add, ast.Sub, ast.Mult, ast.Div,
        ast.FloorDiv, ast.Mod, ast.Pow, ast.LShift, ast.RShift,
        ast.BitOr, ast.BitXor, ast.BitAnd, ast.MatMult,
        ast.Invert, ast.Not, ast.UAdd, ast.USub,
        ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
        ast.Is, ast.IsNot, ast.In, ast.NotIn,
        ast.comprehension, ast.ExceptHandler, ast.arguments,
        ast.arg, ast.keyword, ast.alias, ast.withitem,
    }
    _FORBIDDEN_NAMES = {"__import__", "eval", "exec", "compile", "open", "input"}

    def __init__(self):
        self._counter = 0

    def validate(self, code: str) -> Tuple[bool, str]:
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return False, f"SyntaxError: {e}"

        for node in ast.walk(tree):
            if type(node) not in self._ALLOWED:
                return False, f"Запрещённая конструкция: {type(node).__name__}"
            if isinstance(node, ast.Name) and node.id in self._FORBIDDEN_NAMES:
                return False, f"Запрещённое имя: {node.id}"
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == "getattr":
                    return False, "getattr запрещён"
        return True, "OK"

    def run(self, code: str) -> Tuple[int, str, str]:
        ok, reason = self.validate(code)
        if not ok:
            return 1, "", f"Security: {reason}"

        self._counter += 1
        # Важно: не /tmp — на Android его нет. Используем sandbox_dir из config.
        script = CONFIG.sandbox_dir / f"sb_{self._counter}_{int(time.time())}.py"

        try:
            script.write_text(code, encoding="utf-8")

            def limits():
                try:
                    resource.setrlimit(resource.RLIMIT_AS,
                        (CONFIG.SANDBOX_MAX_RAM_MB * 1024 * 1024, -1))
                    resource.setrlimit(resource.RLIMIT_CPU,
                        (CONFIG.SANDBOX_TIMEOUT, CONFIG.SANDBOX_TIMEOUT + 5))
                    resource.setrlimit(resource.RLIMIT_NPROC, (50, 100))
                except:
                    pass

            r = subprocess.run(
                [sys.executable, str(script)],
                capture_output=True,
                text=True,
                timeout=CONFIG.SANDBOX_TIMEOUT,
                cwd=str(CONFIG.sandbox_dir),
                env={
                    "PYTHONPATH": "",
                    "PATH": "/system/bin:/data/data/com.termux/files/usr/bin",
                },
                preexec_fn=limits,
            )
            return r.returncode, r.stdout, r.stderr

        except subprocess.TimeoutExpired:
            return 1, "", "Timeout (бесконечный цикл?)"
        except Exception as e:
            return 1, "", f"Sandbox error: {e}"
        finally:
            script.unlink(missing_ok=True)


SANDBOX = SecureSandbox()


# ══════════════════════════════════════════════════════════════════════════════
# GRACEFUL SHUTDOWN
# ══════════════════════════════════════════════════════════════════════════════

_shutdown_handlers: List[Callable] = []

def on_shutdown(fn: Callable):
    """Зарегистрировать функцию для вызова при остановке"""
    _shutdown_handlers.append(fn)

def _handle_signal(sig, _):
    log(f"Сигнал {sig} — останавливаемся...", "INFO")
    for fn in _shutdown_handlers:
        try:
            fn()
        except:
            pass
    sys.exit(0)

signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT,  _handle_signal)


# ══════════════════════════════════════════════════════════════════════════════
# ЭКСПОРТ
# ══════════════════════════════════════════════════════════════════════════════

__all__ = [
    "CactusEngine", "Scheduler", "HttpServer", "NetworkStack",
    "Thermal", "THERMAL", "Hardware", "DeviceProfile", "DeviceType",
    "SecureSandbox", "SANDBOX", "Metrics", "METRICS",
    "Packet", "Config", "CONFIG",
    "Task", "log", "on_shutdown",
    "CactusError", "ThermalError", "NetworkError",
]


# ══════════════════════════════════════════════════════════════════════════════
# SELF-TEST  — честная проверка всех компонентов
# Запуск: python3 core_engine_v4.py
# Запуск как сервер: python3 core_engine_v4.py --serve
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":

    serve_mode = "--serve" in sys.argv

    print("╔══════════════════════════════════════════════════════════════╗")
    print("║         CORE ENGINE v4.0 'ATLAS' — Self-Test                 ║")
    print("╚══════════════════════════════════════════════════════════════╝\n")

    results: Dict[str, bool] = {}

    # ── 1. Конфигурация ───────────────────────────────────────────────────────
    print("[1/7] Configuration...")
    print(f"      libcactus : {CONFIG.libcactus}  exists={CONFIG.libcactus.exists()}")
    print(f"      model     : {CONFIG.model}  exists={CONFIG.model.is_dir()}")
    print(f"      http port : {CONFIG.HTTP_PORT}")
    print(f"      secret    : {'из env' if os.getenv(CONFIG.SECRET_ENV) else 'дефолт (смени!)'}")
    results["config"] = CONFIG.libcactus.exists()

    # ── 2. Hardware ───────────────────────────────────────────────────────────
    print("\n[2/7] Hardware Detection...")
    profile = Hardware.detect()
    print(f"      Device  : {profile.name}")
    print(f"      Type    : {profile.device_type.value}")
    print(f"      Threads : {profile.threads}")
    print(f"      RAM     : {profile.ram_mb}MB")
    print(f"      Context : {profile.context_size}")
    results["hardware"] = True

    # ── 3. Thermal ────────────────────────────────────────────────────────────
    print("\n[3/7] Thermal Manager...")
    THERMAL.start()
    time.sleep(1)
    ok, reason = THERMAL.can_run()
    print(f"      Temp       : {THERMAL.temp:.1f}°C")
    print(f"      Can run    : {ok} ({reason})")
    results["thermal"] = True  # тепловой менеджер всегда OK как компонент

    # ── 4. Cactus Engine ──────────────────────────────────────────────────────
    print("\n[4/7] Cactus Engine...")
    try:
        engine = CactusEngine()
        print(f"      .so загружена : OK")
        print(f"      cactus_init   : {engine._lib.cactus_init}")
        print(f"      cactus_complete: {engine._lib.cactus_complete}")
        print(f"      cactus_destroy: {engine._lib.cactus_destroy}")

        # Загрузка модели
        engine.load_model()
        print(f"      Модель загружена: {CONFIG.model.name}")
        results["cactus"] = True

    except CactusError as e:
        print(f"      FAIL: {e}")
        results["cactus"] = False

    # ── 5. Sandbox ────────────────────────────────────────────────────────────
    print("\n[5/7] Secure Sandbox...")
    ok1, _ = SANDBOX.validate("x = 2 + 2\nprint(x)")
    ok2, m = SANDBOX.validate("__import__('os').system('ls')")
    print(f"      Safe code OK     : {ok1}")
    print(f"      Bad code blocked : {not ok2}  ({m})")
    results["sandbox"] = ok1 and not ok2

    # ── 6. Network Packet + HMAC ──────────────────────────────────────────────
    print("\n[6/7] Network Packet + HMAC...")
    secret = "test_secret"
    pkt  = Packet("test", {"hello": "world"})
    raw  = pkt.serialize(secret)
    # raw[4:] — убираем length-prefix (4 байта), остальное передаём в deserialize
    rest = Packet.deserialize(raw[4:], secret)
    hmac_ok = rest is not None and rest.type == "test" and rest.payload == {"hello": "world"}
    print(f"      HMAC round-trip  : {'OK' if hmac_ok else 'FAIL'}")
    results["network_packet"] = hmac_ok

    # ── 7. NetworkStack (необязательный) ──────────────────────────────────────
    print("\n[7/7] NetworkStack (необязательный)...")
    if results.get("cactus"):
        net = NetworkStack(profile, role="worker")
        net_ok = net.start()
        if net_ok:
            print(f"      UDP/TCP запущены : OK")
            on_shutdown(net.stop)
        else:
            print(f"      Порты заняты — NetworkStack пропущен (это нормально)")
        results["network_stack"] = True  # необязательный компонент — всегда OK
    else:
        print("      Пропущено (Cactus не загружен)")
        results["network_stack"] = True

    # ── Итог ──────────────────────────────────────────────────────────────────
    critical = ["config", "hardware", "cactus", "sandbox", "network_packet"]
    failed   = [k for k in critical if not results.get(k)]

    print("\n╔══════════════════════════════════════════════════════════════╗")
    if not failed:
        print("║  ✅  Все компоненты OK  —  Engine v4.0 готов к работе        ║")
    else:
        print(f"║  ⚠️   Проблемы: {', '.join(failed):<44}║")
    print("╚══════════════════════════════════════════════════════════════╝")

    # ── Режим сервера ─────────────────────────────────────────────────────────
    if serve_mode and results.get("cactus"):
        print(f"\n🚀 Запуск HTTP сервера на порту {CONFIG.HTTP_PORT}...")
        sched = Scheduler(engine)
        sched.start()

        srv = HttpServer(sched, profile)
        on_shutdown(srv.stop)
        on_shutdown(engine.close)
        on_shutdown(THERMAL.stop)

        srv.start()  # блокирует

    elif serve_mode:
        print("\n❌ Сервер не запущен — Cactus Engine не инициализирован")
        sys.exit(1)

    else:
        THERMAL.stop()
        print("\nПодсказка: python3 core_engine_v4.py --serve  — запуск как сервер")
