"""高信息密度测试集 Diff 提取器单元测试 (Diff Extractor Tests).

验证:
1. 全部通过场景识别 (包括庆祝弹窗与 100% 比例)
2. 典型头歌 DOM 格式识别 ("共有X组测试集...通过Y组")
3. 预期输出与实际输出精准提取 (清理多余 HTML 与换行)
4. 多种精炼差异提示 (diff_hint):
   - 行数不匹配
   - 大小写不匹配
   - 空白字符/末尾换行差异
   - 逐行内容差异
   - 实际输出为空
5. 控制台输出与 Python Traceback 异常栈分离
6. Playwright Page 对象与纯 HTML 字符串双向兼容
"""

from unittest.mock import MagicMock
import pytest

from src.executor.diff_extractor import (
    _line_by_line_diff,
    clean_text_content,
    extract_testcase_diff,
    generate_diff_hint,
)


class TestDiffExtractor:
    """测试 Diff 提取器核心功能"""

    def test_extract_all_passed_modal(self):
        """测试通关弹窗识别全绿"""
        html = """
        <div class="evaluate-result-container">
            <h3>恭喜通关！全部通过</h3>
            <p>获得经验值 +100，金币 +10</p>
            <button>下一关</button>
        </div>
        """
        res = extract_testcase_diff(html)
        assert res["passed"] is True
        assert res["pass_ratio"] == "1/1"
        assert "全部通过" in res["diff_hint"]
        assert res["error_msg"] == ""

    def test_extract_pass_ratio_partial(self):
        """测试部分通过比例解析 (如 1/2)"""
        html = """
        <div class="shixun-result">
            <div class="summary">共有 2 组测试集，已通过 1 组</div>
            <div class="testcase-detail">
                <div class="expected-output">8</div>
                <div class="actual-output">7</div>
            </div>
        </div>
        """
        res = extract_testcase_diff(html)
        assert res["passed"] is False
        assert res["pass_ratio"] == "1/2"
        assert res["expected"] == "8"
        assert res["actual"] == "7"
        assert "7" in res["diff_hint"] and "8" in res["diff_hint"]

    def test_extract_all_passed_ratio(self):
        """测试比例全部通过 (如 3/3)"""
        html = """
        <div class="test-result">
            <span>共有 3 组测试集，已通过 3 组</span>
            <div class="console-output">All testcases passed successfully!</div>
        </div>
        """
        res = extract_testcase_diff(html)
        assert res["passed"] is True
        assert "全部通过" in res["diff_hint"]

    def test_extract_labeled_sections(self):
        """测试标题式标签的预期输出与实际输出提取"""
        html = """
        <div class="testcase-panel">
            <h4>【预期输出】</h4>
            <pre>Hello World</pre>
            <h4>【实际输出】</h4>
            <pre>hello world</pre>
        </div>
        """
        res = extract_testcase_diff(html)
        assert res["expected"] == "Hello World"
        assert res["actual"] == "hello world"
        assert res["passed"] is False
        assert "大小写不匹配" in res["diff_hint"]

    def test_diff_hint_line_count_mismatch(self):
        """测试输出行数不匹配提示"""
        expected = "Line 1\nLine 2\nLine 3"
        actual = "Line 1\nLine 2"
        hint = generate_diff_hint(expected, actual, error_msg="", passed=False, pass_ratio="0/1")
        assert "行数不匹配" in hint
        assert "3 行" in hint
        assert "2 行" in hint

    def test_diff_hint_empty_actual(self):
        """测试实际输出为空提示"""
        expected = "42"
        actual = ""
        hint = generate_diff_hint(expected, actual, error_msg="", passed=False, pass_ratio="0/1")
        assert "实际输出为空" in hint

    def test_diff_hint_trailing_whitespace(self):
        """测试末尾换行差异提示"""
        expected = "hello"
        actual = "hello\n"
        hint = generate_diff_hint(expected, actual, error_msg="", passed=False, pass_ratio="0/1")
        assert "核心文本完全一致" in hint
        assert "隐形空白字符/换行不匹配" in hint
        assert "末尾是否缺少或多出空格/换行" in hint

    def test_diff_hint_leading_space(self):
        """测试缩进/前后空白差异提示"""
        expected = "foo"
        actual = "  foo"
        hint = generate_diff_hint(expected, actual, error_msg="", passed=False, pass_ratio="0/1")
        assert "核心文本完全一致" in hint
        assert "隐形空白字符/换行不匹配" in hint

        # 行级逐行比对检测
        line_hint = _line_by_line_diff(expected, actual)
        assert line_hint is not None
        assert "空白字符不匹配" in line_hint
        assert "末尾空格或制表符" in line_hint

    def test_extract_python_traceback(self):
        """测试从控制台日志中提取 Traceback 异常栈"""
        html = """
        <div class="console-output">
            <p>正在执行评测...</p>
            <pre>
Traceback (most recent call last):
  File "solution.py", line 12, in solve
    return a / b
ZeroDivisionError: division by zero
            </pre>
        </div>
        """
        res = extract_testcase_diff(html)
        assert res["passed"] is False
        assert "ZeroDivisionError" in res["error_msg"]
        assert "ZeroDivisionError: division by zero" in res["diff_hint"]

    def test_clean_text_content(self):
        """测试文本清理：ANSI码、HTML实体与首尾空格"""
        raw = "\x1b[31mError:&nbsp;Test&gt;Failed\x1b[0m\n\n\n"
        cleaned = clean_text_content(raw)
        assert "\x1b" not in cleaned
        assert "&nbsp;" not in cleaned
        assert cleaned == "Error: Test>Failed"

    def test_extract_from_mock_page(self):
        """测试传入 Playwright Page mock 对象"""
        mock_page = MagicMock()
        mock_page.content.return_value = """
        <div class="test-result">
            <span class="expected">Result: 100</span>
            <span class="actual">Result: 99</span>
        </div>
        """
        res = extract_testcase_diff(mock_page)
        assert res["expected"] == "Result: 100"
        assert res["actual"] == "Result: 99"
        assert "内容不匹配" in res["diff_hint"]

    def test_empty_html_fallback(self):
        """测试空输入安全兜底"""
        res = extract_testcase_diff("")
        assert res["passed"] is False
        assert res["diff_hint"] == "未获取到评测输出"

    def test_invisible_trailing_space_mismatch(self):
        """测试末尾隐形空格高敏识别 (预期 '6=3+3 ' vs 实际 '6=3+3')"""
        # 1. 直接比对 generate_diff_hint
        expected = "6=3+3 "
        actual = "6=3+3"
        hint = generate_diff_hint(expected, actual, error_msg="", passed=False, pass_ratio="0/1")
        assert "⚠️ 核心文本完全一致，但存在隐形空白字符/换行不匹配！" in hint
        assert "预期长度 6" in hint
        assert "实际长度 5" in hint
        assert "'6=3+3 '" in hint
        assert "'6=3+3'" in hint
        assert "请特别检查输出末尾是否缺少或多出空格/换行！" in hint
        assert "当前测试集输出与预期一致" not in hint

        # 2. 从 HTML 源码解析提取，验证 clean_text_content 与 extract_testcase_diff 完整链路
        html = """
        <div class="testcase-panel">
            <div class="summary">共有 1 组测试集，已通过 0 组</div>
            <div class="expected-output">6=3+3 </div>
            <div class="actual-output">6=3+3</div>
        </div>
        """
        res = extract_testcase_diff(html)
        assert res["passed"] is False
        assert res["expected"] == "6=3+3 "
        assert res["actual"] == "6=3+3"
        assert "⚠️ 核心文本完全一致，但存在隐形空白字符/换行不匹配！" in res["diff_hint"]
        assert "当前测试集输出与预期一致" not in res["diff_hint"]

        # 3. 多测试集比对场景：验证优先报出该具体空白字符差异，严禁误报为“当前测试集输出与预期一致 (可能存在其他未通过的隐藏测试集)”
        html_multi = """
        <div class="shixun-result">
            <div class="summary">共有 2 组测试集，已通过 1 组</div>
            <h4>【预期输出】</h4>
            <pre>6=3+3 </pre>
            <h4>【实际输出】</h4>
            <pre>6=3+3</pre>
        </div>
        """
        res_multi = extract_testcase_diff(html_multi)
        assert res_multi["passed"] is False
        assert res_multi["pass_ratio"] == "1/2"
        assert "⚠️ 核心文本完全一致，但存在隐形空白字符/换行不匹配！" in res_multi["diff_hint"]
        assert "当前测试集输出与预期一致" not in res_multi["diff_hint"]

        # 4. 传入纯文本 stdout 与 error_output 模式
        stdout_txt = "共有 1 组测试集，已通过 0 组\n预期输出：6=3+3 \n实际输出：6=3+3\n"
        res_stdout = extract_testcase_diff(stdout_txt, error_output="")
        assert res_stdout["passed"] is False
        assert res_stdout["expected"] == "6=3+3 "
        assert res_stdout["actual"] == "6=3+3"
        assert "⚠️ 核心文本完全一致，但存在隐形空白字符/换行不匹配！" in res_stdout["diff_hint"]
        assert "当前测试集输出与预期一致" not in res_stdout["diff_hint"]

    def test_line_by_line_diff_invisible_tab_and_newline(self):
        """测试逐行比对中行尾包含制表符或换行差异时的精确定位提示"""
        # 1. 行尾包含制表符 \t
        exp_tab = "Line 1\t\nLine 2"
        act_tab = "Line 1\nLine 2"
        hint_tab = _line_by_line_diff(exp_tab, act_tab)
        assert hint_tab == "第 1 行文本一致但空白字符不匹配: 预期='Line 1\\t' vs 实际='Line 1' (请检查末尾空格或制表符)"

        # 2. 第 2 行尾部包含多余空格
        exp_space = "header\ndata 123   \nfooter"
        act_space = "header\ndata 123\nfooter"
        hint_space = _line_by_line_diff(exp_space, act_space)
        assert hint_space == "第 2 行文本一致但空白字符不匹配: 预期='data 123   ' vs 实际='data 123' (请检查末尾空格或制表符)"

        # 3. 多行在 generate_diff_hint 中完整委托并定位到第 2 行
        gen_hint = generate_diff_hint(exp_space, act_space, error_msg="", passed=False, pass_ratio="0/1")
        assert gen_hint == "第 2 行文本一致但空白字符不匹配: 预期='data 123   ' vs 实际='data 123' (请检查末尾空格或制表符)"

        # 4. 单行包含制表符比对
        exp_single_tab = "output\t"
        act_single_tab = "output"
        hint_single_tab = _line_by_line_diff(exp_single_tab, act_single_tab)
        assert hint_single_tab == "第 1 行文本一致但空白字符不匹配: 预期='output\\t' vs 实际='output' (请检查末尾空格或制表符)"
