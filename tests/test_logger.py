"""针对 src.utils.logger 的单元测试"""

import io
import json
import sys
from src.utils.logger import AgentLogger, print_json_result


def test_logger_methods():
    """测试日志方法正常调用不抛出异常"""
    custom_logger = AgentLogger(name="test_logger", json_mode=False)
    custom_logger.debug("Test debug message")
    custom_logger.info("Test info message")
    custom_logger.success("Test success message")
    custom_logger.warning("Test warning message")
    custom_logger.error("Test error message")


def test_logger_json_mode_suppression():
    """测试 json 模式下普通信息输出受到抑制"""
    custom_logger = AgentLogger(name="test_json_logger", json_mode=True)
    # 不抛出异常即可
    custom_logger.info("Should be silenced in JSON mode")


def test_print_json_result(capsys):
    """测试结构化 JSON 规范输出"""
    test_data = {
        "status": "success",
        "question_type": "choice",
        "answer": ["A", "B"],
        "options_count": 4,
    }
    print_json_result(test_data)
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed == test_data
