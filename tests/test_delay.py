"""针对 src.utils.delay 的单元测试"""

import asyncio
import pytest
from src.utils.delay import async_random_delay, get_random_duration, random_delay


def test_get_random_duration_bounds():
    """测试计算出的延迟时间在给定的上下界内"""
    for _ in range(50):
        val = get_random_duration(0.1, 0.3)
        assert 0.1 <= val <= 0.3

    for _ in range(50):
        val = get_random_duration(delay_range=(0.5, 0.8))
        assert 0.5 <= val <= 0.8


def test_get_random_duration_reversed_order():
    """测试上下界倒序时能自动纠正"""
    for _ in range(20):
        val = get_random_duration(0.5, 0.2)
        assert 0.2 <= val <= 0.5


def test_random_delay_execution():
    """测试同步延迟实际执行时间（使用极小值以加速测试）"""
    duration = random_delay(0.05, 0.1)
    assert 0.05 <= duration <= 0.1


def test_async_random_delay_execution():
    """测试异步延迟实际执行时间（使用极小值以加速测试）"""
    duration = asyncio.run(async_random_delay(0.05, 0.1))
    assert 0.05 <= duration <= 0.1

