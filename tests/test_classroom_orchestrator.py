"""测试课堂大作业全自动巡航编排器 (Classroom Orchestrator Unit Tests)."""

from unittest.mock import MagicMock, call, patch
import pytest

from src.executor.classroom_orchestrator import (
    run_classroom_cruise,
    scan_classroom_tasks,
)


def test_scan_classroom_tasks_empty():
    assert scan_classroom_tasks(None) == []

    mock_page = MagicMock()
    mock_page.query_selector_all.return_value = []
    assert scan_classroom_tasks(mock_page) == []


def test_scan_classroom_tasks_with_cards():
    mock_page = MagicMock()

    # 模拟两个卡片：一个已完成，一个未完成
    card_completed = MagicMock()
    card_completed.inner_text.return_value = "任务一：建表操作 已完成 100分"
    title_el1 = MagicMock()
    title_el1.inner_text.return_value = "任务一：建表操作"
    card_completed.query_selector.side_effect = lambda sel: title_el1 if "title" in sel or "name" in sel else None

    card_pending = MagicMock()
    card_pending.inner_text.return_value = "任务二：索引优化 未完成 开始实训"
    title_el2 = MagicMock()
    title_el2.inner_text.return_value = "任务二：索引优化"
    btn_el = MagicMock()
    btn_el.is_visible.return_value = True

    def card_pending_qs(sel):
        if "title" in sel or "name" in sel:
            return title_el2
        if "开始实训" in sel:
            return btn_el
        return None

    card_pending.query_selector.side_effect = card_pending_qs

    mock_page.query_selector_all.return_value = [card_completed, card_pending]

    tasks = scan_classroom_tasks(mock_page)
    assert len(tasks) == 2

    assert tasks[0]["title"] == "任务一：建表操作"
    assert tasks[0]["is_completed"] is True
    assert tasks[0]["status"] == "已完成"

    assert tasks[1]["title"] == "任务二：索引优化"
    assert tasks[1]["is_completed"] is False
    assert tasks[1]["status"] == "未完成"
    assert tasks[1]["button"] == btn_el


def test_run_classroom_cruise_all_skipped():
    """当所有大题均已完成时，全部跳过"""
    mock_page = MagicMock()
    fake_tasks = [
        {"index": 0, "title": "任务一", "is_completed": True, "button": None},
        {"index": 1, "title": "任务二", "is_completed": True, "button": None},
    ]

    with patch("src.executor.classroom_orchestrator.scan_classroom_tasks", return_value=fake_tasks):
        report = run_classroom_cruise(mock_page, max_tasks=5, min_duration=0)

        assert report["status"] == "success"
        assert report["total_tasks_found"] == 2
        assert report["tasks_processed"] == 0
        assert report["tasks_skipped"] == 2
        assert report["tasks_completed"] == 0


def test_run_classroom_cruise_flow():
    """测试巡航编排完整流转：点击按钮开启新 Tab，完成关卡后安全关闭 Tab 并切回主页刷新"""
    mock_page = MagicMock()
    mock_context = MagicMock()
    mock_page.context = mock_context

    mock_btn = MagicMock()
    fake_tasks = [
        {"index": 0, "title": "实训大题A", "is_completed": False, "button": mock_btn},
    ]

    mock_task_page = MagicMock()
    mock_task_page.content.return_value = "<html><body><div class='shixun-left'><h3>任务描述</h3></div></body></html>"
    mock_task_page.url = "http://educoder.net/shixun/1"
    mock_page_info = MagicMock()
    mock_page_info.value = mock_task_page

    mock_context.expect_page.return_value.__enter__.return_value = mock_page_info
    mock_context.pages = [mock_page, mock_task_page]

    # 回调模拟单关通过
    fake_callback = MagicMock(return_value=True)

    with patch("src.executor.classroom_orchestrator.scan_classroom_tasks", return_value=fake_tasks), \
         patch("src.executor.classroom_orchestrator.dismiss_blocking_overlays"), \
         patch("src.executor.classroom_orchestrator.random_delay"):

        report = run_classroom_cruise(
            page=mock_page,
            max_tasks=1,
            min_duration=0,
            auto_next=True,
            solver_callback=fake_callback,
        )

        assert report["status"] == "success"
        assert report["tasks_completed"] == 1
        assert report["tasks_failed"] == 0
        assert len(report["details"]) == 1
        assert report["details"][0]["success"] is True

        # 验证新 Tab 安全关闭
        mock_task_page.close.assert_called_once()
        # 验证主页切回与刷新
        mock_page.bring_to_front.assert_called_once()
        mock_page.reload.assert_called_once()
