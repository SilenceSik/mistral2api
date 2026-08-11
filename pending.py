# -*- coding: utf-8 -*-
"""断联恢复 — pending 状态持久化 + 幂等恢复。

每个账号注册到关键步骤后写入 pending 文件，完成后清除。
如果中途中断（网络断、Ctrl+C、进程崩溃），下次启动时自动恢复未完成的注册。
"""
import json
import os
import time
from datetime import datetime
from typing import Optional


class PendingManager:
    """注册状态持久化 + 恢复。"""

    def __init__(self, pending_file: str = "pending.jsonl"):
        self.file = pending_file

    def save(self, email: str, step: str, data: dict):
        """保存/更新 pending 状态。

        Args:
            email: 邮箱（唯一 key）
            step: 当前步骤（registered / verified / logged_in / key_created）
            data: 附加数据（password, jwt, flow_id, key 等）
        """
        pending = self._load_all()
        entry = pending.get(email, {})
        entry.update({
            "email": email,
            "step": step,
            "updated_at": datetime.now().isoformat(),
            **data,
        })
        pending[email] = entry
        self._write_all(pending)

    def remove(self, email: str):
        """注册完成后清除 pending 记录。"""
        pending = self._load_all()
        pending.pop(email, None)
        self._write_all(pending)

    def get_pending(self) -> list:
        """返回所有未完成的注册记录。"""
        return list(self._load_all().values())

    def has_pending(self) -> bool:
        """是否有待恢复的记录。"""
        return bool(self._load_all())

    def _load_all(self) -> dict:
        if not os.path.exists(self.file):
            return {}
        try:
            with open(self.file, encoding="utf-8") as f:
                return {e["email"]: e for e in (json.loads(line) for line in f if line.strip())}
        except Exception:
            return {}

    def _write_all(self, pending: dict):
        with open(self.file, "w", encoding="utf-8") as f:
            for entry in pending.values():
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
