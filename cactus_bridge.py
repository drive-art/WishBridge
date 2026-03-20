#!/usr/bin/env python3
"""
Cactus Bridge — замена llama-server для Noah
Запускает HTTP сервер на порту 8080 совместимый с OpenAI API
"""
import ctypes, json, threading, time
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

import subprocess
_last_tps = 0
_last_latency = 0

def get_system_info():
    try:
        mem = open("/proc/meminfo").read()
        ram_mb = int([l for l in mem.splitlines() if "MemAvailable" in l][0].split()[1]) // 1024
        temp = int(open("/sys/class/thermal/thermal_zone0/temp").read()) // 1000
        return f"{ram_mb}MB", f"{temp}C"
    except: return "?", "?"

LIB_PATH = str(Path.home() / "AI/libcactus_android.so")
MODEL_PATH = str(Path.home() / "AI/cactus-models/qwen3-0.6b-int4")

lib = ctypes.CDLL(LIB_PATH)
lib.cactus_init.restype = ctypes.c_void_p
lib.cactus_init.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_bool]
lib.cactus_complete.restype = ctypes.c_int
lib.cactus_complete.argtypes = [
    ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p,
    ctypes.c_int, ctypes.c_char_p, ctypes.c_char_p,
    ctypes.c_void_p, ctypes.c_void_p,
]
lib.cactus_destroy.argtypes = [ctypes.c_void_p]

print(f"Загружаю модель {MODEL_PATH}...")
handle = lib.cactus_init(MODEL_PATH.encode(), None, False)
if not handle:
    print("❌ Не удалось загрузить модель!")
    exit(1)
print(f"✅ Модель загружена!")

lock = threading.Lock()

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # тишина в логах

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            ram, temp = get_system_info()
            data = json.dumps({"status":"ok","active":active_requests,"tps":_last_tps,"ram":ram,"temp":temp}).encode()
            self.wfile.write(data)

    def do_POST(self):
        if self.path == "/v1/chat/completions":
            length = int(self.headers["Content-Length"])
            body = json.loads(self.rfile.read(length))
            messages = body.get("messages", [])
            # Добавляем /no_think если нет системного промпта
            has_system = any(m.get("role") == "system" for m in messages)
            if not has_system:
                messages = [{"role": "system", "content": "/no_think"}] + messages
            max_tokens = body.get("max_tokens", 512)

            options = json.dumps({"max_tokens": max_tokens})
            msgs_json = json.dumps(messages)
            buf = ctypes.create_string_buffer(524288)  # 512KB

            with lock:
                ret = lib.cactus_complete(
                    handle, msgs_json.encode(), buf, 131072,
                    options.encode(), None, None, None
                )

            if ret >= 0:
                r = json.loads(buf.value.decode())
                response_text = r.get("response", "")
                # Убираем <think>...</think> блоки
                import re
                response_text = re.sub(r'<think>.*?</think>', '', response_text, flags=re.DOTALL).strip()
                tps = r.get("decode_tps", 0)
            else:
                response_text = "Error"
                tps = 0

            result = {
                "choices": [{
                    "message": {"role": "assistant", "content": response_text},
                    "finish_reason": "stop"
                }],
                "usage": {"completion_tokens": max_tokens, "prompt_tokens": 0, "total_tokens": max_tokens},
                "decode_tps": tps
            }
            data = json.dumps(result).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", len(data))
            self.end_headers()
            self.wfile.write(data)

print("🚀 Cactus Bridge запущен на порту 8080")
server = HTTPServer(("127.0.0.1", 8080), Handler)
server.serve_forever()
