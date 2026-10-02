"""拟真随机延迟工具 (Realistic Anti-Risk Delay Utility).

在关键操作（点击、输入、提交、页面切换）之间引入随机微延迟，
模拟人类真实操作行为，避免触发头歌平台的防高频/防刷脚本风控。
"""

import asyncio
import random
import time
from typing import Optional, Tuple, Union

from src.config import config


def get_random_duration(
    min_seconds: Optional[float] = None,
    max_seconds: Optional[float] = None,
    delay_range: Optional[Tuple[float, float]] = None,
) -> float:
    """计算随机延迟时间（秒）"""
    if delay_range is not None:
        low, high = delay_range
    elif min_seconds is not None and max_seconds is not None:
        low, high = min_seconds, max_seconds
    elif min_seconds is not None:
        low, high = min_seconds, max(min_seconds, config.delay.click_delay[1])
    else:
        low, high = config.delay.click_delay

    if low > high:
        low, high = high, low

    return random.uniform(low, high)


def random_delay(
    min_seconds: Optional[float] = None,
    max_seconds: Optional[float] = None,
    delay_range: Optional[Tuple[float, float]] = None,
) -> float:
    """同步阻塞随机延迟。

    Args:
        min_seconds: 最小等待秒数，默认使用 config.delay.click_delay[0] (0.5s)
        max_seconds: 最大等待秒数，默认使用 config.delay.click_delay[1] (1.5s)
        delay_range: 元组形式指定的 (min, max) 范围

    Returns:
        float: 实际睡眠等待的时长（秒）
    """
    duration = get_random_duration(min_seconds, max_seconds, delay_range)
    time.sleep(duration)
    return duration


async def async_random_delay(
    min_seconds: Optional[float] = None,
    max_seconds: Optional[float] = None,
    delay_range: Optional[Tuple[float, float]] = None,
) -> float:
    """异步非阻塞随机延迟 (配合 Playwright async API 使用)。

    Args:
        min_seconds: 最小等待秒数，默认 0.5s
        max_seconds: 最大等待秒数，默认 1.5s
        delay_range: 元组形式指定的 (min, max) 范围

    Returns:
        float: 实际睡眠等待的时长（秒）
    """
    duration = get_random_duration(min_seconds, max_seconds, delay_range)
    await asyncio.sleep(duration)
    return duration
