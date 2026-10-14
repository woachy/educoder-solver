"""智能防刷控速跨进程状态持久化与流水线打卡集成单元测试 (Pacing Persistence & Pipeline Tests).

覆盖:
1. 规范化 task_id (_normalize_task_id: 支持 educoder 完整 URL, 查询参数, 相对路径等).
2. 跨进程打卡与持久化 (.cache/pacing_state.json 原子读写与多实例数据共享).
3. 跨进程时间差额补足计算 (已耗时扣除与差额等待，杜绝重复等满整段).
4. 超过 2 小时过期记录自动过滤与清理.
5. 通关清理 clear_task (内存及磁盘双清，支持 URL 与规范化 Path 双向清理).
6. 复合流水线 run_solve_cycle 集成:
   - 自动回退 page.url 为 effective_task_id.
   - 评测全绿 (passed=True) 自动调用 clear_task 清理打卡缓存.
   - 评测未通过时保留打卡记录.
   - inject_res 中 saved 与 commit_id 字段透传.
7. CLI dump-question 与 open-task 的打卡集成.
"""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from src.executor.eval_action import EvaluationManager
from src.executor.pacing import PacingController, pacing_controller
from src.executor.pipeline import run_solve_cycle
from src.extractor.base import PracticalDetails, QuestionData, QuestionType


class TestNormalizeTaskId:
    """测试 task_id 规范化提取机制"""

    def test_normalize_full_educoder_url(self):
        url = "https://www.educoder.net/tasks/12345"
        assert PacingController._normalize_task_id(url) == "/tasks/12345"

    def test_normalize_url_with_subdomain_and_query(self):
        url = "https://data.educoder.net/tasks/shixun_101/sub_task?tab=1&retry=true#editor"
        assert PacingController._normalize_task_id(url) == "/tasks/shixun_101/sub_task"

    def test_normalize_url_trailing_slash(self):
        url = "https://www.educoder.net/tasks/12345/"
        assert PacingController._normalize_task_id(url) == "/tasks/12345"

    def test_normalize_relative_path_with_query(self):
        path = "/tasks/shixun_202?keyword=test"
        assert PacingController._normalize_task_id(path) == "/tasks/shixun_202"

    def test_normalize_clean_relative_path(self):
        path = "/tasks/12345"
        assert PacingController._normalize_task_id(path) == "/tasks/12345"

    def test_normalize_arbitrary_string(self):
        assert PacingController._normalize_task_id("custom_task_id_001") == "custom_task_id_001"

    def test_normalize_none_and_empty(self):
        assert PacingController._normalize_task_id(None) is None
        assert PacingController._normalize_task_id("") is None
        assert PacingController._normalize_task_id("   ") is None


class TestCrossProcessPersistence:
    """测试跨进程持久化与状态共享"""

    def test_start_task_writes_to_cache_file(self, tmp_path):
        cache_file = tmp_path / "pacing_state.json"
        controller = PacingController(cache_file=cache_file)

        task_url = "https://www.educoder.net/tasks/999"
        t0 = controller.start_task(task_url)

        assert cache_file.exists()
        with open(cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 同时记录原始 key 和规范化后的 path key
        assert task_url in data
        assert "/tasks/999" in data
        assert data[task_url] == t0
        assert data["/tasks/999"] == t0

    def test_cross_process_state_restore_and_elapsed(self, tmp_path):
        cache_file = tmp_path / "pacing_state.json"

        # 模拟第一个进程 (如 open-task) 打卡
        proc1 = PacingController(cache_file=cache_file)
        task_url = "https://www.educoder.net/tasks/888"

        cur_time = [1000.0]
        with patch("time.time", side_effect=lambda: cur_time[0]):
            proc1.start_task(task_url)

        # 模拟第二个全新进程 (如 solve-cycle 启动，内存为空)
        proc2 = PacingController(cache_file=cache_file)
        assert proc2._task_start_times == {}

        # 经过 20 秒后在进程 2 查询
        cur_time[0] = 1020.0
        with patch("time.time", side_effect=lambda: cur_time[0]):
            # 通过原始 URL 查询
            elapsed_raw = proc2.get_elapsed_time(task_url)
            assert 19.9 <= elapsed_raw <= 20.1

            # 通过规范化 Path 查询同样能命中
            elapsed_norm = proc2.get_elapsed_time("/tasks/888")
            assert 19.9 <= elapsed_norm <= 20.1

            # 且已经同步恢复至进程 2 内存
            assert task_url in proc2._task_start_times

    def test_cross_process_differential_wait(self, tmp_path):
        cache_file = tmp_path / "pacing_state.json"
        task_url = "https://www.educoder.net/tasks/diff_test"

        # 进程 1 记录开题打卡 (t = 1000.0)
        cur_time = [1000.0]
        with patch("time.time", side_effect=lambda: cur_time[0]):
            p1 = PacingController(cache_file=cache_file)
            p1.start_task(task_url)

        # 进程 2 在 40 秒后执行 solve-cycle (t = 1040.0)
        cur_time[0] = 1040.0
        p2 = PacingController(cache_file=cache_file)

        mock_sleep = MagicMock()
        def fake_sleep(secs):
            cur_time[0] += secs
        mock_sleep.side_effect = fake_sleep

        with patch("time.time", side_effect=lambda: cur_time[0]), patch("time.sleep", mock_sleep):
            # min_duration 为 60s, 抖动固定为 0, 目标总耗时 60s
            # 已经过了 40s，仅需补足 20s，绝不死等完整 60s
            total_elapsed = p2.wait_thinking_pacing(
                page=None,
                min_duration=60,
                jitter_range=(0, 0),
                quiet=True,
                task_id=task_url,
            )

            assert total_elapsed >= 60.0
            total_slept = sum(c.args[0] for c in mock_sleep.call_args_list)
            # 补齐差额约为 20 秒 (允许浮点误差)
            assert 19.0 <= total_slept <= 21.0

    def test_cache_expiration_filter(self, tmp_path):
        cache_file = tmp_path / "pacing_state.json"
        controller = PacingController(cache_file=cache_file)
        task_url = "https://www.educoder.net/tasks/expired_task"

        cur_time = [1000.0]
        with patch("time.time", side_effect=lambda: cur_time[0]):
            controller.start_task(task_url)

        # 模拟时间流逝超过 2 小时 (7200 秒 + 10 秒 = 7210 秒)
        cur_time[0] = 1000.0 + 7210.0

        with patch("time.time", side_effect=lambda: cur_time[0]):
            # 内存中的记录应该判定过期，返回 0.0 并清除
            elapsed = controller.get_elapsed_time(task_url)
            assert elapsed == 0.0

            # 跨进程独立实例读取时，同样过滤超过 2 小时的过期记录
            other_proc = PacingController(cache_file=cache_file)
            assert other_proc.get_elapsed_time(task_url) == 0.0
            assert other_proc._load_cache() == {}

    def test_clear_task_removes_from_memory_and_disk(self, tmp_path):
        cache_file = tmp_path / "pacing_state.json"
        controller = PacingController(cache_file=cache_file)
        task_url = "https://www.educoder.net/tasks/clear_me"

        controller.start_task(task_url)
        assert controller.get_elapsed_time(task_url) > 0.0

        # 执行清理
        controller.clear_task(task_url)

        # 内存中已被清理
        assert task_url not in controller._task_start_times
        assert "/tasks/clear_me" not in controller._task_start_times
        assert controller.get_elapsed_time(task_url) == 0.0

        # 磁盘缓存中同样已被清理
        with open(cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert task_url not in data
        assert "/tasks/clear_me" not in data

    def test_clear_task_by_normalized_path(self, tmp_path):
        cache_file = tmp_path / "pacing_state.json"
        controller = PacingController(cache_file=cache_file)
        task_url = "https://www.educoder.net/tasks/dual_clear"

        controller.start_task(task_url)

        # 传入 normalized path 执行清理
        controller.clear_task("/tasks/dual_clear")

        assert controller.get_elapsed_time(task_url) == 0.0
        assert controller.get_elapsed_time("/tasks/dual_clear") == 0.0


class TestPipelinePacingIntegration:
    """测试复合流水线 run_solve_cycle 与打卡/清理的深度集成"""

    def test_pipeline_fallback_to_page_url_and_clear_on_passed(self, tmp_path):
        cache_file = tmp_path / "pacing_state.json"
        test_controller = PacingController(cache_file=cache_file)

        mock_page = MagicMock()
        page_url = "https://www.educoder.net/tasks/level_1"
        mock_page.url = page_url

        mock_eval_mgr = MagicMock(spec=EvaluationManager)

        fake_inject_res = {
            "success": True,
            "method_used": "monaco_fiber",
            "backup_path": "/cache/b.py",
            "is_target_assembled": True,
            "saved": True,
            "commit_id": "commit_abc123",
            "message": "注入成功",
        }
        fake_eval_res = {
            "success": True,
            "passed": True,
            "pass_ratio": "1/1",
            "diff_hint": "全部通过",
            "message": "评测成功",
        }
        mock_eval_mgr.trigger_and_wait_eval.return_value = fake_eval_res

        # 事先打卡
        test_controller.start_task(page_url)
        assert test_controller.get_elapsed_time(page_url) >= 0.0

        with patch("src.executor.pipeline.pacing_controller", test_controller), \
             patch("src.executor.pipeline.dismiss_blocking_overlays", return_value=0), \
             patch("src.executor.pipeline.inject_code", return_value=fake_inject_res):

            # task_id 传 None，验证自动提取 page.url 并于通关后清理
            result = run_solve_cycle(
                page=mock_page,
                code="print('ok')",
                min_duration=0,
                eval_manager=mock_eval_mgr,
                task_id=None,
            )

            assert result["passed"] is True
            # 通关后打卡记录被清理
            assert test_controller.get_elapsed_time(page_url) == 0.0

            # 验证 injection 透传了 saved 与 commit_id
            assert result["injection"]["saved"] is True
            assert result["injection"]["commit_id"] == "commit_abc123"

    def test_pipeline_retains_pacing_state_when_eval_failed(self, tmp_path):
        cache_file = tmp_path / "pacing_state.json"
        test_controller = PacingController(cache_file=cache_file)

        mock_page = MagicMock()
        page_url = "https://www.educoder.net/tasks/level_failed"
        mock_page.url = page_url

        mock_eval_mgr = MagicMock(spec=EvaluationManager)

        fake_inject_res = {
            "success": True,
            "method_used": "monaco_api",
            "backup_path": "/cache/b.py",
            "is_target_assembled": False,
            "saved": False,
            "commit_id": "",
        }
        fake_eval_res = {
            "success": True,
            "passed": False,
            "pass_ratio": "0/1",
            "diff_hint": "AssertionError",
            "message": "评测未通过",
        }
        mock_eval_mgr.trigger_and_wait_eval.return_value = fake_eval_res

        # 打卡
        test_controller.start_task(page_url)

        with patch("src.executor.pipeline.pacing_controller", test_controller), \
             patch("src.executor.pipeline.dismiss_blocking_overlays", return_value=0), \
             patch("src.executor.pipeline.inject_code", return_value=fake_inject_res):

            result = run_solve_cycle(
                page=mock_page,
                code="wrong code",
                min_duration=0,
                eval_manager=mock_eval_mgr,
            )

            assert result["passed"] is False
            # 评测未通过时，不应清除打卡记录，以便下次重试继续累计已耗时
            assert test_controller.get_elapsed_time(page_url) >= 0.0
            assert test_controller._task_start_times != {}


class TestCliCheckinIntegration:
    """测试 CLI 子命令打卡集成"""

    def test_cmd_dump_question_auto_checkin_practical(self):
        """当 dump-question 提取到实训题且尚未打卡时，自动打卡"""
        from src.cli import main

        mock_page = MagicMock()
        task_url = "https://www.educoder.net/tasks/cli_dump_test"
        mock_page.url = task_url

        dummy_q = QuestionData(
            type=QuestionType.PRACTICAL,
            title="实训第一关",
            practical_details=PracticalDetails(language="python"),
        )

        with patch("src.cli.BrowserSession") as mock_session_cls, \
             patch("src.cli.extract_question", return_value=dummy_q), \
             patch.object(pacing_controller, "get_elapsed_time", return_value=0.0) as mock_get_elapsed, \
             patch.object(pacing_controller, "start_task") as mock_start:

            mock_session = MagicMock()
            mock_session.get_target_page.return_value = mock_page
            mock_session_cls.return_value.__enter__.return_value = mock_session

            main(["dump-question", "--json"])

            mock_get_elapsed.assert_called_once_with(task_url)
            mock_start.assert_called_once_with(task_url)

    def test_cmd_open_task_auto_checkin(self):
        """当 open-task 开启成功后，自动调用 start_task 打卡"""
        from src.cli import main

        task_url = "https://www.educoder.net/tasks/cli_open_test"
        fake_res = {
            "status": "success",
            "task_index": 0,
            "task_title": "实验一",
            "task_url": task_url,
            "level_preview": {"title": "第1关", "type": "practical"},
        }

        with patch("src.cli.BrowserSession"), \
             patch("src.cli.open_classroom_task", return_value=fake_res), \
             patch.object(pacing_controller, "start_task") as mock_start:

            main(["open-task", "--index", "0", "--json"])

            mock_start.assert_called_once_with(task_url)
