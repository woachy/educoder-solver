"""文本填空题拟真注入器 (Blank Action Executor).

支持头歌平台各类行内与列表式填空题的拟真自动化输入：
1. 槽位序号匹配：按输入框顺序与答案列表依次对应。
2. 拟真事件交互：focus -> 模拟键盘 fill -> 触发 blur / change / input 事件保证 Vue/React 双向数据绑定生效。
3. 拟真微延迟：不同输入槽位之间插入随机间隔 (0.3s ~ 0.8s)。
4. 结构化回执：返回包含每个槽位填入结果的标准化字典。
"""

from typing import Any, Dict, List, Optional
from playwright.sync_api import ElementHandle, Page

from src.extractor.base import BlankItem, QuestionData, QuestionType
from src.extractor.blank import BlankExtractor
from src.extractor.detector import extract_question
from src.utils.delay import random_delay
from src.utils.logger import logger


def _find_blank_input_elements(page: Page, question_data: Optional[QuestionData] = None) -> List[ElementHandle]:
    """定位页面中的所有填空输入框元素。"""
    elements: List[ElementHandle] = []

    # 1. 优先使用常见填空输入框选择器在页面中全局检索
    candidate_selectors = [
        "input.blank-input",
        "input.answer-input",
        "input.fill-input",
        ".blank-item input",
        ".blank-fill input",
        ".fill-blank input",
        ".fill-in input",
        ".subject-stem input[type='text']",
        ".blank-question input[type='text']",
        "input[type='text']:not(.search-input):not(.filter-input)",
    ]

    for selector in candidate_selectors:
        try:
            found = page.query_selector_all(selector)
            if found:
                elements = list(found)
                break
        except Exception:
            continue

    if elements:
        return elements

    # 2. 如果全局选择器未匹配到，且 question_data 中已有填空项特定选择器
    if question_data and question_data.blanks:
        for b in question_data.blanks:
            if b.selector:
                try:
                    el = page.query_selector(b.selector)
                    if el and el not in elements:
                        elements.append(el)
                except Exception:
                    pass

    return elements


def _fill_single_blank(page: Page, element: ElementHandle, answer_text: str) -> bool:
    """对单个填空输入框执行精准拟真填入与双向绑定事件触发。"""
    try:
        # 1. 拟真聚焦
        try:
            element.focus()
        except Exception:
            pass

        random_delay(0.1, 0.25)

        # 2. 键入/填充文本
        element.fill(answer_text)

        # 3. 强制分发 input, change 与 blur 事件，确保 Vue / React / Angular 响应式状态感知
        try:
            page.evaluate(
                """(el) => {
                    if (el) {
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                        el.dispatchEvent(new Event('blur', { bubbles: true }));
                    }
                }""",
                element,
            )
        except Exception as e:
            logger.debug(f"双向绑定事件分发异常 (安全容错): {e}")

        return True
    except Exception as e:
        logger.error(f"填入输入框失败: {e}")
        return False


def submit_blank_answer(
    page: Page,
    answers: List[str],
    question_data: Optional[QuestionData] = None,
) -> Dict[str, Any]:
    """提交填空题答案。

    Args:
        page: Playwright Page 实例
        answers: 待填入的答案列表，按槽位顺序对应 (如 ['print', 'input'])
        question_data: 可选的预提取题目数据模型

    Returns:
        dict: 操作回执字典:
            - success (bool): 是否成功填入所有槽位
            - filled_count (int): 实际成功填入的空位数量
            - total_answers (int): 传入的答案总数
            - details (list[dict]): 每个空位的填入详情
            - message (str): 状态说明
    """
    if not answers:
        return {
            "success": False,
            "filled_count": 0,
            "total_answers": 0,
            "details": [],
            "message": "未提供任何待填入答案",
        }

    # 1. 确保获取题目结构
    if question_data is None:
        try:
            question_data = extract_question(page)
        except Exception as e:
            logger.warning(f"自动提取题目失败，使用空结构: {e}")
            question_data = QuestionData(type=QuestionType.BLANK)

    logger.info(f"正在执行填空题答题: 答案项数={len(answers)}")

    # 2. 定位页面上的输入框元素
    input_elements = _find_blank_input_elements(page, question_data)
    logger.info(f"页面共检测到 {len(input_elements)} 个可输入槽位")

    details: List[Dict[str, Any]] = []
    filled_count = 0

    # 3. 逐个槽位拟真填入
    for idx, ans in enumerate(answers):
        slot_index = idx + 1
        detail: Dict[str, Any] = {
            "slot_index": slot_index,
            "answer": str(ans),
            "status": "pending",
        }

        if idx < len(input_elements):
            elem = input_elements[idx]
            logger.info(f"正在填入槽位 [{slot_index}]: '{ans}'")
            success = _fill_single_blank(page, elem, str(ans))
            if success:
                detail["status"] = "filled"
                filled_count += 1
            else:
                detail["status"] = "failed"
                detail["error"] = "fill_failed"
        else:
            logger.warning(f"槽位 [{slot_index}] 超出页面检测到的输入框数量 ({len(input_elements)})")
            detail["status"] = "slot_not_found"

        details.append(detail)

        # 槽位之间拟真微延迟
        if idx < len(answers) - 1:
            random_delay(0.3, 0.8)

    all_filled = filled_count == len(answers)
    result = {
        "success": all_filled,
        "filled_count": filled_count,
        "total_answers": len(answers),
        "total_slots_detected": len(input_elements),
        "details": details,
        "message": (
            f"成功完成所有 {filled_count} 个填空项"
            if all_filled
            else f"部分填空项未成功 (已填入 {filled_count}/{len(answers)})"
        ),
    }

    if all_filled:
        logger.success(result["message"])
    else:
        logger.warning(result["message"])

    return result
