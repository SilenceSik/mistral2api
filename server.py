# -*- coding: utf-8 -*-
"""Mistral API 网关 — 多 key 轮询 + 429 冷却 + 流式 SSE + OpenAI 兼容。

启动后暴露 OpenAI 兼容 endpoint，客户端用任意 key（或配置的统一 key）访问，
网关自动轮询后端 Mistral API key 池，遇到 429 自动冷却切换下一个。

用法:
    python server.py --port 8082
    python server.py --port 8082 --api-keys sk-my-gateway-key --load-keys accounts_latest.txt
"""
import json
import time
import threading
import argparse
from datetime import datetime
from typing import Optional
from http.server import HTTPServer, BaseHTTPRequestHandler

import requests


class KeyPool:
    """线程安全的 API key 轮询池 + 429 冷却。"""

    def __init__(self, cooldown_seconds: int = 60):
        self._keys = []          # [{"key": "...", "cooldown_until": 0, "requests": 0, "errors": 0}]
        self._lock = threading.Lock()
        self._idx = 0
        self.cooldown = cooldown_seconds

    def add(self, key: str):
        with self._lock:
            if not any(k["key"] == key for k in self._keys):
                self._keys.append({"key": key, "cooldown_until": 0,
                                   "requests": 0, "errors": 0, "added_at": datetime.now().isoformat()})

    def remove(self, key: str):
        with self._lock:
            self._keys = [k for k in self._keys if k["key"] != key]

    def next(self) -> Optional[dict]:
        """获取下一个可用 key（跳过冷却中的）。"""
        with self._lock:
            if not self._keys:
                return None
            now = time.time()
            for _ in range(len(self._keys)):
                entry = self._keys[self._idx % len(self._keys)]
                self._idx += 1
                if entry["cooldown_until"] < now:
                    entry["requests"] += 1
                    return entry
            # 全部冷却中，返回最早冷却结束的
            earliest = min(self._keys, key=lambda k: k["cooldown_until"])
            earliest["requests"] += 1
            return earliest

    def mark_429(self, key: str):
        """标记 key 遇到 429，冷却。"""
        with self._lock:
            for k in self._keys:
                if k["key"] == key:
                    k["cooldown_until"] = time.time() + self.cooldown
                    k["errors"] += 1
                    break

    def mark_ok(self, key: str):
        """标记 key 请求成功。"""
        with self._lock:
            for k in self._keys:
                if k["key"] == key:
                    # 成功后重置冷却（可能之前是临时问题）
                    k["cooldown_until"] = 0
                    break

    def status(self) -> list:
        """返回所有 key 的状态。"""
        with self._lock:
            now = time.time()
            return [{**k, "cooling_down": k["cooldown_until"] > now,
                     "cooldown_remaining": max(0, int(k["cooldown_until"] - now))}
                    for k in self._keys]

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._keys)

    @property
    def available(self) -> int:
        now = time.time()
        with self._lock:
            return sum(1 for k in self._keys if k["cooldown_until"] < now)

    def load_from_file(self, path: str):
        """从 accounts_*.txt 加载 key（格式：email|key 每行一个）。"""
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and "|" in line:
                    _, key = line.split("|", 1)
                    self.add(key.strip())
                elif line and len(line) > 20:
                    self.add(line.strip())


MISTRAL_API = "https://api.mistral.ai/v1"
pool = KeyPool()
gateway_keys = []  # 网关自身的 API key（客户端用这个访问）


class GatewayHandler(BaseHTTPRequestHandler):
    """OpenAI 兼容 API 网关。"""

    def _send_json(self, code: int, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _check_auth(self) -> bool:
        """检查客户端的 API key。"""
        if not gateway_keys:
            return True  # 不设鉴权
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth[7:] in gateway_keys
        return False

    def _proxy_chat(self, body: dict, stream: bool):
        """代理 chat completions 请求到 Mistral API。"""
        if not self._check_auth():
            self._send_json(401, {"error": {"message": "Invalid API key", "type": "auth_error"}})
            return

        entry = pool.next()
        if not entry:
            self._send_json(503, {"error": {"message": "No API keys available", "type": "server_error"}})
            return

        key = entry["key"]
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

        try:
            if stream:
                resp = requests.post(f"{MISTRAL_API}/chat/completions",
                                    json={**body, "stream": True},
                                    headers=headers, timeout=120, stream=True)
            else:
                resp = requests.post(f"{MISTRAL_API}/chat/completions",
                                    json=body, headers=headers, timeout=120)

            if resp.status_code == 429:
                pool.mark_429(key)
                # 重试下一个 key
                self._proxy_chat(body, stream)
                return

            if resp.status_code != 200:
                pool.mark_429(key)
                self._send_json(resp.status_code, resp.json())
                return

            pool.mark_ok(key)

            if stream:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                for chunk in resp.iter_content(chunk_size=None):
                    if chunk:
                        self.wfile.write(chunk)
                        self.wfile.flush()
            else:
                self._send_json(200, resp.json())

        except requests.exceptions.ConnectionError:
            self._send_json(502, {"error": {"message": "Upstream connection error", "type": "server_error"}})
        except Exception as e:
            self._send_json(500, {"error": {"message": str(e), "type": "server_error"}})

    def do_GET(self):
        if self.path == "/v1/models" or self.path == "/models":
            if not self._check_auth():
                self._send_json(401, {"error": {"message": "Invalid API key"}})
                return
            # 返回 Mistral 可用模型
            entry = pool.next()
            if not entry:
                self._send_json(503, {"error": {"message": "No keys"}})
                return
            try:
                resp = requests.get(f"{MISTRAL_API}/models",
                                  headers={"Authorization": f"Bearer {entry['key']}"},
                                  timeout=30)
                self._send_json(200, resp.json())
            except Exception as e:
                self._send_json(500, {"error": {"message": str(e)}})

        elif self.path == "/health":
            self._send_json(200, {"status": "ok", "keys": pool.count,
                                  "available": pool.available,
                                  "timestamp": datetime.now().isoformat()})

        elif self.path == "/" or self.path == "":
            self._send_json(200, {"service": "mistral2api gateway",
                                  "version": "0.3.0",
                                  "endpoints": ["/v1/chat/completions", "/v1/models", "/health"]})

        elif self.path == "/admin/keys":
            self._send_json(200, {"keys": pool.status()})

        else:
            self._send_json(404, {"error": {"message": "Not found"}})

    def do_POST(self):
        if self.path == "/v1/chat/completions" or self.path == "/chat/completions":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            stream = body.get("stream", False)
            self._proxy_chat(body, stream)
        else:
            self._send_json(404, {"error": {"message": "Not found"}})

    def do_DELETE(self):
        if self.path.startswith("/admin/keys/"):
            key = self.path.split("/admin/keys/")[-1]
            pool.remove(key)
            self._send_json(200, {"removed": key})

    def log_message(self, format, *args):
        # 简化日志
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {args[0]}")


def main():
    parser = argparse.ArgumentParser(description="Mistral API 网关 — 多 key 轮询 + OpenAI 兼容")
    parser.add_argument("--port", type=int, default=8082, help="监听端口")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址")
    parser.add_argument("--api-keys", help="网关访问密钥（逗号分隔，留空则不鉴权）")
    parser.add_argument("--load-keys", help="从 accounts_*.txt 加载 key 文件")
    parser.add_argument("--cooldown", type=int, default=60, help="429 冷却秒数")
    parser.add_argument("--proxy", help="上游代理地址")
    args = parser.parse_args()

    global gateway_keys, pool
    pool = KeyPool(cooldown_seconds=args.cooldown)
    if args.api_keys:
        gateway_keys = [k.strip() for k in args.api_keys.split(",")]
    if args.load_keys:
        pool.load_from_file(args.load_keys)
        print(f"✅ 从 {args.load_keys} 加载了 {pool.count} 个 key")

    if args.proxy:
        import os
        os.environ["HTTP_PROXY"] = args.proxy
        os.environ["HTTPS_PROXY"] = args.proxy

    server = HTTPServer((args.host, args.port), GatewayHandler)
    print(f"🚀 mistral2api gateway 启动: http://{args.host}:{args.port}")
    print(f"   Key 池: {pool.count} 个 key, {pool.available} 可用")
    print(f"   鉴权: {'开启' if gateway_keys else '关闭'}")
    print(f"   端点: /v1/chat/completions, /v1/models, /health, /admin/keys")
    server.serve_forever()


if __name__ == "__main__":
    main()
