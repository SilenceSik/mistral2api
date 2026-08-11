# -*- coding: utf-8 -*-
"""主注册器 — 端到端：邮箱 → 注册 → 验证 → 登录 → 创建 key → 测试。"""
import json
import time
import argparse
from datetime import datetime
from typing import Optional

from mail_client import MailClient
from ory_auth import OryAuth
from mistral_api import MistralAPI


class MistralRegistrar:
    """端到端 Mistral 账号注册 + API key 创建。"""

    def __init__(self, mail_api: str = "http://localhost:8000",
                 proxy: str = "http://127.0.0.1:7890",
                 password: str = "ChangeMe123!"):
        self.mail = MailClient(mail_api)
        self.auth = OryAuth(proxy=proxy)
        self.proxy = proxy
        self.password = password

    def register_one(self) -> dict:
        """注册单个账号，返回结果 dict。"""
        result = {"email": "", "status": "unknown", "key": "", "error": ""}

        # 1. 创建邮箱
        email, jwt = self.mail.create_address()
        result["email"] = email
        print(f"  EMAIL: {email}")

        # 2. 注册
        identity = self.auth.register(email, self.password)
        if not (identity.get("identity") or identity.get("session")):
            result["status"] = "register_failed"
            result["error"] = "registration rejected"
            return result

        # 3. 发验证码 + 等待 + 验证
        vflow = self.auth.send_verification_code(email)
        code = self.mail.wait_for_code(jwt, vflow)
        if not code:
            result["status"] = "no_verification_email"
            result["error"] = "verification email not received"
            return result

        if not self.auth.verify_code(vflow, code):
            result["status"] = "verification_failed"
            result["error"] = "code verification rejected"
            return result
        print(f"  ✅ REGISTER + VERIFIED")

        # 4. 登录（新 session 避开 cookie 冲突）
        if not self.auth.login(email, self.password):
            result["status"] = "login_failed"
            result["error"] = "two-step login failed"
            return result
        print(f"  ✅ LOGIN")

        # 5. 创建 API key
        key = self.auth.create_api_key()
        if not key:
            result["status"] = "key_failed"
            result["error"] = "workspace not found or key creation rejected"
            return result
        result["key"] = key
        print(f"  ✅ KEY: {key[:12]}...")

        # 6. 测试 key
        api = MistralAPI(key, self.proxy)
        if api.test():
            result["status"] = "success"
            print(f"  ✅ API TEST: OK")
        else:
            result["status"] = "key_created_api_fail"
            print(f"  ⚠️ API TEST: key created but API test failed")

        return result

    def register_batch(self, count: int, delay: float = 2.0) -> list:
        """批量注册，返回结果列表。"""
        results = []
        for i in range(count):
            print(f"--- [{i+1}/{count}] {datetime.now().strftime('%H:%M:%S')} ---")
            try:
                result = self.register_one()
            except Exception as e:
                result = {"email": "?", "status": "exception",
                          "key": "", "error": str(e)}
                print(f"  ❌ EXCEPTION: {e}")
            results.append(result)
            if delay and i < count - 1:
                time.sleep(delay)

        # 汇总
        success = [r for r in results if r["status"] == "success"]
        print(f"\n{'='*50}")
        print(f"成功: {len(success)}/{count}")
        for r in results:
            k = r.get("key", "")[:16] + "..." if r.get("key") else ""
            print(f"  {r.get('email','?'):40s} {r['status']:25s} {k}")

        # 保存结果
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        outfile = f"accounts_{ts}.txt"
        with open(outfile, "w", encoding="utf-8") as f:
            for r in results:
                if r.get("key"):
                    f.write(f"{r['email']}|{r['key']}\n")
        print(f"\nKeys saved to {outfile}")
        return results


def load_config(path: str = "config.json") -> dict:
    """从 config.json 加载配置，不存在则用默认值。"""
    defaults = {
        "mail_api": "http://localhost:8000",
        "proxy": "http://127.0.0.1:7890",
        "password": "ChangeMe123!",
        "register_count": 1,
        "delay": 2.0,
        "key_name": "auto-bot",
        "first_name": "Bot",
        "last_name": "User",
    }
    try:
        with open(path, encoding="utf-8") as f:
            user = json.load(f)
        defaults.update(user)
    except FileNotFoundError:
        pass
    return defaults


def main():
    parser = argparse.ArgumentParser(description="Mistral 批量注册 + API key 创建")
    parser.add_argument("-n", "--count", type=int, help="注册数量（覆盖 config）")
    parser.add_argument("--mail-api", help="临时邮箱 API 地址（覆盖 config）")
    parser.add_argument("--proxy", help="HTTP 代理地址（覆盖 config）")
    parser.add_argument("--password", help="注册密码（覆盖 config）")
    parser.add_argument("--delay", type=float, help="批量间隔秒数（覆盖 config）")
    parser.add_argument("--config", default="config.json", help="配置文件路径")
    args = parser.parse_args()

    cfg = load_config(args.config)
    # CLI 参数覆盖 config
    count = args.count if args.count is not None else cfg["register_count"]
    delay = args.delay if args.delay is not None else cfg["delay"]

    registrar = MistralRegistrar(
        mail_api=args.mail_api or cfg["mail_api"],
        proxy=args.proxy or cfg["proxy"],
        password=args.password or cfg["password"],
    )
    registrar.register_batch(count, delay)


if __name__ == "__main__":
    main()
