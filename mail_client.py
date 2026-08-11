# -*- coding: utf-8 -*-
"""临时邮箱客户端 — 兼容 cloudflare_temp_email API 契约。"""
import re
import time
import requests
from typing import Optional, Tuple


class MailClient:
    """自建临时邮箱客户端（兼容 cloudflare_temp_email API）。"""

    def __init__(self, api_base: str):
        self.base = api_base.rstrip("/")

    def create_address(self) -> Tuple[str, str]:
        """创建临时邮箱，返回 (email, jwt)。"""
        r = requests.post(f"{self.base}/api/new_address", timeout=15)
        r.raise_for_status()
        d = r.json()
        return d["address"], d["jwt"]

    def get_token(self, address: str) -> str:
        """用邮箱地址换取 JWT token。"""
        r = requests.post(f"{self.base}/api/token",
                         json={"address": address}, timeout=15)
        r.raise_for_status()
        return r.json().get("data", {}).get("token", r.json().get("jwt", ""))

    def list_messages(self, jwt: str) -> list:
        """列出收件箱邮件。"""
        r = requests.get(f"{self.base}/api/messages",
                        headers={"Authorization": f"Bearer {jwt}"}, timeout=15)
        r.raise_for_status()
        d = r.json()
        if isinstance(d, dict):
            return d.get("data", d.get("messages", []))
        return d

    def wait_for_code(self, jwt: str, flow_id: str,
                      max_wait: int = 6, interval: float = 8) -> Optional[str]:
        """等待验证邮件并提取验证码（匹配指定 flow_id）。"""
        for _ in range(max_wait):
            time.sleep(interval)
            mails = self.list_messages(jwt)
            for m in mails:
                body = m.get("text", m.get("html", m.get("body", "")))
                fm = re.search(r"flow=([a-f0-9-]+)", body)
                cm = re.search(r"code=(\d+)", body)
                if fm and cm and fm.group(1) == flow_id:
                    return cm.group(1)
        return None
