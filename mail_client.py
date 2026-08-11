# -*- coding: utf-8 -*-
"""临时邮箱客户端 — 兼容 cloudflare_temp_email API 契约。

邮箱格式参照 grok CPA 项目：
  {英文名}{6位hex}@{随机子域前缀}.{域名}

示例：
  aliceadams3ac7bc@my.example.xyz
  sarahwilson3ac849@r2.example.top
  patrickthomas3aca14@8q.example.xyz

英文名池：800+ 个常见英文名组合
子域前缀：2-3 位随机字母数字（每次随机，避免重复）
域名：从配置的域名列表中随机选
"""
import re
import time
import random
import string
import requests
from typing import Optional, Tuple, List


# 英文名池（参照 grok CPA 项目提取的常见组合）
FIRST_NAMES = [
    "alice", "bobby", "carol", "david", "emma", "frank", "grace", "henry",
    "ivan", "judy", "kevin", "linda", "mike", "nancy", "oliver", "peter",
    "rachel", "samuel", "tina", "victor", "wendy", "sarah", "patrick",
    "katherine", "william", "sophia", "edward", "james", "thomas", "rachel",
    "charles", "jennifer", "daniel", "lisa", "donald", "ashley", "paul",
    "kimberly", "george", "nicole", "kenneth", "stephanie", "steven",
    "dorothy", "edward", "joseph", "helen", "ronald", "sandra", "brian",
    "carol", "jason", "ruth", "jerry", "sharon", "justin", "michelle",
    "gary", "laura", "aaron", "emily", "randy", "deborah", "philip", "virginia",
    "harry", "maria", "vincent", "jacqueline", "jacob", "janet", "maria",
    "amber", "rebecca", "wyatt", "claire", "christian", "ann",
]
LAST_NAMES = [
    "adams", "allen", "baker", "carter", "clark", "green", "hall", "harris",
    "jackson", "king", "lewis", "martin", "miller", "moore", "nelson",
    "parker", "perez", "roberts", "turner", "walker", "young", "wilson",
    "thomas", "clark", "green", "lewis", "king", "nelson", "hall", "harris",
    "adams", "allen", "baker", "carter", "moore", "parker", "roberts",
    "turner", "walker", "young", "wilson", "martin", "miller",
]


def generate_email_name() -> str:
    """生成英文名+随机hex格式的邮箱前缀。

    格式: {firstname}{lastname}3ac{6位hex}
    示例: aliceadams3ac7bc, sarahwilson3ac849
    """
    first = random.choice(FIRST_NAMES)
    last = random.choice(LAST_NAMES)
    hex_part = "".join(random.choices("abcdef0123456789", k=6))
    return f"{first}{last}3ac{hex_part}"


def generate_subdomain_prefix() -> str:
    """生成 2-3 位随机子域前缀。

    示例: my, 7fi, r2, 8q, gx, 9dj, h3k
    """
    length = random.choice([2, 2, 2, 3])  # 2 位居多
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


class MailClient:
    """自建临时邮箱客户端（兼容 cloudflare_temp_email API）。

    支持两种模式：
    1. 旧模式：服务端自动分配邮箱地址（向后兼容）
    2. 新模式：客户端生成 {name}@{subdomain}.{domain} 格式地址，传给服务端
    """

    def __init__(self, api_base: str, domains: List[str] = None,
                 enable_custom_format: bool = True):
        """
        Args:
            api_base: 邮箱服务 API 地址
            domains: 域名列表（用于生成邮箱地址），为空则用旧模式
            enable_custom_format: 是否启用自定义邮箱格式
        """
        self.base = api_base.rstrip("/")
        self.domains = domains or []
        self.custom = enable_custom_format and bool(self.domains)

    def generate_address(self) -> str:
        """生成完整的邮箱地址。"""
        name = generate_email_name()
        prefix = generate_subdomain_prefix()
        domain = random.choice(self.domains)
        return f"{name}@{prefix}.{domain}"

    def create_address(self) -> Tuple[str, str]:
        """创建临时邮箱，返回 (email, jwt)。

        新模式：客户端生成地址，POST 时带 name + domain
        旧模式：服务端自动分配
        """
        if self.custom:
            name = generate_email_name()
            prefix = generate_subdomain_prefix()
            domain = random.choice(self.domains)
            address = f"{name}@{prefix}.{domain}"
            # 传完整地址给服务端（cloudflare_temp_email 支持 name 参数）
            r = requests.post(f"{self.base}/api/new_address",
                            json={"name": f"{name}@{prefix}.{domain}",
                                  "domain": domain},
                            timeout=15)
            if r.status_code == 200:
                d = r.json()
                return d["address"], d["jwt"]
            # 失败则 fallback 到旧模式
        # 旧模式：服务端自动分配
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
