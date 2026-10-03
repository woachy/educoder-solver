"""系统全局配置模块 (Global Configuration).

统一管理 CDP 端口、网络与评测超时、拟真延迟区间、日志输出与风控规则。
"""

import os
from dataclasses import dataclass, field
from typing import Tuple


@dataclass
class BrowserConfig:
    """浏览器与 CDP 连接配置"""
    host: str = field(default_factory=lambda: os.getenv("CDP_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(os.getenv("CDP_PORT", "9222")))
    target_domain: str = "educoder.net"
    connect_timeout_ms: int = 10000
    action_timeout_ms: int = 15000

    @property
    def cdp_url(self) -> str:
        """获取 CDP 连接 URL"""
        return f"http://{self.host}:{self.port}"


@dataclass
class DelayConfig:
    """拟真操作随机延迟配置 (单位: 秒)，遵循防风控行为规范"""
    click_delay: Tuple[float, float] = (0.5, 1.5)
    input_delay: Tuple[float, float] = (0.05, 0.2)
    step_delay: Tuple[float, float] = (1.0, 2.5)
    submit_delay: Tuple[float, float] = (1.5, 3.0)


@dataclass
class SafetyConfig:
    """风控与安全熔断配置"""
    max_consecutive_unchanged_errors: int = 3  # 连续报错无变化熔断阈值
    max_eval_retries_per_question: int = 5     # 单题最大评测重试次数
    min_task_duration: int = 60                # 单题最小作答耗时限制 (秒)，防止教师端审查秒刷


@dataclass
class LogConfig:
    """日志与输出格式配置"""
    level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper())
    json_mode: bool = field(default_factory=lambda: os.getenv("JSON_MODE", "false").lower() in ("true", "1", "yes"))


@dataclass
class AppConfig:
    """应用顶层总配置"""
    browser: BrowserConfig = field(default_factory=BrowserConfig)
    delay: DelayConfig = field(default_factory=DelayConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    log: LogConfig = field(default_factory=LogConfig)
    min_task_duration: int = 60  # 默认单题控速最小作答时长 (秒)


# 全局单例配置对象
config = AppConfig()
settings = config  # 别名
