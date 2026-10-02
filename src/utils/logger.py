"""日志记录与结构化输出工具 (Logger & JSON Formatter).

基于 rich 库实现高可读性、带高亮和格式化的终端输出，
同时支持纯净结构化 JSON 输出模式以适配 AI Agent 自动化流程解析。
"""

import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, Optional, Union
from rich.console import Console
from rich.text import Text

from src.config import config

if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


class AgentLogger:
    """Agent 日志器，兼顾终端交互视觉美感与自动化管道 JSON 解析"""

    LEVELS = {
        "DEBUG": 10,
        "INFO": 20,
        "SUCCESS": 25,
        "WARNING": 30,
        "ERROR": 40,
        "CRITICAL": 50,
    }

    def __init__(self, name: str = "educoder_solver", json_mode: Optional[bool] = None):
        self.name = name
        self._json_mode = (
            json_mode
            if json_mode is not None
            else config.log.json_mode
        )
        # stderr 控制台用于输出人类可读日志，避免污染 stdout 的纯净 JSON 数据流
        self.stderr_console = Console(stderr=True)
        self.stdout_console = Console()
        self.level_num = self.LEVELS.get(config.log.level, 20)

    @property
    def json_mode(self) -> bool:
        return self._json_mode

    @json_mode.setter
    def json_mode(self, value: bool) -> None:
        self._json_mode = value

    def set_level(self, level_name: str) -> None:
        """动态设置日志过滤级别"""
        self.level_num = self.LEVELS.get(level_name.upper(), 20)

    def _should_log(self, level: str) -> bool:
        return self.LEVELS.get(level, 20) >= self.level_num

    def _format_time(self) -> str:
        return datetime.now().strftime("%H:%M:%S.%f")[:-3]

    def debug(self, msg: str, **kwargs: Any) -> None:
        if self._should_log("DEBUG") and not self._json_mode:
            time_str = self._format_time()
            self.stderr_console.print(f"[dim]{time_str}[/dim] [bold cyan]DEBUG[/bold cyan]   {msg}", **kwargs)

    def info(self, msg: str, **kwargs: Any) -> None:
        if self._should_log("INFO") and not self._json_mode:
            time_str = self._format_time()
            self.stderr_console.print(f"[dim]{time_str}[/dim] [bold blue]INFO[/bold blue]    {msg}", **kwargs)

    def success(self, msg: str, **kwargs: Any) -> None:
        if self._should_log("SUCCESS") and not self._json_mode:
            time_str = self._format_time()
            self.stderr_console.print(f"[dim]{time_str}[/dim] [bold green]SUCCESS[/bold green] {msg}", **kwargs)

    def warning(self, msg: str, **kwargs: Any) -> None:
        if self._should_log("WARNING") and not self._json_mode:
            time_str = self._format_time()
            self.stderr_console.print(f"[dim]{time_str}[/dim] [bold yellow]WARN[/bold yellow]    {msg}", **kwargs)

    def error(self, msg: str, **kwargs: Any) -> None:
        if self._should_log("ERROR"):
            time_str = self._format_time()
            self.stderr_console.print(f"[dim]{time_str}[/dim] [bold red]ERROR[/bold red]   {msg}", **kwargs)


# 默认全局 logger 实例
logger = AgentLogger()


def get_logger(name: str = "educoder_solver", json_mode: Optional[bool] = None) -> AgentLogger:
    """获取指定名称的 Logger 实例"""
    return AgentLogger(name=name, json_mode=json_mode)


def print_json_result(data: Union[Dict[str, Any], list, Any], exit_code: Optional[int] = None) -> None:
    """向标准输出 (stdout) 打印结构化 JSON 格式结果。

    规范要求：CLI 工具对外输出必须保持格式整洁的 JSON，便于 AI Agent 无损解析并推演。
    """
    try:
        json_output = json.dumps(data, ensure_ascii=False, indent=2)
    except Exception as e:
        json_output = json.dumps({
            "status": "error",
            "message": f"JSON serialization failed: {str(e)}"
        }, ensure_ascii=False, indent=2)
    
    try:
        print(json_output, flush=True)
    except UnicodeEncodeError:
        try:
            sys.stdout.buffer.write((json_output + "\n").encode("utf-8", errors="replace"))
            sys.stdout.buffer.flush()
        except Exception:
            print(json.dumps(data, ensure_ascii=True, indent=2), flush=True)

    if exit_code is not None:
        sys.exit(exit_code)
