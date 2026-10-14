"""测试课堂大作业全自动巡航编排器 (Classroom Orchestrator Unit Tests)."""

from unittest.mock import MagicMock, call, patch
import pytest

from src.executor.classroom_orchestrator import (
    list_classroom_tasks,
    open_classroom_task,
    run_classroom_cruise,
    scan_classroom_tasks,
    _read_stdin_with_timeout,
    penetrate_detail_springboard,
    cleanup_old_task_pages,
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


def test_run_classroom_cruise_interactive_mode():
    """测试 interactive=True 下 stdio JSON Lines 双向交互协议"""
    import io
    import json

    mock_page = MagicMock()
    mock_btn = MagicMock()
    fake_tasks = [
        {"index": 0, "title": "交互大题1", "is_completed": False, "button": mock_btn},
    ]

    mock_task_page = MagicMock()
    mock_task_page.content.return_value = "<html><body><div class='shixun-left'><h3>SQL实验</h3></div></body></html>"
    mock_task_page.url = "http://educoder.net/shixun/interactive"
    mock_task_page.query_selector.return_value = None

    mock_context = MagicMock()
    mock_page.context = mock_context
    mock_context.expect_page.return_value.__enter__.return_value = MagicMock(value=mock_task_page)
    mock_context.pages = [mock_page, mock_task_page]

    # 模拟 Agent 在 stdin 输入指令
    agent_action = json.dumps({"action": "solve", "code": "SELECT 1;", "target_only": True}) + "\n"
    fake_stdin = io.StringIO(agent_action)
    fake_stdout = io.StringIO()

    mock_solve_res = {
        "success": True,
        "passed": True,
        "pass_ratio": "1/1",
        "diff_hint": "通过",
        "circuit_broken": False,
    }

    with patch("src.executor.classroom_orchestrator.scan_classroom_tasks", return_value=fake_tasks), \
         patch("src.executor.classroom_orchestrator.dismiss_blocking_overlays"), \
         patch("src.executor.classroom_orchestrator.random_delay"), \
         patch("src.executor.classroom_orchestrator.run_solve_cycle", return_value=mock_solve_res) as mock_cycle, \
         patch("sys.stdin", fake_stdin), \
         patch("sys.stdout", fake_stdout):

        report = run_classroom_cruise(
            page=mock_page,
            max_tasks=1,
            min_duration=0,
            auto_next=True,
            interactive=True,
        )

        assert report["status"] == "success"
        assert report["tasks_completed"] == 1
        # 验证 run_solve_cycle 被调用且代码为 Agent 提供的 SELECT 1;
        mock_cycle.assert_called_once()
        assert mock_cycle.call_args[1]["code"] == "SELECT 1;"

        # 验证 stdout 中输出了 question_detected 与 eval_result 事件
        stdout_lines = [line.strip() for line in fake_stdout.getvalue().splitlines() if line.strip()]
        assert len(stdout_lines) >= 2
        ev1 = json.loads(stdout_lines[0])
        assert ev1["event"] == "question_detected"
        assert ev1["task_title"] == "交互大题1"
        ev2 = json.loads(stdout_lines[1])
        assert ev2["event"] == "eval_result"
        assert ev2["passed"] is True


def test_list_classroom_tasks():
    """测试 list_classroom_tasks 返回纯序列化字典列表"""
    mock_page = MagicMock()
    mock_btn = MagicMock()
    fake_tasks = [
        {"index": 0, "title": "任务A", "status": "已完成", "is_completed": True, "button": None, "raw_text": "textA"},
        {"index": 1, "title": "任务B", "status": "未完成", "is_completed": False, "button": mock_btn, "raw_text": "textB"},
    ]

    with patch("src.executor.classroom_orchestrator.scan_classroom_tasks", return_value=fake_tasks):
        res = list_classroom_tasks(mock_page)
        assert len(res) == 2
        assert res[0]["title"] == "任务A"
        assert res[0]["can_operate"] is False
        assert "button" not in res[0]

        assert res[1]["title"] == "任务B"
        assert res[1]["can_operate"] is True
        assert "button" not in res[1]


def test_open_classroom_task_empty():
    """测试页面未扫描到任务时的错误提示"""
    mock_page = MagicMock()
    with patch("src.executor.classroom_orchestrator.scan_classroom_tasks", return_value=[]):
        res = open_classroom_task(mock_page)
        assert res["status"] == "error"
        assert "未扫描到" in res["message"]


def test_open_classroom_task_all_completed():
    """测试所有任务已完成时的提示"""
    mock_page = MagicMock()
    fake_tasks = [
        {"index": 0, "title": "任务A", "is_completed": True, "button": None},
    ]
    with patch("src.executor.classroom_orchestrator.scan_classroom_tasks", return_value=fake_tasks):
        res = open_classroom_task(mock_page)
        assert res["status"] == "success"
        assert res["all_completed"] is True


def test_open_classroom_task_success():
    """测试成功开启大题并切换 Tab"""
    mock_page = MagicMock()
    mock_btn = MagicMock()
    fake_tasks = [
        {"index": 0, "title": "任务A", "is_completed": True, "button": None},
        {"index": 1, "title": "任务B", "is_completed": False, "button": mock_btn},
    ]

    mock_task_page = MagicMock()
    mock_task_page.url = "http://educoder.net/shixun/102"
    mock_context = MagicMock()
    mock_page.context = mock_context
    mock_context.expect_page.return_value.__enter__.return_value = MagicMock(value=mock_task_page)
    mock_context.pages = [mock_page, mock_task_page]

    mock_q = MagicMock()
    mock_q.title = "第1关：数据插入"
    mock_q.type.value = "practical"
    mock_q.metadata = {"db_dialect": "mysql", "language": "sql", "has_target_marker": True}

    with patch("src.executor.classroom_orchestrator.scan_classroom_tasks", return_value=fake_tasks), \
         patch("src.executor.classroom_orchestrator.dismiss_blocking_overlays"), \
         patch("src.executor.classroom_orchestrator.random_delay"), \
         patch("src.executor.classroom_orchestrator.extract_question", return_value=mock_q):

        res = open_classroom_task(mock_page)
        assert res["status"] == "success"
        assert res["task_index"] == 1
        assert res["task_title"] == "任务B"
        assert res["level_preview"]["title"] == "第1关：数据插入"
        mock_btn.click.assert_called_once()
        mock_task_page.bring_to_front.assert_called_once()


def test_run_classroom_cruise_dry_run():
    """测试 dry_run 演练模式仅扫描不点击"""
    mock_page = MagicMock()
    mock_btn = MagicMock()
    fake_tasks = [
        {"index": 0, "title": "任务1", "status": "已完成", "is_completed": True, "button": None},
        {"index": 1, "title": "任务2", "status": "未完成", "is_completed": False, "button": mock_btn},
    ]

    with patch("src.executor.classroom_orchestrator.scan_classroom_tasks", return_value=fake_tasks):
        report = run_classroom_cruise(mock_page, dry_run=True)
        assert report["status"] == "dry_run"
        assert report["total_tasks_found"] == 2
        assert len(report["pending_tasks"]) == 1
        assert report["pending_tasks"][0]["title"] == "任务2"
        mock_btn.click.assert_not_called()


def test_run_classroom_cruise_stdin_timeout():
    """测试 interactive 模式下等待输入超时安全退出，不造成进程假死"""
    import io
    import json

    mock_page = MagicMock()
    mock_btn = MagicMock()
    fake_tasks = [
        {"index": 0, "title": "超时大题", "is_completed": False, "button": mock_btn},
    ]

    mock_task_page = MagicMock()
    mock_task_page.content.return_value = "<html><body><div>任务</div></body></html>"
    mock_task_page.url = "http://educoder.net/shixun/timeout"

    mock_context = MagicMock()
    mock_page.context = mock_context
    mock_context.expect_page.return_value.__enter__.return_value = MagicMock(value=mock_task_page)
    mock_context.pages = [mock_page, mock_task_page]

    fake_stdout = io.StringIO()

    with patch("src.executor.classroom_orchestrator.scan_classroom_tasks", return_value=fake_tasks), \
         patch("src.executor.classroom_orchestrator.dismiss_blocking_overlays"), \
         patch("src.executor.classroom_orchestrator.random_delay"), \
         patch("src.executor.classroom_orchestrator._read_stdin_with_timeout", return_value=None), \
         patch("sys.stdout", fake_stdout):

        report = run_classroom_cruise(
            page=mock_page,
            max_tasks=1,
            interactive=True,
            stdin_timeout=0.01,
        )

        assert report["status"] == "success"
        assert report["tasks_failed"] == 1
        stdout_lines = [line.strip() for line in fake_stdout.getvalue().splitlines() if line.strip()]
        assert any("timeout" in l for l in stdout_lines)


def test_open_classroom_task_penetrate_detail_springboard_url():
    """测试打开大题后命中实训跳板详情页 (/detail)，自动穿透点击进入真正 IDE 页面"""
    mock_page = MagicMock()
    mock_task_btn = MagicMock()
    fake_tasks = [
        {"index": 0, "title": "实训大题-详情页跳板", "is_completed": False, "button": mock_task_btn},
    ]

    # 跳板详情页
    mock_springboard_page = MagicMock()
    mock_springboard_page.url = "https://www.educoder.net/shixuns/abc123xyz/detail?tabs=0"
    mock_inner_btn = MagicMock()
    mock_inner_btn.is_visible.return_value = True

    # 真正的 IDE 关卡页
    mock_real_ide_page = MagicMock()
    mock_real_ide_page.url = "https://www.educoder.net/tasks/abc123xyz"

    def springboard_qs(sel):
        if "继续挑战" in sel or "开始实训" in sel:
            return mock_inner_btn
        return None

    mock_springboard_page.query_selector.side_effect = springboard_qs

    mock_context = MagicMock()
    mock_page.context = mock_context

    # 第一次 expect_page 打开跳板详情页，第二次 expect_page 穿透到真正 IDE 关卡页
    mock_page_info_1 = MagicMock(value=mock_springboard_page)
    mock_page_info_2 = MagicMock(value=mock_real_ide_page)
    mock_context.expect_page.side_effect = [
        MagicMock(__enter__=MagicMock(return_value=mock_page_info_1), __exit__=MagicMock(return_value=None)),
        MagicMock(__enter__=MagicMock(return_value=mock_page_info_2), __exit__=MagicMock(return_value=None)),
    ]

    mock_q = MagicMock()
    mock_q.title = "第1关：跳板穿透验证"
    mock_q.type.value = "practical"
    mock_q.metadata = {"language": "python", "has_target_marker": True}

    with patch("src.executor.classroom_orchestrator.scan_classroom_tasks", return_value=fake_tasks), \
         patch("src.executor.classroom_orchestrator.dismiss_blocking_overlays"), \
         patch("src.executor.classroom_orchestrator.random_delay"), \
         patch("src.executor.classroom_orchestrator.extract_question", return_value=mock_q):

        res = open_classroom_task(mock_page, index=0)

        assert res["status"] == "success"
        assert res["task_url"] == "https://www.educoder.net/tasks/abc123xyz"
        assert res["level_preview"]["title"] == "第1关：跳板穿透验证"

        # 验证点击了卡片按钮与内层挑战按钮
        mock_task_btn.click.assert_called_once()
        mock_inner_btn.click.assert_called_once()
        # 验证旧跳板详情页被安全关闭
        mock_springboard_page.close.assert_called_once()
        # 验证新 IDE 页面被激活聚焦
        mock_real_ide_page.bring_to_front.assert_called_once()


def test_penetrate_detail_springboard_no_monaco():
    """测试页面缺乏 Monaco 编辑器且存在内层按钮时自动穿透"""
    mock_page = MagicMock()
    mock_page.url = "https://www.educoder.net/shixuns/test1"
    # evaluate 检测 monaco 返回 False
    mock_page.evaluate.return_value = False

    mock_inner_btn = MagicMock()
    mock_inner_btn.is_visible.return_value = True

    def page_qs(sel):
        if "monaco" in sel:
            return None
        if "开始实训" in sel:
            return mock_inner_btn
        return None

    mock_page.query_selector.side_effect = page_qs

    mock_new_tab = MagicMock()
    mock_new_tab.url = "https://www.educoder.net/tasks/test1"

    mock_context = MagicMock()
    mock_context.expect_page.return_value.__enter__.return_value = MagicMock(value=mock_new_tab)

    with patch("src.executor.classroom_orchestrator.dismiss_blocking_overlays"), \
         patch("src.executor.classroom_orchestrator.random_delay"):
        result_page = penetrate_detail_springboard(mock_page, context=mock_context)

        assert result_page == mock_new_tab
        mock_inner_btn.click.assert_called_once()
        mock_page.close.assert_called_once()


def test_penetrate_detail_springboard_not_triggered_for_real_ide():
    """测试如果已经是 Monaco 关卡 IDE 界面且 URL 无 /detail，则不触发穿透"""
    mock_page = MagicMock()
    mock_page.url = "https://www.educoder.net/tasks/real_ide"
    mock_page.evaluate.return_value = True  # has monaco

    mock_context = MagicMock()
    result_page = penetrate_detail_springboard(mock_page, context=mock_context)

    assert result_page == mock_page
    mock_context.expect_page.assert_not_called()


def test_open_classroom_task_cleans_up_old_task_pages():
    """测试 open_classroom_task 成功开启大题后，自动调用 cleanup_old_task_pages 回收旧 Tab"""
    mock_page = MagicMock()
    mock_btn = MagicMock()
    fake_tasks = [
        {"index": 0, "title": "任务A", "is_completed": False, "button": mock_btn},
    ]

    mock_task_page = MagicMock()
    mock_task_page.url = "http://educoder.net/tasks/102"
    mock_context = MagicMock()
    mock_page.context = mock_context
    mock_task_page.context = mock_context
    mock_context.expect_page.return_value.__enter__.return_value = MagicMock(value=mock_task_page)
    mock_context.pages = [mock_page, mock_task_page]

    mock_q = MagicMock()
    mock_q.title = "第1关"
    mock_q.type.value = "practical"
    mock_q.metadata = {}

    with patch("src.executor.classroom_orchestrator.scan_classroom_tasks", return_value=fake_tasks), \
         patch("src.executor.classroom_orchestrator.dismiss_blocking_overlays"), \
         patch("src.executor.classroom_orchestrator.random_delay"), \
         patch("src.executor.classroom_orchestrator.penetrate_detail_springboard", return_value=mock_task_page), \
         patch("src.executor.classroom_orchestrator.cleanup_old_task_pages", return_value=1) as mock_cleanup, \
         patch("src.executor.classroom_orchestrator.extract_question", return_value=mock_q):

        res = open_classroom_task(mock_page)
        assert res["status"] == "success"
        # 验证 cleanup_old_task_pages 被调用且入参为穿透后的 task_page
        mock_cleanup.assert_called_once_with(mock_task_page)


