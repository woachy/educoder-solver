"""测试智能防刷控速器 (Pacing Controller Unit Tests)."""

import time
from unittest.mock import MagicMock, patch
import pytest

from src.executor.pacing import PacingController


def test_start_task_and_elapsed():
    controller = PacingController(default_min_duration=60)
    assert controller.get_elapsed_time("t1") == 0.0

    t0 = 1000.0
    times = [t0, t0 + 10.0]
    idx = [0]

    def fake_time():
        val = times[min(idx[0], len(times) - 1)]
        idx[0] += 1
        return val

    with patch("time.time", side_effect=fake_time):
        controller.start_task("t1")
        elapsed = controller.get_elapsed_time("t1")
        assert 9.9 <= elapsed <= 10.1


def test_wait_thinking_pacing_min_duration_zero():
    controller = PacingController()
    controller.start_task("quick_task")
    # min_duration <= 0 应该直接返回不进入等待
    res = controller.wait_thinking_pacing(min_duration=0, quiet=True, task_id="quick_task")
    assert res >= 0.0


def test_wait_thinking_pacing_already_satisfied():
    controller = PacingController()
    # 模拟过去已经消耗了 100 秒
    cur_time = 1000.0

    def fake_time():
        return cur_time

    with patch("time.time", side_effect=fake_time):
        controller.start_task("done_task")
        # 时间直接流逝了 100 秒
        cur_time = 1100.0
        elapsed = controller.wait_thinking_pacing(
            min_duration=60,
            jitter_range=(5, 10),
            quiet=True,
            task_id="done_task",
        )
        assert elapsed == 100.0


def test_wait_thinking_pacing_differential_wait():
    controller = PacingController()
    # 模拟开题已过 40 秒，min_duration 为 60 秒，jitter=(0, 0) -> target=60，还需等待 20 秒
    cur_time = [1000.0]

    def fake_time():
        return cur_time[0]

    mock_sleep = MagicMock()

    def fake_sleep(secs):
        cur_time[0] += secs

    mock_sleep.side_effect = fake_sleep

    with patch("time.time", side_effect=fake_time), patch("time.sleep", mock_sleep):
        controller.start_task("t_diff")
        cur_time[0] = 1040.0  # 已经过了 40 秒
        elapsed = controller.wait_thinking_pacing(
            min_duration=60,
            jitter_range=(0, 0),
            quiet=True,
            task_id="t_diff",
        )
        assert elapsed >= 60.0
        assert mock_sleep.called


def test_trigger_heartbeat():
    controller = PacingController()
    mock_page = MagicMock()
    mock_page.is_closed.return_value = False

    res = controller.trigger_heartbeat(mock_page)
    assert res is True
    mock_page.evaluate.assert_called_once()
    assert "scrollBy" in mock_page.evaluate.call_args[0][0]

    # 测试页面为 None 或关闭
    assert controller.trigger_heartbeat(None) is False
    mock_page.is_closed.return_value = True
    assert controller.trigger_heartbeat(mock_page) is False


def test_heartbeat_during_wait():
    controller = PacingController()
    mock_page = MagicMock()
    mock_page.is_closed.return_value = False

    cur_time = [1000.0]

    def fake_time():
        return cur_time[0]

    def fake_sleep(secs):
        # 每次 sleep 模拟步进 16 秒，以触发心跳
        cur_time[0] += 16.0

    mock_sleep = MagicMock(side_effect=fake_sleep)

    with patch("time.time", side_effect=fake_time), patch("time.sleep", mock_sleep):
        controller.start_task("t_heartbeat")
        controller.wait_thinking_pacing(
            page=mock_page,
            min_duration=30,
            jitter_range=(0, 0),
            quiet=True,
            task_id="t_heartbeat",
        )
        assert mock_page.evaluate.called
