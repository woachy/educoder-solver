"""基础题目数据模型与提取器抽象基类 (Base Extractor & Data Models).

定义头歌支持的各类题型、标准化选项、填空位、实训代码片段与统一题目数据结构。
保证全题型结构化输出可无损序列化为 JSON，供上层 AI Agent 解析推演。
"""

import json
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class QuestionType(str, Enum):
    """题目类型枚举"""
    CHOICE = "choice"                     # 单选题
    MULTIPLE_CHOICE = "multiple_choice"   # 多选题
    JUDGMENT = "judgment"                 # 判断题
    BLANK = "blank"                       # 填空题
    PRACTICAL = "practical"               # 编程实训题
    EXAM_PAPER = "exam_paper"             # 试卷型 / 复合多题连排 (单选/填空等混合题)
    UNKNOWN = "unknown"                   # 未知题型


@dataclass
class ChoiceOption:
    """客观选择题/判断题选项模型"""
    id: str                               # 选项标识，如 'A', 'B', 'C', 'D' 或 '对', '错'
    text: str                             # 选项正文文本
    selected: bool = False                # 当前在页面中是否处于已选中状态
    selector: Optional[str] = None        # CSS 选择器或元素定位描述
    locator_index: Optional[int] = None   # 在同一选项组内的下标 (0-indexed)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BlankItem:
    """填空题空位模型"""
    index: int                            # 空位序号 (1-indexed)
    hint: str = ""                        # 占位提示或空位描述 (例如 placeholder)
    prefix_text: str = ""                 # 题干中空位前置上下文文字
    suffix_text: str = ""                 # 题干中空位后置上下文文字
    current_value: str = ""               # 当前输入框已有的文本内容
    selector: Optional[str] = None        # 输入框 CSS 选择器

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SubQuestion:
    """试卷型/复合大题中的子题目模型"""
    index: int                            # 子题序号 (1-indexed)
    type: QuestionType                    # 子题类型 (choice, multiple_choice, judgment, blank)
    title: str = ""                       # 子题题干
    description: str = ""                 # 子题描述 / 上下文
    options: List[ChoiceOption] = field(default_factory=list) # 客观选项列表 (选择/判断题)
    blanks: List[BlankItem] = field(default_factory=list)     # 填空输入槽位列表 (填空题)
    latex_formulas: List[str] = field(default_factory=list)   # 提纯后的 LaTeX 表达式列表 (如关系代数公式)
    selector: Optional[str] = None        # 子题容器选择器
    metadata: Dict[str, Any] = field(default_factory=dict)    # 子题元数据

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "type": self.type.value if isinstance(self.type, QuestionType) else str(self.type),
            "title": self.title,
            "description": self.description,
            "options": [opt.to_dict() for opt in self.options],
            "blanks": [b.to_dict() for b in self.blanks],
            "latex_formulas": self.latex_formulas,
            "selector": self.selector,
            "metadata": self.metadata,
        }


@dataclass
class PracticalDetails:
    """编程实训题专属详情模型"""
    task_description: str = ""            # 任务描述
    requirements: str = ""                # 编程要求 / 通关要求
    sample_io: str = ""                   # 输入输出样例与测试说明
    eval_instructions: str = ""           # 评测规则与注意事项
    code: str = ""                        # 当前编辑器完整代码
    prefix_code: str = ""                 # Begin 标记之前的不可变代码前缀
    target_code: str = ""                 # Begin 与 End 之间的待编写核心区域
    suffix_code: str = ""                 # End 标记之后的不可变代码后缀
    language: str = ""                    # 编程语言 (python, c, cpp, java, sql 等)
    has_target_marker: bool = False       # 是否检测到 Begin-End 区域标记
    editor_type: str = "monaco"           # 编辑器类型: monaco / ace / textarea
    is_blank_slate: bool = False          # 是否为完全无初始模板、需从头编写的空白开卷题

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class QuestionData:
    """统一题目数据模型 (Unified Question Schema).

    对外输出结构化数据，确保 AI 代理可无损解析题意并输出解题动作。
    """
    type: QuestionType
    title: str = ""
    description: str = ""
    options: List[ChoiceOption] = field(default_factory=list)
    blanks: List[BlankItem] = field(default_factory=list)
    sub_questions: List[SubQuestion] = field(default_factory=list)
    practical_details: Optional[PracticalDetails] = None
    raw_html: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """将题目数据无损转换为字典格式"""
        res = {
            "type": self.type.value if isinstance(self.type, QuestionType) else str(self.type),
            "title": self.title,
            "description": self.description,
            "options": [opt.to_dict() for opt in self.options],
            "blanks": [b.to_dict() for b in self.blanks],
            "sub_questions": [sq.to_dict() for sq in self.sub_questions],
            "practical_details": self.practical_details.to_dict() if self.practical_details else None,
            "metadata": self.metadata,
        }
        return res

    def to_json(self, indent: int = 2) -> str:
        """转换为标准格式化 JSON 字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


def get_page_html(page_or_html: Any) -> str:
    """统一获取页面或 HTML 字符串内容。

    兼容 Playwright Page 实例、具有 content() 方法的 Mock 对象以及普通 HTML 字符串。
    """
    if hasattr(page_or_html, "content") and callable(page_or_html.content):
        return page_or_html.content()
    elif isinstance(page_or_html, str):
        return page_or_html
    elif hasattr(page_or_html, "prettify"):  # BeautifulSoup
        return str(page_or_html)
    raise TypeError(f"无法获取页面内容，不支持的类型: {type(page_or_html)}")


class BaseExtractor(ABC):
    """提取器抽象基类"""

    @abstractmethod
    def can_extract(self, page_or_html: Any) -> bool:
        """判断当前页面是否适用于本提取器"""
        pass

    @abstractmethod
    def extract(self, page_or_html: Any) -> QuestionData:
        """从页面提取出结构化 QuestionData"""
        pass
