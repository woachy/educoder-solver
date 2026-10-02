"""客观选择题与判断题拟真执行器 (Choice Action Executor).

支持单选题、多选题、判断题的拟真自动化交互：
1. 真实拟真延迟：点击前后加入随机微延迟 (0.3s ~ 0.8s)，防止触发风控。
2. 多选防重复取消：点击前比对当前选项的选中状态 (checked/is_checked)，
   仅点击未勾选的目标选项，严禁将已选中的误点取消。
3. 容错选项识别：支持选项标识 (A/B/C/D)、选项正文模糊匹配以及判断题 (对/错/正确/错误/T/F) 别名映射。
4. 结构化结果回执：输出包含操作明细、当前选中状态的标准化字典。
"""

import re
from typing import Any, Dict, List, Optional, Set
from playwright.sync_api import ElementHandle, Locator, Page

from src.extractor.base import ChoiceOption, QuestionData, QuestionType
from src.extractor.detector import extract_question
from src.utils.delay import random_delay
from src.utils.logger import logger


# 判断题常见真/假等价映射集
TRUE_ALIASES = {"对", "正确", "T", "TRUE", "是", "1", "A"}
FALSE_ALIASES = {"错", "错误", "F", "FALSE", "否", "0", "B"}


def _normalize_string(text: str) -> str:
    """标准化字符串：去除首尾空白并转为大写"""
    return text.strip().upper() if text else ""


def _matches_target(opt: ChoiceOption, target: str, is_judgment: bool = False) -> bool:
    """判断单个选项是否匹配目标答案项。

    Args:
        opt: 提取到的选项数据模型
        target: 用户/Agent 指定的目标选项字符串 (如 'A', '正确', '列表是可变序列')
        is_judgment: 是否为判断题

    Returns:
        bool: 是否匹配
    """
    target_clean = target.strip()
    target_norm = _normalize_string(target)
    opt_id_norm = _normalize_string(opt.id)
    opt_text_clean = opt.text.strip()

    # 1. 选项 ID 精确匹配 (如 'A' == 'A')
    if opt_id_norm and opt_id_norm == target_norm:
        return True

    # 2. 判断题语义别名匹配
    if is_judgment:
        if target_norm in TRUE_ALIASES and (opt_id_norm in TRUE_ALIASES or opt_text_clean in {"对", "正确", "True", "T"}):
            return True
        if target_norm in FALSE_ALIASES and (opt_id_norm in FALSE_ALIASES or opt_text_clean in {"错", "错误", "False", "F"}):
            return True

    # 3. 选项正文完全匹配或包含匹配
    if opt_text_clean and target_clean:
        if target_clean == opt_text_clean:
            return True
        if target_clean in opt_text_clean:
            return True

    return False


def _check_element_is_checked(page: Page, opt: ChoiceOption) -> bool:
    """检查页面中指定选项当前是否已被勾选/选中。"""
    # 1. 优先使用提取器感知到的初始选中状态作为基准
    current_selected = bool(opt.selected)

    # 2. 若有可用选择器，在活跃页面中探测实际 DOM 状态
    if opt.selector:
        try:
            elem = page.query_selector(opt.selector)
            if elem:
                # 检查 input 元素
                input_elem = elem if "input" in opt.selector else elem.query_selector("input")
                if input_elem and hasattr(input_elem, "is_checked"):
                    try:
                        checked_val = input_elem.is_checked()
                        if isinstance(checked_val, bool):
                            return checked_val
                    except Exception:
                        pass

                # 检查类名中的选中标识 (严格验证字符串类型，防止 Mock 对象虚假真值)
                class_attr = elem.get_attribute("class")
                if isinstance(class_attr, str):
                    selected_classes = {
                        "checked",
                        "selected",
                        "active",
                        "ant-radio-checked",
                        "ant-checkbox-checked",
                        "is-checked",
                        "el-radio__input.is-checked",
                    }
                    classes_set = set(class_attr.split())
                    if classes_set.intersection(selected_classes):
                        return True
                    for sel_cls in selected_classes:
                        if sel_cls in class_attr:
                            return True

                # 检查 aria-checked
                aria = elem.get_attribute("aria-checked")
                if isinstance(aria, str) and aria.lower() == "true":
                    return True
        except Exception as e:
            logger.debug(f"检查选项 {opt.id} 选中状态异常: {e}")

    # 3. 兜底尝试全局查找对应 input
    try:
        inputs = page.query_selector_all("input[type='radio'], input[type='checkbox']")
        if opt.locator_index is not None and opt.locator_index < len(inputs):
            inp = inputs[opt.locator_index]
            if hasattr(inp, "is_checked") and callable(inp.is_checked):
                checked_val = inp.is_checked()
                if isinstance(checked_val, bool):
                    return checked_val
    except Exception:
        pass

    return current_selected


def _click_option_element(page: Page, opt: ChoiceOption) -> bool:
    """安全点击页面中的选项元素，兼容自定义组件与隐藏 input。"""
    # 策略 1: 使用 opt.selector 点击
    if opt.selector:
        try:
            elem = page.query_selector(opt.selector)
            if elem:
                # 拟真随机微延迟
                random_delay(0.3, 0.8)
                elem.click()
                return True
        except Exception as e:
            logger.debug(f"使用 selector 点击选项 {opt.id} 失败: {e}")

    # 策略 2: 使用 locator_index 点击 input 对应的父容器/label
    try:
        inputs = page.query_selector_all("input[type='radio'], input[type='checkbox']")
        if opt.locator_index is not None and opt.locator_index < len(inputs):
            inp = inputs[opt.locator_index]
            random_delay(0.3, 0.8)
            try:
                inp.click()
                return True
            except Exception:
                # 若 input 隐藏不可点，点击其父级容器
                parent = page.evaluate_handle("el => el.parentElement", inp)
                if parent:
                    parent.as_element().click()
                    return True
    except Exception as e:
        logger.debug(f"按下标点击选项 {opt.id} 失败: {e}")

    # 策略 3: 使用文本定位器点击
    try:
        loc = page.locator(f"text={opt.text[:20]}").first
        if loc and loc.count() > 0:
            random_delay(0.3, 0.8)
            loc.click()
            return True
    except Exception as e:
        logger.debug(f"按文本点击选项 {opt.id} 失败: {e}")

    return False


def submit_choice_answer(
    page: Page,
    target_options: List[str],
    question_data: Optional[QuestionData] = None,
) -> Dict[str, Any]:
    """提交客观选择题/多选题/判断题答案。

    核心逻辑：
    1. 动态感知题型与选项列表（若未传入 question_data，则从当前页面自动提取）。
    2. 多选防重复取消：逐一检查目标选项是否已选中；若已选中则严禁再次点击。
    3. 仅对未选中的目标选项下发拟真点击，并在每次点击间插入 0.3s ~ 0.8s 随机微延迟。

    Args:
        page: Playwright Page 实例
        target_options: 目标选项列表，如 ['A', 'B'] 或 ['对']
        question_data: 可选的预提取题目数据模型

    Returns:
        dict: 操作回执字典:
            - success (bool): 是否成功处理所有目标选项
            - question_type (str): 题型名称
            - target_options (list[str]): 目标选项输入
            - clicked_options (list[str]): 实际执行了点击的选项 ID
            - already_selected (list[str]): 原本已处于选中态跳过点击的选项 ID
            - current_states (dict): 各选项当前选中状态字典 {opt_id: bool}
            - message (str): 详细状态说明
    """
    if not target_options:
        return {
            "success": False,
            "question_type": "unknown",
            "target_options": [],
            "clicked_options": [],
            "already_selected": [],
            "current_states": {},
            "message": "未指定任何目标选项",
        }

    # 1. 确保获取结构化题目数据
    if question_data is None:
        try:
            question_data = extract_question(page)
        except Exception as e:
            logger.warning(f"自动提取题目失败，使用空结构: {e}")
            question_data = QuestionData(type=QuestionType.CHOICE)

    q_type = question_data.type
    is_judgment = q_type == QuestionType.JUDGMENT
    options = question_data.options

    logger.info(f"正在执行客观题答题: 题型={q_type.value}, 目标选项={target_options}")

    clicked_options: List[str] = []
    already_selected: List[str] = []
    current_states: Dict[str, bool] = {}
    matched_opt_ids: Set[str] = set()

    # 2. 遍历现有选项，比对目标与状态
    for opt in options:
        opt_id = opt.id
        is_matched = any(_matches_target(opt, target, is_judgment) for target in target_options)

        # 探测当前在页面中的实际选中状态
        is_checked = _check_element_is_checked(page, opt)
        current_states[opt_id] = is_checked

        if is_matched:
            matched_opt_ids.add(opt_id)
            if is_checked:
                # 【核心红线】若目标选项已处于选中状态，严禁再次点击导致误取消
                logger.info(f"选项 [{opt_id}] 当前已处于勾选状态，跳过点击以防止取消选中")
                already_selected.append(opt_id)
            else:
                # 未选中：下发拟真点击
                logger.info(f"正在拟真点击选项 [{opt_id}] ({opt.text[:20]}...)")
                click_success = _click_option_element(page, opt)
                if click_success:
                    clicked_options.append(opt_id)
                    current_states[opt_id] = True
                else:
                    logger.warning(f"未能成功点击选项 [{opt_id}]")

    # 3. 校验是否有未匹配到的目标选项
    unmatched_targets = []
    for target in target_options:
        if not any(_matches_target(opt, target, is_judgment) for opt in options):
            unmatched_targets.append(target)

    # 如果有完全未匹配到的目标且页面有直接同名 input/label，尝试兜底定位
    if unmatched_targets:
        for t in unmatched_targets:
            logger.warning(f"选项列表中未找到目标项 '{t}'，尝试直接定位页面文本...")
            try:
                loc = page.locator(f"text={t}").first
                if loc and loc.count() > 0:
                    random_delay(0.3, 0.8)
                    loc.click()
                    clicked_options.append(t)
                    current_states[t] = True
            except Exception as e:
                logger.debug(f"直接文本定位点击失败: {e}")

    all_targets_handled = len(clicked_options) + len(already_selected) >= len(target_options)

    result = {
        "success": all_targets_handled,
        "question_type": q_type.value if hasattr(q_type, "value") else str(q_type),
        "target_options": target_options,
        "clicked_options": clicked_options,
        "already_selected": already_selected,
        "current_states": current_states,
        "message": (
            f"成功处理选项: 已点击 {clicked_options}, 原已选中 {already_selected}"
            if all_targets_handled
            else f"部分选项未成功处理 (目标={target_options}, 已点击={clicked_options}, 已选中={already_selected})"
        ),
    }

    logger.success(result["message"])
    return result
