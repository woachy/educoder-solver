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
        assert "空白字符差异" in hint
        assert "末尾多出" in hint

    def test_diff_hint_leading_space(self):
        """测试缩进/前后空白差异提示"""
        expected = "foo"
        actual = "  foo"
        hint = generate_diff_hint(expected, actual, error_msg="", passed=False, pass_ratio="0/1")
        assert "缩进" in hint or "空格不匹配" in hint

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
