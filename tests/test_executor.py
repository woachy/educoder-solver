"""拟真执行引擎与评测监听单元测试 (Executor Tests).

验证:
1. 选择题点击防反选逻辑 (未勾选才点击，已勾选严禁二次点击误取消)
2. 填空题槽位匹配、顺序填入与 Vue/React 双向绑定事件分发
3. 编辑器修改前自动快照备份至 .cache/backups/
4. Begin-End 靶心代码无损组装与全量覆盖模式
5. Monaco API 优先与键盘覆盖分级注入
6. 评测监听与连续 3 次相同报错时的熔断保护 (Circuit Breaker)
7. 下一关按钮识别与触发
"""

import os
from pathlib import Path
from unittest.mock import MagicMock, call, patch
import pytest

from src.executor.blank_action import submit_blank_answer
from src.executor.choice_action import submit_choice_answer
from src.executor.editor_action import (
    assemble_target_code,
    backup_code_to_file,
    inject_code,
)
from src.executor.eval_action import EvaluationManager
from src.extractor.base import (
    BlankItem,
    ChoiceOption,
    PracticalDetails,
    QuestionData,
    QuestionType,
)


# =====================================================================
# 1. 客观选择题与判断题拟真执行测试 (Choice Action Tests)
# =====================================================================

class TestChoiceAction:
    """测试选择题拟真点击与防反选逻辑"""

    def test_single_choice_click_unselected(self):
        """测试单选题：未选中项被正常点击"""
        mock_page = MagicMock()
        mock_elem = MagicMock()
        mock_page.query_selector.return_value = mock_elem

        q_data = QuestionData(
            type=QuestionType.CHOICE,
            title="Python序列测试",
            options=[
                ChoiceOption(id="A", text="列表", selected=False, selector="#opt_a"),
                ChoiceOption(id="B", text="元组", selected=False, selector="#opt_b"),
            ],
        )

        with patch("src.executor.choice_action.random_delay") as mock_delay:
            result = submit_choice_answer(mock_page, ["A"], question_data=q_data)

            assert result["success"] is True
            assert "A" in result["clicked_options"]
            assert len(result["already_selected"]) == 0
            mock_elem.click.assert_called_once()
            mock_delay.assert_called()

    def test_multiple_choice_anti_uncheck(self):
        """【核心红线】多选题防反选：已勾选的选项严禁二次点击，仅点击未勾选的选项"""
        mock_page = MagicMock()
        mock_elem_a = MagicMock()
        mock_elem_c = MagicMock()

        def query_selector_side_effect(selector):
            if "opt_a" in selector:
                return mock_elem_a
            elif "opt_c" in selector:
                return mock_elem_c
            return None

        mock_page.query_selector.side_effect = query_selector_side_effect

        # A 已处于选中态 (selected=True)，C 处于未选中态 (selected=False)
        q_data = QuestionData(
            type=QuestionType.MULTIPLE_CHOICE,
            title="多选题测试",
            options=[
                ChoiceOption(id="A", text="int", selected=True, selector="#opt_a"),
                ChoiceOption(id="B", text="list", selected=False, selector="#opt_b"),
                ChoiceOption(id="C", text="tuple", selected=False, selector="#opt_c"),
            ],
        )

        with patch("src.executor.choice_action.random_delay"):
            # 目标选项为 A 和 C
            result = submit_choice_answer(mock_page, ["A", "C"], question_data=q_data)

            assert result["success"] is True
            # A 应该在 already_selected 中，且绝对未执行 click()
            assert "A" in result["already_selected"]
            assert "A" not in result["clicked_options"]
            mock_elem_a.click.assert_not_called()

            # C 应该被点击，且在 clicked_options 中
            assert "C" in result["clicked_options"]
            mock_elem_c.click.assert_called_once()

    def test_judgment_alias_matching(self):
        """测试判断题语义别名匹配 (如 '对' 匹配 '正确', '错' 匹配 '错误')"""
        mock_page = MagicMock()
        mock_elem = MagicMock()
        mock_page.query_selector.return_value = mock_elem

        q_data = QuestionData(
            type=QuestionType.JUDGMENT,
            title="判断题测试",
            options=[
                ChoiceOption(id="正确", text="正确", selected=False, selector="#opt_true"),
                ChoiceOption(id="错误", text="错误", selected=False, selector="#opt_false"),
            ],
        )

        with patch("src.executor.choice_action.random_delay"):
            # 传入 '对' 或 'T'
            result = submit_choice_answer(mock_page, ["对"], question_data=q_data)
            assert result["success"] is True
            assert "正确" in result["clicked_options"]
            mock_elem.click.assert_called_once()

    def test_empty_target_options(self):
        """测试空目标选项安全容错"""
        mock_page = MagicMock()
        result = submit_choice_answer(mock_page, [])
        assert result["success"] is False
        assert "未指定任何目标选项" in result["message"]


# =====================================================================
# 2. 文本填空题拟真执行测试 (Blank Action Tests)
# =====================================================================

class TestBlankAction:
    """测试填空题槽位匹配与事件分发"""

    def test_submit_blank_multiple_slots(self):
        """测试按槽位序号顺序填入多个答案"""
        mock_page = MagicMock()
        mock_input_1 = MagicMock()
        mock_input_2 = MagicMock()
        mock_page.query_selector_all.return_value = [mock_input_1, mock_input_2]

        q_data = QuestionData(
            type=QuestionType.BLANK,
            title="填空题",
            blanks=[
                BlankItem(index=1, hint="函数1", selector="input.blank-input:nth-of-type(1)"),
                BlankItem(index=2, hint="函数2", selector="input.blank-input:nth-of-type(2)"),
            ],
        )

        with patch("src.executor.blank_action.random_delay"):
            result = submit_blank_answer(mock_page, ["print", "input"], question_data=q_data)

            assert result["success"] is True
            assert result["filled_count"] == 2
            mock_input_1.fill.assert_called_with("print")
            mock_input_2.fill.assert_called_with("input")

            # 验证触发了 evaluate 分发 input/change/blur 事件
            assert mock_page.evaluate.call_count == 2

    def test_submit_blank_exceed_slots(self):
        """测试答案数量超出页面实际槽位时的容错提示"""
        mock_page = MagicMock()
        mock_input = MagicMock()
        mock_page.query_selector_all.return_value = [mock_input]

        with patch("src.executor.blank_action.random_delay"):
            result = submit_blank_answer(mock_page, ["ans1", "ans2"])
            assert result["success"] is False
            assert result["filled_count"] == 1
            assert result["details"][1]["status"] == "slot_not_found"


# =====================================================================
# 3. 编程实训题安全注入测试 (Editor Action Tests)
# =====================================================================

class TestEditorAction:
    """测试实训题代码快照备份、靶心代码组装与分级注入"""

    def test_backup_code_to_file(self, tmp_path):
        """测试原代码自动快照备份持久化"""
        original_code = "def old_func():\n    return 42\n"
        with patch("src.executor.editor_action.BACKUP_DIR", tmp_path):
            backup_path = backup_code_to_file(original_code, lang="py")
            assert os.path.exists(backup_path)
            with open(backup_path, "r", encoding="utf-8") as f:
                content = f.read()
            assert content == original_code
            assert backup_path.endswith(".py")

    def test_target_assembly_with_marker(self):
        """测试存在 Begin-End 区域时的靶心无损组装"""
        prefix = "def solve(a, b):\n    # ********** Begin **********\n"
        suffix = "    # ********** End **********\n    return 0\n"
        new_core_code = "    return a + b"

        assembled, is_assembled = assemble_target_code(new_core_code, prefix, suffix, has_marker=True)
        assert is_assembled is True
        assert assembled.startswith(prefix)
        assert assembled.endswith(suffix)
        assert "    return a + b\n" in assembled

    def test_target_assembly_without_marker(self):
        """测试未标记 Begin-End 时的纯代码直通"""
        raw_code = "print('hello')"
        assembled, is_assembled = assemble_target_code(raw_code, "", "", has_marker=False)
        assert is_assembled is False
        assert assembled == raw_code

    def test_inject_code_monaco_api_priority(self, tmp_path):
        """测试优先通过 Monaco 原生 API setValue 注入"""
        mock_page = MagicMock()
        # 第一次 evaluate (获取当前代码): 返回原代码
        # 第二次 evaluate (Monaco setValue): 返回 True
        mock_page.evaluate.side_effect = [
            "def foo():\n    pass",  # get current code
            True,                    # monaco setValue success
        ]

        with patch("src.executor.editor_action.BACKUP_DIR", tmp_path):
            result = inject_code(mock_page, "def foo():\n    return 1", target_only=False)

            assert result["success"] is True
            assert result["method_used"] == "monaco_api"
            assert os.path.exists(result["backup_path"])

    def test_inject_code_keyboard_fallback(self, tmp_path):
        """测试 Monaco 与 Ace API 均失败时自动降级至键盘选中覆盖"""
        mock_page = MagicMock()
        mock_page.query_selector.return_value = MagicMock()
        # JS evaluate 全部返回 False
        mock_page.evaluate.return_value = False

        with patch("src.executor.editor_action.BACKUP_DIR", tmp_path), \
             patch("src.executor.editor_action.random_delay"):
            result = inject_code(mock_page, "new_code_content", target_only=False)

            assert result["success"] is True
            assert result["method_used"] == "keyboard_fallback"
            mock_page.keyboard.press.assert_has_calls([call("Control+A"), call("Backspace")])
            mock_page.keyboard.insert_text.assert_called_with("new_code_content")


# =====================================================================
# 4. 评测监听与自愈熔断器测试 (Evaluation & Circuit Breaker Tests)
# =====================================================================

class TestEvaluationManager:
    """测试实训评测生命周期与自愈熔断保护机制"""

    def test_eval_passed_detection(self):
        """测试评测通过状态与 100% 比例识别"""
        eval_mgr = EvaluationManager(max_consecutive_unchanged_errors=3)
        mock_page = MagicMock()
        mock_btn = MagicMock()
        mock_page.query_selector.side_effect = lambda sel: mock_btn if "button" in sel or "评测" in sel else None
        
        # 模拟评测结果容器输出
        mock_container = MagicMock()
        mock_container.is_visible.return_value = True
        mock_container.inner_text.return_value = "全部通过！通过用例: 3/3\n恭喜通关！"

        with patch.object(eval_mgr, "find_eval_button", return_value=mock_btn), \
             patch.object(eval_mgr, "wait_for_eval_completion", return_value=True), \
             patch.object(eval_mgr, "extract_eval_results", return_value={
                 "passed": True,
                 "pass_ratio": "3/3",
                 "error_output": "",
                 "stdout": "全部通过！",
                 "raw_output": "全部通过！通过用例: 3/3",
             }):
            result = eval_mgr.trigger_and_wait_eval(mock_page)

            assert result["success"] is True
            assert result["passed"] is True
            assert result["pass_ratio"] == "3/3"
            assert result["circuit_broken"] is False
            assert len(eval_mgr.error_history) == 0

    def test_circuit_breaker_triggers_on_3_identical_errors(self):
        """【核心红线】连续 3 次返回完全一致的评测报错时，触发熔断保护并拒绝后续评测"""
        eval_mgr = EvaluationManager(max_consecutive_unchanged_errors=3)
        mock_page = MagicMock()
        mock_btn = MagicMock()

        same_error = "AssertionError: Expected 8 but got 7 on line 12"

        with patch.object(eval_mgr, "find_eval_button", return_value=mock_btn), \
             patch.object(eval_mgr, "wait_for_eval_completion", return_value=True), \
             patch.object(eval_mgr, "extract_eval_results", return_value={
                 "passed": False,
                 "pass_ratio": "1/3",
                 "error_output": same_error,
                 "stdout": "",
                 "raw_output": same_error,
             }):

            # 第 1 次报错
            r1 = eval_mgr.trigger_and_wait_eval(mock_page)
            assert r1["passed"] is False
            assert r1["circuit_broken"] is False
            assert len(eval_mgr.error_history) == 1

            # 第 2 次相同报错
            r2 = eval_mgr.trigger_and_wait_eval(mock_page)
            assert r2["passed"] is False
            assert r2["circuit_broken"] is False
            assert len(eval_mgr.error_history) == 2

            # 第 3 次相同报错 -> 触发熔断！
            r3 = eval_mgr.trigger_and_wait_eval(mock_page)
            assert r3["passed"] is False
            assert r3["circuit_broken"] is True
            assert eval_mgr.circuit_broken is True

            # 第 4 次调用 -> 前置阻断，不发起任何点击
            mock_btn.click.reset_mock()
            r4 = eval_mgr.trigger_and_wait_eval(mock_page)
            assert r4["circuit_broken"] is True
            assert r4["success"] is False
            assert "熔断保护生效中" in r4["message"]
            mock_btn.click.assert_not_called()

    def test_circuit_breaker_resets_on_error_change(self):
        """测试报错信息发生变化时不触发连续相同错误熔断"""
        eval_mgr = EvaluationManager(max_consecutive_unchanged_errors=3)

        assert eval_mgr.record_error("SyntaxError: line 1") is False
        assert eval_mgr.record_error("SyntaxError: line 1") is False
        # 第 3 次报错发生变化
        assert eval_mgr.record_error("TypeError: line 5") is False
        assert eval_mgr.circuit_broken is False

    def test_trigger_next_level(self):
        """测试下一关按钮定位与点击"""
        eval_mgr = EvaluationManager()
        mock_page = MagicMock()
        mock_next_btn = MagicMock()
        mock_next_btn.is_visible.return_value = True
        mock_page.query_selector.return_value = mock_next_btn

        with patch("src.executor.eval_action.random_delay"):
            clicked = eval_mgr.trigger_next_level(mock_page)
            assert clicked is True
            mock_next_btn.click.assert_called_once()

    def test_dismiss_blocking_overlays_integrated_in_eval(self):
        """测试 trigger_and_wait_eval 自动调用 dismiss_blocking_overlays 清理弹窗"""
        eval_mgr = EvaluationManager()
        mock_page = MagicMock()
        mock_btn = MagicMock()

        with patch("src.executor.eval_action.dismiss_blocking_overlays") as mock_dismiss, \
             patch.object(eval_mgr, "find_eval_button", return_value=mock_btn), \
             patch.object(eval_mgr, "wait_for_eval_completion", return_value=True), \
             patch.object(eval_mgr, "extract_eval_results", return_value={"passed": True, "pass_ratio": "1/1", "error_output": "", "stdout": ""}):
            result = eval_mgr.trigger_and_wait_eval(mock_page)
            assert result["passed"] is True
            mock_dismiss.assert_called_once_with(mock_page)

    def test_wait_for_eval_completion_two_stages(self):
        """测试两阶段防竞态监听：loading结束后比对快照新鲜度"""
        eval_mgr = EvaluationManager()
        mock_page = MagicMock()

        # 模拟：第一阶段无 modal，第二阶段按钮可用且检测到新结果
        with patch.object(eval_mgr, "_is_eval_loading", side_effect=[True, False]), \
             patch.object(eval_mgr, "_is_eval_btn_ready", return_value=True), \
             patch.object(eval_mgr, "get_result_snapshot", side_effect=["old_res", "new_res"]):
            completed = eval_mgr.wait_for_eval_completion(mock_page, timeout_seconds=5, pre_snapshot="old_res")
            assert completed is True
