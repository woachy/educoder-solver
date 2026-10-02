"""智能题型探测与统一提取路由 (Detector & Dispatcher).

负责自动分析当前激活页面的 DOM 拓扑结构与关键特征，实现：
- 零人工干预自动识别题型 (单选、多选、判断、填空、编程实训)
- 调度对应的专用提取器完成高保真信息抽取
- 对外输出标准化统一结构 QuestionData
"""

from typing import Any, Optional
from bs4 import BeautifulSoup

from src.extractor.base import (
    BaseExtractor,
    QuestionData,
    QuestionType,
    get_page_html,
)
from src.extractor.blank import BlankExtractor
from src.extractor.choice import ChoiceExtractor
from src.extractor.practical import PracticalExtractor
from src.utils.logger import logger


def detect_question_type(page_or_html: Any) -> QuestionType:
    """自动分析页面 DOM 特征，精准探测题目类型。

    Args:
        page_or_html: Playwright Page 对象、Mock 对象或 HTML 字符串

    Returns:
        QuestionType: 探测出的题目类型枚举
    """
    try:
        # 1. 优先探测编程实训题 (包含在线 Monaco/Ace 编辑器或双栏实训布局)
        practical_extractor = PracticalExtractor()
        if practical_extractor.can_extract(page_or_html):
            logger.info("题型探测结果: 编程实训题 (PRACTICAL)")
            return QuestionType.PRACTICAL

        html = get_page_html(page_or_html)
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text()

        # 2. 探测客观题 (单选 / 多选 / 判断)
        choice_extractor = ChoiceExtractor()
        if choice_extractor.can_extract(page_or_html):
            # 细分客观题子类型
            if any(k in text for k in ["【判断题】", "(判断题)", "[判断题]", "判断正误"]):
                logger.info("题型探测结果: 判断题 (JUDGMENT)")
                return QuestionType.JUDGMENT

            if soup.find("input", attrs={"type": "checkbox"}) or any(
                k in text for k in ["【多选题】", "(多选题)", "[多选题]", "多项选择题", "多选"]
            ):
                logger.info("题型探测结果: 多选题 (MULTIPLE_CHOICE)")
                return QuestionType.MULTIPLE_CHOICE

            # 检查选项是否恰为对/错两项
            options = soup.select(".option-item, .ant-radio-wrapper, .choice-option, label.option")
            if len(options) == 2:
                opts_text = [o.get_text(strip=True) for o in options]
                if any(any(j in ot for j in ["正确", "错误", "对", "错"]) for ot in opts_text):
                    logger.info("题型探测结果: 判断题 (JUDGMENT)")
                    return QuestionType.JUDGMENT

            logger.info("题型探测结果: 单选题 (CHOICE)")
            return QuestionType.CHOICE

        # 3. 探测填空题
        blank_extractor = BlankExtractor()
        if blank_extractor.can_extract(page_or_html):
            logger.info("题型探测结果: 填空题 (BLANK)")
            return QuestionType.BLANK

    except Exception as e:
        logger.warning(f"题型自动探测过程出现异常: {e}")

    logger.warning("未能精确匹配已知题型特征，归类为 UNKNOWN")
    return QuestionType.UNKNOWN


def extract_question(page_or_html: Any, force_type: Optional[QuestionType] = None) -> QuestionData:
    """统一题目提取入口。

    自动探测页面题型并路由至专有提取器，输出结构化 QuestionData。

    Args:
        page_or_html: Playwright Page 实例、Mock 对象或 HTML 字符串
        force_type: 可选，强制指定题型而不进行自动探测

    Returns:
        QuestionData: 结构化题目数据模型
    """
    target_type = force_type or detect_question_type(page_or_html)

    if target_type in (QuestionType.CHOICE, QuestionType.MULTIPLE_CHOICE, QuestionType.JUDGMENT):
        extractor = ChoiceExtractor()
        data = extractor.extract(page_or_html)
        # 保持与指定类型或探测类型一致
        if force_type:
            data.type = force_type
        return data

    elif target_type == QuestionType.BLANK:
        extractor = BlankExtractor()
        return extractor.extract(page_or_html)

    elif target_type == QuestionType.PRACTICAL:
        extractor = PracticalExtractor()
        return extractor.extract(page_or_html)

    else:
        # UNKNOWN 类型兜底：尝试依次用 Choice -> Blank -> Practical 抽取
        logger.info("未识别题型，尝试通用抽取兜底...")
        for ext in [ChoiceExtractor(), BlankExtractor(), PracticalExtractor()]:
            try:
                if ext.can_extract(page_or_html):
                    return ext.extract(page_or_html)
            except Exception:
                continue

        # 最终纯文本兜底
        html = get_page_html(page_or_html)
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text("\n", strip=True)
        return QuestionData(
            type=QuestionType.UNKNOWN,
            title="未知题型页面",
            description=text[:500],
            metadata={"raw_length": len(text)},
        )
