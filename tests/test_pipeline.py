"""复合答题流水线与遮罩清理器单元测试 (Pipeline & Sweeper Tests).

验证:
1. 遮罩清理器识别并关闭各类弹窗按钮与遮罩层 (dismiss_blocking_overlays)
2. 复合流水线 run_solve_cycle 全闭环流转 (清理 -> 注入 -> 评测 -> Diff -> 下一关)
3. 注入失败时的流水线快速熔断保护
4. 评测失败时高密度 Diff 提纯字段透传
5. CLI solve-cycle 子命令解析与执行
"""

import json
from unittest.mock import MagicMock, patch
import pytest

from src.cli import build_parser, main
from src.executor.eval_action import EvaluationManager
from src.executor.modal_sweeper import dismiss_blocking_overlays
from src.executor.pipeline import run_solve_cycle


class TestModalSweeper:
    """测试弹窗与残留遮罩清理器"""

    def test_dismiss_visible_close_buttons(self):
        """测试定位并点击可见的弹窗关闭按钮"""
        mock_page = MagicMock()
        mock_btn_1 = MagicMock()
        mock_btn_1.is_visible.return_value = True
        mock_btn_2 = MagicMock()
        mock_btn_2.is_visible.return_value = False  # 不可见的不点击

        def qsa_side_effect(selector):
            if ".ant-modal-close" in selector:
                return [mock_btn_1, mock_btn_2]
            return []

        mock_page.query_selector_all.side_effect = qsa_side_effect
        mock_page.evaluate.return_value = 0

        count = dismiss_blocking_overlays(mock_page)
        assert count == 1
        mock_btn_1.click.assert_called_once()
        mock_btn_2.click.assert_not_called()

    def test_dismiss_pointer_blocking_masks_via_js(self):
        """测试通过 JS evaluate 清理残留阻断指针事件的遮罩层"""
        mock_page = MagicMock()
        mock_page.query_selector_all.return_value = []
        mock_page.evaluate.return_value = 2  # JS 清理了 2 个残留遮罩

        count = dismiss_blocking_overlays(mock_page)
        assert count == 2

    def test_dismiss_empty_page(self):
        """测试空页面对象容错"""
        assert dismiss_blocking_overlays(None) == 0


class TestPipeline:
    """测试复合流水线核心引擎"""

    def test_run_solve_cycle_all_passed_with_auto_next(self):
        """测试代码注入成功、评测全通过并自动流转下一关"""
        mock_page = MagicMock()
        mock_eval_mgr = MagicMock(spec=EvaluationManager)

        fake_inject_res = {
            "success": True,
            "method_used": "monaco_api",
            "backup_path": "/cache/backup_123.py",
            "is_target_assembled": True,
            "message": "注入成功",
        }
        fake_eval_res = {
            "success": True,
            "passed": True,
            "pass_ratio": "1/1",
            "expected": "",
            "actual": "",
            "diff_hint": "全部测试用例通过 (1/1)",
            "stdout": "Success",
            "stdout_msg": "Success",
            "error_output": "",
            "error_msg": "",
            "circuit_broken": False,
            "message": "评测全部通过！",
        }

        mock_eval_mgr.trigger_and_wait_eval.return_value = fake_eval_res
        mock_eval_mgr.trigger_next_level.return_value = True

        with patch("src.executor.pipeline.dismiss_blocking_overlays", return_value=1), \
             patch("src.executor.pipeline.inject_code", return_value=fake_inject_res):

            result = run_solve_cycle(
                page=mock_page,
                code="return a + b",
                target_only=True,
                auto_next=True,
                timeout=30,
                eval_manager=mock_eval_mgr,
            )

            assert result["success"] is True
            assert result["passed"] is True
            assert result["pass_ratio"] == "1/1"
            assert result["next_level_triggered"] is True
            assert result["overlays_dismissed"] == 1
            assert result["injection"]["method_used"] == "monaco_api"
            assert result["elapsed_seconds"] >= 0
            mock_eval_mgr.trigger_next_level.assert_called_once_with(mock_page)

    def test_run_solve_cycle_injection_fail_early_exit(self):
        """测试注入失败时快速阻断，不触发评测"""
        mock_page = MagicMock()
        mock_eval_mgr = MagicMock(spec=EvaluationManager)

        fake_inject_res = {
            "success": False,
            "message": "待注入代码不能为空",
            "method_used": "none",
            "backup_path": "",
            "is_target_assembled": False,
        }

        with patch("src.executor.pipeline.dismiss_blocking_overlays", return_value=0), \
             patch("src.executor.pipeline.inject_code", return_value=fake_inject_res):

            result = run_solve_cycle(
                page=mock_page,
                code="",
                eval_manager=mock_eval_mgr,
            )

            assert result["success"] is False
            assert result["passed"] is False
            assert "代码注入失败" in result["diff_hint"]
            mock_eval_mgr.trigger_and_wait_eval.assert_not_called()

    def test_run_solve_cycle_eval_failed_with_diff_info(self):
        """测试评测未通过时，透传高信息密度 Diff 对比"""
        mock_page = MagicMock()
        mock_eval_mgr = MagicMock(spec=EvaluationManager)

        fake_inject_res = {
            "success": True,
            "method_used": "monaco_api",
            "backup_path": "/cache/b.py",
            "is_target_assembled": True,
        }
        fake_eval_res = {
            "success": True,
            "passed": False,
            "pass_ratio": "0/1",
            "expected": "8",
            "actual": "7",
            "diff_hint": "第 1 行内容不匹配: 预期 '8' vs 实际 '7'",
            "stdout": "",
            "stdout_msg": "",
            "error_output": "AssertionError: 8 != 7",
            "error_msg": "AssertionError: 8 != 7",
            "circuit_broken": False,
            "message": "评测未通过",
        }
        mock_eval_mgr.trigger_and_wait_eval.return_value = fake_eval_res

        with patch("src.executor.pipeline.dismiss_blocking_overlays", return_value=0), \
             patch("src.executor.pipeline.inject_code", return_value=fake_inject_res):

            result = run_solve_cycle(
                page=mock_page,
                code="return 7",
                auto_next=True,  # 未通过时不应流转
                eval_manager=mock_eval_mgr,
            )

            assert result["passed"] is False
            assert result["expected"] == "8"
            assert result["actual"] == "7"
            assert "8" in result["diff_hint"] and "7" in result["diff_hint"]
            assert result["next_level_triggered"] is False
            mock_eval_mgr.trigger_next_level.assert_not_called()


class TestCliSolveCycle:
    """测试 CLI solve-cycle 子命令"""

    def test_parser_solve_cycle(self):
        parser = build_parser()
        args = parser.parse_args(["solve-cycle", "--code", "return a+b", "--auto-next", "--timeout", "45", "--json"])
        assert args.command == "solve-cycle"
        assert args.code == "return a+b"
        assert args.auto_next is True
        assert args.timeout == 45
        assert args.json is True

    def test_cmd_solve_cycle_json(self, capsys):
        """测试 CLI solve-cycle 运行并输出 JSON"""
        fake_pipeline_res = {
            "success": True,
            "passed": True,
            "pass_ratio": "1/1",
            "expected": "",
            "actual": "",
            "diff_hint": "全部测试用例通过 (1/1)",
            "stdout_msg": "ok",
            "error_msg": "",
            "circuit_broken": False,
            "next_level_triggered": False,
            "overlays_dismissed": 0,
            "elapsed_seconds": 1.25,
            "injection": {"method_used": "monaco_api"},
            "message": "成功",
        }

        with patch("src.cli.BrowserSession"), \
             patch("src.cli.run_solve_cycle", return_value=fake_pipeline_res):
            main(["solve-cycle", "--code", "return a+b", "--json"])
            captured = capsys.readouterr()
            data = json.loads(captured.out)

            assert data["passed"] is True
            assert data["pass_ratio"] == "1/1"
            assert "全部测试用例通过" in data["diff_hint"]
