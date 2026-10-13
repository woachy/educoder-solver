"""Web 终端 xterm.js 接管与命令注入单元测试 (Terminal Action Tests).

验证:
1. 存在 .xterm-helper-textarea 时，通过 ClipboardEvent 成功注入命令并返回 True
2. execute_enter 状态控制（末尾追加 \\n 与保持原样）
3. .xterm-screen 兜底匹配机制
4. 终端元素不存在时，安全平滑返回 False 并记录 warning，绝不抛出未捕获异常
5. JS evaluate 抛出异常时的平滑捕获与错误日志
6. 跨 iframe 终端探查与穿透注入
7. read_terminal_output 提取 .xterm-rows 文本行并保留换行
8. read_terminal_output 在元素不存在或异常时安全返回空字符串
"""

from unittest.mock import MagicMock, patch
import pytest

from src.executor import inject_terminal_command, read_terminal_output
from src.executor.terminal_action import _get_all_frames


class TestTerminalAction:
    """测试 Web 终端命令注入与输出提取"""

    def test_inject_terminal_command_success_with_textarea(self):
        """测试存在 .xterm-helper-textarea 时，注入成功并返回 True"""
        mock_page = MagicMock()
        mock_textarea = MagicMock()
        mock_page.query_selector.side_effect = lambda sel: mock_textarea if ".xterm-helper-textarea" in sel else None
        mock_page.evaluate.return_value = True

        result = inject_terminal_command(mock_page, "ls -la")

        assert result is True
        mock_page.evaluate.assert_called_once()
        # 验证 execute_enter=True 默认自动在末尾追加 \n
        call_args = mock_page.evaluate.call_args[0]
        js_code = call_args[0]
        payload = call_args[1]
        assert "ClipboardEvent" in js_code
        assert "DataTransfer" in js_code
        assert payload["text"] == "ls -la\n"

    def test_inject_terminal_command_without_enter(self):
        """测试 execute_enter=False 时，末尾不追加换行"""
        mock_page = MagicMock()
        mock_textarea = MagicMock()
        mock_page.query_selector.return_value = mock_textarea
        mock_page.evaluate.return_value = True

        result = inject_terminal_command(mock_page, "cat file.txt", execute_enter=False)

        assert result is True
        call_args = mock_page.evaluate.call_args[0]
        payload = call_args[1]
        assert payload["text"] == "cat file.txt"

    def test_inject_terminal_command_already_has_newline(self):
        """测试命令本身已包含换行时，不重复追加换行"""
        mock_page = MagicMock()
        mock_textarea = MagicMock()
        mock_page.query_selector.return_value = mock_textarea
        mock_page.evaluate.return_value = True

        result = inject_terminal_command(mock_page, "pwd\n", execute_enter=True)

        assert result is True
        payload = mock_page.evaluate.call_args[0][1]
        assert payload["text"] == "pwd\n"

    def test_inject_terminal_command_screen_fallback(self):
        """测试 .xterm-helper-textarea 不存在时，通过 .xterm-screen 兜底匹配成功"""
        mock_page = MagicMock()
        mock_screen = MagicMock()
        mock_page.query_selector.side_effect = lambda sel: mock_screen if ".xterm-screen" in sel else None
        mock_page.evaluate.return_value = True

        result = inject_terminal_command(mock_page, "whoami")

        assert result is True
        payload = mock_page.evaluate.call_args[0][1]
        assert payload["text"] == "whoami\n"

    def test_inject_terminal_command_element_not_found(self):
        """测试页面不存在终端元素时，平滑返回 False 并记录 warning，不抛异常"""
        mock_page = MagicMock()
        mock_page.query_selector.return_value = None

        result = inject_terminal_command(mock_page, "ls")

        assert result is False
        # 未找到元素时，不应发起 evaluate 注入
        mock_page.evaluate.assert_not_called()

    def test_inject_terminal_command_evaluate_returns_false(self):
        """测试 evaluate 脚本执行返回 False 时平滑返回 False"""
        mock_page = MagicMock()
        mock_page.query_selector.return_value = MagicMock()
        mock_page.evaluate.return_value = False

        result = inject_terminal_command(mock_page, "make")

        assert result is False

    def test_inject_terminal_command_evaluate_exception(self):
        """测试 evaluate 过程中发生异常时，安全捕获并返回 False"""
        mock_page = MagicMock()
        mock_page.query_selector.return_value = MagicMock()
        mock_page.evaluate.side_effect = Exception("Page context destroyed")

        result = inject_terminal_command(mock_page, "echo hello")

        assert result is False

    def test_inject_terminal_command_none_page(self):
        """测试 page 为空时的安全防护"""
        result = inject_terminal_command(None, "ls")
        assert result is False

    def test_inject_terminal_command_iframe_support(self):
        """测试终端位于子 iframe 时的穿透注入"""
        mock_page = MagicMock()
        mock_frame = MagicMock()
        mock_page.frames = [mock_page, mock_frame]

        # 主页面找不到终端，子 iframe 找到了终端
        mock_page.query_selector.return_value = None
        mock_frame.query_selector.return_value = MagicMock()
        mock_frame.evaluate.return_value = True

        result = inject_terminal_command(mock_page, "python app.py")

        assert result is True
        mock_frame.evaluate.assert_called_once()
        assert mock_frame.evaluate.call_args[0][1]["text"] == "python app.py\n"

    def test_read_terminal_output_success(self):
        """测试调用 read_terminal_output 成功提取终端可见文本行并保留换行"""
        mock_page = MagicMock()
        sample_output = "root@educoder:~# ls\napp.py  README.md\nroot@educoder:~# "
        mock_page.evaluate.return_value = sample_output

        output = read_terminal_output(mock_page)

        assert output == sample_output
        mock_page.evaluate.assert_called_once()
        # 验证 JS 脚本中针对 .xterm-rows 的查询
        js_code = mock_page.evaluate.call_args[0][0]
        assert ".xterm-rows" in js_code

    def test_read_terminal_output_not_found(self):
        """测试未找到终端输出元素时，返回空字符串"""
        mock_page = MagicMock()
        mock_page.evaluate.return_value = None

        output = read_terminal_output(mock_page)

        assert output == ""

    def test_read_terminal_output_exception(self):
        """测试提取终端输出发生异常时，安全返回空字符串并不崩溃"""
        mock_page = MagicMock()
        mock_page.evaluate.side_effect = Exception("Target frame detached")

        output = read_terminal_output(mock_page)

        assert output == ""

    def test_read_terminal_output_none_page(self):
        """测试 page 为 None 时安全返回空字符串"""
        output = read_terminal_output(None)
        assert output == ""

    def test_read_terminal_output_iframe_support(self):
        """测试从子 iframe 提取终端输出"""
        mock_page = MagicMock()
        mock_frame = MagicMock()
        mock_page.frames = [mock_page, mock_frame]

        mock_page.evaluate.return_value = None
        mock_frame.evaluate.return_value = "iframe terminal content\nsecond line"

        output = read_terminal_output(mock_page)

        assert output == "iframe terminal content\nsecond line"
