# -*- coding: utf-8 -*-
"""Mistral API client — 原生 OpenAI 兼容 API 封装。"""
import requests
from typing import Optional


class MistralAPI:
    """Mistral 原生 API 客户端（OpenAI 兼容）。"""

    BASE = "https://api.mistral.ai/v1"

    def __init__(self, api_key: str, proxy: Optional[str] = None):
        self.key = api_key
        self.session = requests.Session()
        if proxy:
            self.session.proxies = {"https": proxy, "http": proxy}
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        })

    def list_models(self) -> list:
        r = self.session.get(f"{self.BASE}/models", timeout=30)
        r.raise_for_status()
        return [m["id"] for m in r.json().get("data", [])]

    def chat(self, model: str, messages: list, **kwargs) -> str:
        payload = {"model": model, "messages": messages, "stream": False, **kwargs}
        r = self.session.post(f"{self.BASE}/chat/completions", json=payload, timeout=120)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    def test(self) -> bool:
        """快速验证 key 是否可用。"""
        try:
            reply = self.chat("mistral-small-latest",
                              [{"role": "user", "content": "Say OK"}])
            return bool(reply)
        except Exception:
            return False
