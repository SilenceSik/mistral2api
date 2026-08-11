# -*- coding: utf-8 -*-
"""Ory Kratos 身份认证客户端 — Mistral 使用的身份系统。"""
import re
import requests
from typing import Optional


class OryAuth:
    """Ory Kratos 身份认证客户端（纯 API，无浏览器）。"""

    def __init__(self, base_url: str = "https://auth.mistral.ai",
                 proxy: Optional[str] = None):
        self.base = base_url.rstrip("/")
        self.session = requests.Session()
        if proxy:
            self.session.proxies = {"https": proxy, "http": proxy}
        self.session.headers.update({"Accept": "application/json"})

    @staticmethod
    def _get_csrf(flow_data: dict) -> str:
        for node in flow_data.get("ui", {}).get("nodes", []):
            if node["attributes"].get("name") == "csrf_token":
                return node["attributes"]["value"]
        return ""

    def init_registration(self) -> dict:
        """初始化注册 flow，返回 flow 数据。"""
        r = self.session.get(f"{self.base}/self-service/registration/browser")
        r.raise_for_status()
        return r.json()

    def register(self, email: str, password: str,
                 first_name: str = "Bot", last_name: str = "User") -> dict:
        """提交注册，返回 Ory identity。"""
        flow = self.init_registration()
        action = flow["ui"]["action"]
        csrf = self._get_csrf(flow)
        r = self.session.post(action, json={
            "method": "password",
            "csrf_token": csrf,
            "traits": {"email": email, "name": {"first": first_name, "last": last_name}},
            "password": password,
        }, headers={"Content-Type": "application/json"})
        return r.json()

    def send_verification_code(self, email: str) -> str:
        """触发验证码邮件，返回 verification flow_id。"""
        flow = self.session.get(f"{self.base}/self-service/verification/browser").json()
        action = flow["ui"]["action"]
        csrf = self._get_csrf(flow)
        self.session.post(action, json={
            "method": "code", "csrf_token": csrf, "email": email,
        }, headers={"Content-Type": "application/json"})
        return flow["id"]

    def verify_code(self, flow_id: str, code: str) -> bool:
        """提交验证码完成邮箱验证。"""
        rv = self.session.get(f"{self.base}/self-service/verification/flows?id={flow_id}")
        vd = rv.json()
        action = vd.get("ui", {}).get("action", "")
        csrf = self._get_csrf(vd)
        if not action:
            return False
        rv2 = self.session.post(action, json={
            "method": "code", "csrf_token": csrf, "code": code,
        }, headers={"Content-Type": "application/json"})
        return rv2.json().get("state") == "passed_challenge"

    def login(self, email: str, password: str) -> bool:
        """两步式登录（identifier_first → password），返回是否成功。

        注意：必须用新 session（不带注册 cookie）调 login，
        否则 Ory 会因 cookie 冲突返回非预期结果。
        """
        # 新 session 避免 cookie 冲突
        fresh = requests.Session()
        if self.session.proxies:
            fresh.proxies = self.session.proxies
        fresh.headers.update({"Accept": "application/json"})

        flow = fresh.get(f"{self.base}/self-service/login/browser").json()
        if "ui" not in flow:
            return False
        action = flow["ui"]["action"]
        csrf = self._get_csrf(flow)

        # step 1: identifier_first
        r1 = fresh.post(action, json={
            "method": "identifier_first", "csrf_token": csrf, "identifier": email,
        }, headers={"Content-Type": "application/json"})
        d1 = r1.json()
        if d1.get("session"):
            self.session = fresh
            return True
        if "ui" not in d1:
            return False

        # step 2: password
        action2 = d1["ui"].get("action", action)
        csrf2 = self._get_csrf(d1) or csrf
        r2 = fresh.post(action2, json={
            "method": "password", "csrf_token": csrf2,
            "identifier": email, "password": password,
        }, headers={"Content-Type": "application/json"})
        d2 = r2.json()
        if d2.get("session"):
            self.session = fresh
            return True
        return False

    def create_api_key(self, name: str = "auto-bot") -> Optional[str]:
        """登录后创建 API key，返回 key 字符串。"""
        # 从 console/api-keys 页面 RSC 数据提取 workspace UUID
        r = self.session.get("https://console.mistral.ai/api-keys",
                            headers={"Accept": "text/html"}, timeout=30)
        ws = None
        # RSC flight data 里的 workspace UUID
        for m in re.finditer(
            r'workspace[A-Za-z]*"[^"]*"([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})',
            r.text,
        ):
            ws = m.group(1)
            break
        if not ws:
            for m in re.finditer(r'"workspaceId":"([a-f0-9-]+)"', r.text):
                ws = m.group(1)
                break
        if not ws:
            for m in re.finditer(r'workspaces/([a-f0-9]{8}-[a-f0-9-]+)', r.text):
                ws = m.group(1)
                break
        if not ws:
            return None

        r2 = self.session.post(
            "https://admin.mistral.ai/api/billing/api-keys",
            json={"name": name, "workspace_uuid": ws,
                  "primitive_access_scope": "shared_only"},
            headers={"Content-Type": "application/json"}, timeout=30,
        )
        if r2.status_code == 200:
            return r2.json().get("key")
        return None
