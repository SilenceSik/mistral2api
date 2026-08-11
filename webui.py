# -*- coding: utf-8 -*-
"""mistral2api WebUI — key 池状态 + 注册 + 测试 一体化管理界面。

单文件 HTML+JS，内嵌在 Python HTTP 服务里，通过调用 server.py 的 admin API 管理状态。
也支持直接启动注册器（调 register.py）。

用法:
    python webui.py --port 8083 --gateway http://localhost:8082
"""
import json
import subprocess
import sys
import os
import argparse
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# 注册器路径
REGISTER_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REGISTER_DIR)

HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>mistral2api · 管理面板</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, 'Segoe UI', sans-serif; background: #0f0f0f; color: #e0e0e0; }
.header { background: #1a1a2e; padding: 20px; border-bottom: 1px solid #333; }
.header h1 { font-size: 20px; color: #7c83ff; }
.header .sub { font-size: 12px; color: #666; margin-top: 4px; }
.container { max-width: 900px; margin: 20px auto; padding: 0 16px; }
.card { background: #1a1a2e; border-radius: 8px; padding: 16px; margin-bottom: 16px; border: 1px solid #2a2a3e; }
.card h2 { font-size: 14px; color: #aaa; margin-bottom: 12px; text-transform: uppercase; letter-spacing: 1px; }
.stats { display: flex; gap: 16px; flex-wrap: wrap; }
.stat { background: #22223a; border-radius: 6px; padding: 12px 20px; text-align: center; min-width: 100px; }
.stat .num { font-size: 24px; font-weight: bold; color: #7c83ff; }
.stat .label { font-size: 11px; color: #666; margin-top: 4px; }
table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: 8px 12px; border-bottom: 1px solid #2a2a3e; font-size: 13px; }
th { color: #888; font-weight: 500; }
td .key { font-family: monospace; color: #7c83ff; }
.badge { padding: 2px 8px; border-radius: 4px; font-size: 11px; }
.badge-ok { background: #1a3a1a; color: #4ade80; }
.badge-cool { background: #3a2a1a; color: #fbbf24; }
.badge-err { background: #3a1a1a; color: #f87171; }
.btn { padding: 8px 16px; border-radius: 6px; border: none; cursor: pointer; font-size: 13px; }
.btn-primary { background: #7c83ff; color: white; }
.btn-danger { background: #f87171; color: white; }
.btn-sm { padding: 4px 10px; font-size: 12px; }
.input { background: #22223a; border: 1px solid #333; border-radius: 6px; padding: 8px 12px; color: #e0e0e0; font-size: 13px; width: 100%; }
.row { display: flex; gap: 8px; margin-bottom: 12px; }
.row .input { flex: 1; }
.log { background: #0a0a0a; border-radius: 6px; padding: 12px; font-family: monospace; font-size: 12px; max-height: 300px; overflow-y: auto; white-space: pre-wrap; color: #4ade80; }
</style>
</head>
<body>
<div class="header">
    <h1>🚀 mistral2api 管理面板</h1>
    <div class="sub">v0.3.0 · <span id="gateway-url"></span></div>
</div>
<div class="container">
    <!-- 状态概览 -->
    <div class="card">
        <h2>状态概览</h2>
        <div class="stats" id="stats">
            <div class="stat"><div class="num" id="stat-total">-</div><div class="label">总 Key 数</div></div>
            <div class="stat"><div class="num" id="stat-avail">-</div><div class="label">可用</div></div>
            <div class="stat"><div class="num" id="stat-cool">-</div><div class="label">冷却中</div></div>
            <div class="stat"><div class="num" id="stat-req">-</div><div class="label">总请求</div></div>
            <div class="stat"><div class="num" id="stat-err">-</div><div class="label">总错误</div></div>
        </div>
    </div>

    <!-- Key 池 -->
    <div class="card">
        <h2>Key 池管理</h2>
        <div class="row">
            <input class="input" id="new-key" placeholder="粘贴 Mistral API Key (32字符)">
            <button class="btn btn-primary" onclick="addKey()">添加</button>
        </div>
        <table>
            <thead><tr><th>#</th><th>Key</th><th>状态</th><th>请求数</th><th>错误</th><th>冷却剩余</th><th>操作</th></tr></thead>
            <tbody id="key-table"></tbody>
        </table>
    </div>

    <!-- 批量注册 -->
    <div class="card">
        <h2>批量注册</h2>
        <div class="row">
            <input class="input" id="reg-count" type="number" value="5" min="1" max="50" style="max-width:80px">
            <input class="input" id="reg-workers" type="number" value="1" min="1" max="10" style="max-width:80px" placeholder="并发">
            <button class="btn btn-primary" onclick="startRegister()">开始注册</button>
            <button class="btn btn-danger" onclick="stopRegister()">停止</button>
        </div>
        <div class="log" id="reg-log">等待操作...</div>
    </div>

    <!-- 快速测试 -->
    <div class="card">
        <h2>API 测试</h2>
        <div class="row">
            <input class="input" id="test-model" value="mistral-small-latest" style="max-width:200px">
            <input class="input" id="test-prompt" value="Say OK" placeholder="测试消息">
            <button class="btn btn-primary" onclick="testApi()">测试</button>
        </div>
        <div class="log" id="test-result">...</div>
    </div>
</div>

<script>
const GATEWAY = location.origin.replace(/:\\\\d+$/, '') + ':__GATEWAY_PORT__';
document.getElementById('gateway-url').textContent = GATEWAY;

async function refreshKeys() {
    try {
        const r = await fetch(GATEWAY + '/admin/keys');
        const d = await r.json();
        const keys = d.keys || [];
        document.getElementById('stat-total').textContent = keys.length;
        document.getElementById('stat-avail').textContent = keys.filter(k => !k.cooling_down).length;
        document.getElementById('stat-cool').textContent = keys.filter(k => k.cooling_down).length;
        document.getElementById('stat-req').textContent = keys.reduce((s,k) => s + k.requests, 0);
        document.getElementById('stat-err').textContent = keys.reduce((s,k) => s + k.errors, 0);

        const tbody = document.getElementById('key-table');
        tbody.innerHTML = keys.map((k, i) => `
            <tr>
                <td>${i+1}</td>
                <td class="key">${k.key.substring(0,8)}...${k.key.substring(k.key.length-4)}</td>
                <td>${k.cooling_down
                    ? '<span class="badge badge-cool">冷却中</span>'
                    : '<span class="badge badge-ok">可用</span>'}</td>
                <td>${k.requests}</td>
                <td>${k.errors}</td>
                <td>${k.cooldown_remaining > 0 ? k.cooldown_remaining + 's' : '-'}</td>
                <td><button class="btn btn-danger btn-sm" onclick="delKey('${k.key}')">删除</button></td>
            </tr>`).join('');
    } catch(e) {
        console.error(e);
    }
}

async function addKey() {
    const key = document.getElementById('new-key').value.trim();
    if (!key) return;
    await fetch(GATEWAY + '/admin/keys', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({key})});
    document.getElementById('new-key').value = '';
    refreshKeys();
}

async function delKey(key) {
    await fetch(GATEWAY + '/admin/keys/' + key, {method: 'DELETE'});
    refreshKeys();
}

let regProcess = null;
async function startRegister() {
    const n = document.getElementById('reg-count').value;
    const w = document.getElementById('reg-workers').value;
    const log = document.getElementById('reg-log');
    log.textContent = '启动注册...\\n';
    try {
        const r = await fetch('/api/register', {method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({count: parseInt(n), workers: parseInt(w)})});
        const d = await r.json();
        if (d.task_id) {
            log.textContent += `任务 ${d.task_id} 已启动\\n`;
            pollLog(d.task_id);
        }
    } catch(e) {
        log.textContent += '错误: ' + e + '\\n';
    }
}

async function pollLog(taskId) {
    const log = document.getElementById('reg-log');
    const interval = setInterval(async () => {
        try {
            const r = await fetch('/api/register/' + taskId + '/status');
            const d = await r.json();
            if (d.log) log.textContent = d.log;
            if (d.done) {
                clearInterval(interval);
                log.textContent += '\\n✅ 注册完成\\n';
                refreshKeys();
            }
        } catch(e) { clearInterval(interval); }
    }, 3000);
}

async function testApi() {
    const model = document.getElementById('test-model').value;
    const prompt = document.getElementById('test-prompt').value;
    const result = document.getElementById('test-result');
    result.textContent = '请求中...';
    try {
        const r = await fetch(GATEWAY + '/v1/chat/completions', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({model, messages: [{role: 'user', content: prompt}], stream: false})
        });
        const d = await r.json();
        if (d.choices) result.textContent = '✅ ' + d.choices[0].message.content;
        else result.textContent = '❌ ' + JSON.stringify(d);
    } catch(e) {
        result.textContent = '❌ ' + e;
    }
}

refreshKeys();
setInterval(refreshKeys, 5000);
</script>
</body>
</html>"""


class TaskManager:
    """注册任务管理。"""
    def __init__(self):
        self._tasks = {}
        self._lock = threading.Lock()

    def start(self, count: int, workers: int) -> str:
        import uuid
        task_id = str(uuid.uuid4())[:8]
        with self._lock:
            self._tasks[task_id] = {"log": "", "done": False, "count": count}
        
        def run():
            try:
                cmd = [sys.executable, "register.py", "-n", str(count), "-w", str(workers)]
                proc = subprocess.Popen(cmd, cwd=REGISTER_DIR, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True, encoding="utf-8")
                for line in proc.stdout:
                    with self._lock:
                        self._tasks[task_id]["log"] += line
                proc.wait()
            except Exception as e:
                with self._lock:
                    self._tasks[task_id]["log"] += f"\n错误: {e}\n"
            finally:
                with self._lock:
                    self._tasks[task_id]["done"] = True
        
        threading.Thread(target=run, daemon=True).start()
        return task_id

    def status(self, task_id: str) -> dict:
        with self._lock:
            return self._tasks.get(task_id, {"log": "not found", "done": True})


tasks = TaskManager()


class WebUIHandler(BaseHTTPRequestHandler):
    def _send(self, code, data, content_type="application/json"):
        body = data.encode("utf-8") if isinstance(data, str) else json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        
        if parsed.path == "/" or parsed.path == "":
            html = HTML.replace("__GATEWAY_PORT__", str(self.server.gateway_port))
            self._send(200, html, "text/html")
        
        elif parsed.path.startswith("/api/register/") and parsed.path.endswith("/status"):
            task_id = parsed.path.split("/")[3]
            self._send(200, tasks.status(task_id))
        
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        
        if parsed.path == "/api/register":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            task_id = tasks.start(body.get("count", 1), body.get("workers", 1))
            self._send(200, {"task_id": task_id})
        
        elif parsed.path == "/admin/keys" and self.server.gateway_url:
            # 转发到 gateway
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                r = requests.post(f"{self.server.gateway_url}/admin/keys",
                                data=body, headers={"Content-Type": "application/json"}, timeout=10)
                self._send(r.status_code, r.text, "application/json")
            except Exception as e:
                self._send(502, {"error": str(e)})
        else:
            self._send(404, {"error": "not found"})

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/admin/keys/") and self.server.gateway_url:
            key = parsed.path.split("/admin/keys/")[-1]
            try:
                r = requests.delete(f"{self.server.gateway_url}/admin/keys/{key}", timeout=10)
                self._send(200, {"removed": key})
            except Exception as e:
                self._send(502, {"error": str(e)})
        else:
            self._send(404, {"error": "not found"})

    def log_message(self, format, *args):
        pass  # 静默


def main():
    parser = argparse.ArgumentParser(description="mistral2api WebUI 管理面板")
    parser.add_argument("--port", type=int, default=8083, help="WebUI 监听端口")
    parser.add_argument("--gateway", default="http://localhost:8082", help="网关地址")
    args = parser.parse_args()

    server = HTTPServer(("0.0.0.0", args.port), WebUIHandler)
    server.gateway_url = args.gateway
    server.gateway_port = urlparse(args.gateway).port or 8082
    
    print(f"🖥️  mistral2api WebUI: http://localhost:{args.port}")
    print(f"   网关地址: {args.gateway}")
    server.serve_forever()


if __name__ == "__main__":
    main()
