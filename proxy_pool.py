# -*- coding: utf-8 -*-
"""代理池管理 — 支持 mihomo 多策略组轮换 + 健康检查。

兼容两种模式：
1. 单代理：直接用 config 里的 proxy 地址（向后兼容）
2. 代理池：从 config 里的 proxy_pool 列表轮换，每个注册用不同出口

mihomo 用户可以配多个策略组地址（同一 mihomo 实例不同端口/路径），
或多个 mihomo 实例实现 IP 轮换。
"""
import itertools
import time
import threading
from typing import Optional


class ProxyPool:
    """线程安全的代理轮换池。"""

    def __init__(self, proxy: str = "", proxy_pool: list = None,
                 health_check: bool = True, check_url: str = "https://api.mistral.ai/v1/models"):
        """
        Args:
            proxy: 单代理地址（向后兼容，proxy_pool 为空时用这个）
            proxy_pool: 代理地址列表（轮换使用）
            health_check: 是否启动时做健康检查
            check_url: 健康检查 URL
        """
        self._lock = threading.Lock()
        self._check_url = check_url
        
        if proxy_pool:
            self._proxies = list(proxy_pool)
        elif proxy:
            self._proxies = [proxy]
        else:
            self._proxies = []
        
        self._cycle = itertools.cycle(self._proxies) if self._proxies else None
        self._healthy = set(self._proxies)  # 初始全标记健康
        self._current_idx = 0
        
        if health_check and len(self._proxies) > 1:
            self._check_all()

    def _check_one(self, proxy: str) -> bool:
        """检查单个代理是否可用。"""
        import requests
        try:
            r = requests.get(self._check_url, 
                           proxies={"https": proxy, "http": proxy},
                           timeout=10)
            return r.status_code in (200, 401, 403)  # 401/403 说明代理通但需要 auth
        except Exception:
            return False

    def _check_all(self):
        """启动时检查所有代理。"""
        bad = []
        for p in self._proxies:
            if not self._check_one(p):
                bad.append(p)
                print(f"  [proxy] 不可用: {p}")
        with self._lock:
            self._healthy = set(self._proxies) - set(bad)
        if bad:
            print(f"  [proxy] {len(bad)}/{len(self._proxies)} 不可用，已剔除")
        if not self._healthy:
            print(f"  [proxy] ⚠️ 全部不可用，将使用全部代理（可能影响成功率）")
            self._healthy = set(self._proxies)

    def next(self) -> Optional[str]:
        """获取下一个健康代理（线程安全，轮换）。"""
        if not self._proxies:
            return None
        
        with self._lock:
            if not self._healthy:
                return self._proxies[0]
            
            # 从当前位置开始找下一个健康的
            for _ in range(len(self._proxies)):
                proxy = next(self._cycle)
                if proxy in self._healthy:
                    return proxy
            
            # 全不健康就返回第一个
            return self._proxies[0]

    def mark_bad(self, proxy: str):
        """标记代理为不健康（连接失败后调用）。"""
        with self._lock:
            self._healthy.discard(proxy)
            if not self._healthy:
                # 全不健康了，重置（可能只是临时网络问题）
                self._healthy = set(self._proxies)
                print(f"  [proxy] 全部标记不健康，重置池")

    def mark_good(self, proxy: str):
        """标记代理健康（成功后调用）。"""
        with self._lock:
            self._healthy.add(proxy)

    @property
    def count(self) -> int:
        return len(self._proxies)

    @property
    def healthy_count(self) -> int:
        with self._lock:
            return len(self._healthy)
