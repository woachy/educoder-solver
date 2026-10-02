"""统一命令行接口单元测试 (CLI Tests).

验证:
1. build_parser 参数解析完备性 (支持各子命令与选项)
2. check-browser 命令与 --json 结构化输出
3. dump-question 命令与结构化 JSON 回执
4. submit-choice / submit-blank 拟真下发参数解析与路由
5. inject-code 代码注入与文件读取
6. trigger-eval 评测与自动下一关参数
7. submit-answer 兼容性综合命令路由
"""

import json
from unittest.mock import MagicMock, patch
import pytest

from src.cli import build_parser, main
from src.executor.eval_action import EvaluationManager
from src.extractor.base import QuestionData, QuestionType


class TestCliParser:
    """测试命令行参数解析器"""

    def test_parser_check_browser(self):
        parser = build_parser()
        args = parser.parse_args(["check-browser", "--port", "9222", "--json"])
        assert args.command == "check-browser"
        assert args.port == 9222
        assert args.json is True

    def test_parser_dump_question(self):
        parser = build_parser()
        args = parser.parse_args(["dump-question", "-o", "task.json", "-t", "choice", "--json"])
        assert args.command == "dump-question"
        assert args.output == "task.json"
        assert args.type == "choice"
        assert args.json is True

    def test_parser_submit_choice(self):
        parser = build_parser()
        args = parser.parse_args(["submit-choice", "--options", "A,B", "--json"])
        assert args.command == "submit-choice"
        assert args.options == "A,B"
        assert args.json is True

    def test_parser_submit_blank(self):
        parser = build_parser()
        args = parser.parse_args(["submit-blank", "--answers", '["print", "input"]', "--json"])
        assert args.command == "submit-blank"
        assert args.answers == '["print", "input"]'
        assert args.json is True

    def test_parser_inject_code(self):
        parser = build_parser()
        args = parser.parse_args(["inject-code", "--code", "return a+b", "--full", "--json"])
        assert args.command == "inject-code"
        assert args.code == "return a+b"
        assert args.full is True
        assert args.json is True

    def test_parser_trigger_eval(self):
        parser = build_parser()
        args = parser.parse_args(["trigger-eval", "--timeout", "30", "--auto-next", "--json"])
        assert args.command == "trigger-eval"
        assert args.timeout == 30
        assert args.auto_next is True
        assert args.json is True

    def test_parser_submit_answer(self):
        parser = build_parser()
        args = parser.parse_args(["submit-answer", "--type", "choice", "--data", "A", "--json"])
        assert args.command == "submit-answer"
        assert args.type == "choice"
        assert args.data == "A"
        assert args.json is True


class TestCliExecution:
    """测试各子命令执行与 --json 结构化输出"""

    def test_cmd_check_browser_json(self, capsys):
        """测试 check-browser 在 --json 模式下输出合规 JSON"""
        with patch("src.cli.check_cdp_available", return_value=True), \
             patch("src.cli.BrowserSession") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.list_pages.return_value = [
                {"title": "Educoder Task", "url": "https://www.educoder.net/tasks/101"}
            ]
            mock_session_cls.return_value.__enter__.return_value = mock_session

            main(["check-browser", "--json"])
            captured = capsys.readouterr()
            data = json.loads(captured.out)

            assert data["status"] == "online"
            assert data["cdp_available"] is True
            assert data["educoder_pages_count"] == 1
            assert len(data["pages"]) == 1

    def test_cmd_dump_question_json(self, capsys):
        """测试 dump-question 提取题目并输出标准 JSON"""
        dummy_q = QuestionData(
            type=QuestionType.CHOICE,
            title="测试题目",
            description="描述内容",
        )

        with patch("src.cli.BrowserSession") as mock_session_cls, \
             patch("src.cli.extract_question", return_value=dummy_q):
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__.return_value = mock_session

            main(["dump-question", "--json"])
            captured = capsys.readouterr()
            data = json.loads(captured.out)

            assert data["type"] == "choice"
            assert data["title"] == "测试题目"

    def test_cmd_submit_choice_json(self, capsys):
        """测试 submit-choice 下发并输出回执 JSON"""
        fake_result = {
            "success": True,
            "clicked_options": ["A"],
            "already_selected": [],
            "message": "成功",
        }

        with patch("src.cli.BrowserSession"), \
             patch("src.cli.submit_choice_answer", return_value=fake_result):
            main(["submit-choice", "--options", "A", "--json"])
            captured = capsys.readouterr()
            data = json.loads(captured.out)

            assert data["success"] is True
            assert "A" in data["clicked_options"]

    def test_cmd_submit_blank_json(self, capsys):
        """测试 submit-blank 下发并输出回执 JSON"""
        fake_result = {
            "success": True,
            "filled_count": 2,
            "total_answers": 2,
            "message": "成功",
        }

        with patch("src.cli.BrowserSession"), \
             patch("src.cli.submit_blank_answer", return_value=fake_result):
            main(["submit-blank", "--answers", '["print", "input"]', "--json"])
            captured = capsys.readouterr()
            data = json.loads(captured.out)

            assert data["success"] is True
            assert data["filled_count"] == 2

    def test_cmd_inject_code_file_json(self, tmp_path, capsys):
        """测试 inject-code 从文件读取并输出回执 JSON"""
        test_file = tmp_path / "solution.py"
        test_file.write_text("def solve(): pass", encoding="utf-8")

        fake_result = {
            "success": True,
            "backup_path": "/path/to/backup.py",
            "method_used": "monaco_api",
            "message": "成功",
        }

        with patch("src.cli.BrowserSession"), \
             patch("src.cli.inject_code", return_value=fake_result):
            main(["inject-code", "--file", str(test_file), "--json"])
            captured = capsys.readouterr()
            data = json.loads(captured.out)

            assert data["success"] is True
            assert data["method_used"] == "monaco_api"

    def test_cmd_trigger_eval_json(self, capsys):
        """测试 trigger-eval 触发并输出评测回执 JSON"""
        fake_result = {
            "success": True,
            "passed": True,
            "pass_ratio": "3/3",
            "circuit_broken": False,
            "message": "全部通过",
        }

        with patch("src.cli.BrowserSession"), \
             patch.object(EvaluationManager, "trigger_and_wait_eval", return_value=fake_result):
            main(["trigger-eval", "--timeout", "30", "--json"])
            captured = capsys.readouterr()
            data = json.loads(captured.out)

            assert data["passed"] is True
            assert data["pass_ratio"] == "3/3"
            assert data["circuit_broken"] is False
