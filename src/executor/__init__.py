"""拟真动作执行引擎与评测监听组件 (Executor Package).

导出核心动作执行器与评测管理器：
- submit_choice_answer: 客观选择题与判断题拟真点击
- submit_blank_answer: 填空题槽位输入与双向绑定触发
- inject_code: 实训题代码快照备份、靶心组装与分级安全注入
- EvaluationManager: 实训评测生命周期监听、结果解析与连续报错自愈熔断器
- dismiss_blocking_overlays: 页面遮挡弹窗与拦截指针事件遮罩清理器
- extract_testcase_diff: 高信息密度测试集 Diff 提取器
- run_solve_cycle: 复合答题流水线 (清理弹窗 -> 注入代码 -> 两阶段评测 -> 提纯Diff)
"""

from src.executor.blank_action import submit_blank_answer
from src.executor.choice_action import submit_choice_answer
from src.executor.diff_extractor import extract_testcase_diff
from src.executor.editor_action import (
    assemble_target_code,
    backup_code_to_file,
    inject_code,
)
from src.executor.eval_action import EvaluationManager
from src.executor.modal_sweeper import dismiss_blocking_overlays
from src.executor.pipeline import run_solve_cycle
from src.executor.terminal_action import (
    inject_terminal_command,
    read_terminal_output,
)

__all__ = [
    "submit_choice_answer",
    "submit_blank_answer",
    "inject_code",
    "backup_code_to_file",
    "assemble_target_code",
    "EvaluationManager",
    "dismiss_blocking_overlays",
    "extract_testcase_diff",
    "run_solve_cycle",
    "inject_terminal_command",
    "read_terminal_output",
]
