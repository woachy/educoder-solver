"""试卷型与复合客观/填空题拟真执行器 (Paper Action Executor).

支持试卷型大题与多题连排页面的批量拟真作答与统一评测：
1. 批量分发：按子题序号依次解析客观选择（单选/多选/判断）与填空输入。
2. 容器级作用域隔离：在各个子题容器内精准查找对应选项与输入框，杜绝多题间的元素抢占与串题。
3. 状态感知与防反选：客观题自动感知已选中状态，避免反向取消勾选；填空题分发 input/change/blur 确保响应式框架同步。
4. 评测联动：支持 auto_eval 自动触发评测并监听结果。
5. 标准化回执：返回每道子题的操作状态与总通过情况。
"""

import json
from typing import Any, Dict, List, Optional, Union
from playwright.sync_api import ElementHandle, Page

from src.executor.blank_action import _fill_single_blank
from src.executor.choice_action import _matches_target
from src.executor.eval_action import EvaluationManager
from src.executor.modal_sweeper import dismiss_blocking_overlays
from src.extractor.base import BlankItem, ChoiceOption, QuestionData, QuestionType, SubQuestion
from src.extractor.detector import extract_question
from src.extractor.paper import OPTION_SELECTORS, SUB_QUESTION_CONTAINER_SELECTORS
from src.utils.delay import random_delay
from src.utils.logger import logger


def _find_sub_containers(page: Page) -> List[ElementHandle]:
    """在活动页面中定位所有子题的 DOM 容器"""
    for sel in SUB_QUESTION_CONTAINER_SELECTORS[:6]:
        try:
            nodes = page.query_selector_all(sel)
            if len(nodes) >= 2:
                return list(nodes)
        except Exception:
            continue

    # 回退到 radio-group
    try:
        groups = page.query_selector_all(".ant-radio-group, .ant-checkbox-group")
        if len(groups) >= 2:
            return list(groups)
    except Exception:
        pass

    return []


def _solve_sub_choice(
    page: Page,
    container: Optional[ElementHandle],
    sub_q: SubQuestion,
    target_answer: Union[str, List[str]],
) -> Dict[str, Any]:
    """处理单个子选择题或判断题的选项点击"""
    targets = [str(target_answer)] if isinstance(target_answer, str) else [str(t) for t in target_answer]
    is_judgment = sub_q.type == QuestionType.JUDGMENT

    clicked_options: List[str] = []
    skipped_options: List[str] = []
    failed_options: List[str] = []

    # 优先在容器内查找选项元素
    option_elems: List[ElementHandle] = []
    if container:
        for sel in OPTION_SELECTORS[:6]:
            try:
                found = container.query_selector_all(sel)
                if found:
                    option_elems = list(found)
                    break
            except Exception:
                continue

        if not option_elems:
            try:
                option_elems = list(container.query_selector_all("input[type='radio'], input[type='checkbox']"))
            except Exception:
                pass

    for target in targets:
        clean_target = target.strip()
        # 寻找匹配的 ChoiceOption
        matched_opt: Optional[ChoiceOption] = None
        matched_idx: Optional[int] = None
        for idx, opt in enumerate(sub_q.options):
            if _matches_target(opt, clean_target, is_judgment):
                matched_opt = opt
                matched_idx = idx
                break

        if not matched_opt and not sub_q.options:
            # 容错：按字母序号直接对应下标 (A->0, B->1, C->2, D->3)
            if clean_target.upper() in ["A", "B", "C", "D", "E", "F"]:
                matched_idx = ord(clean_target.upper()) - ord("A")

        target_elem = None
        if matched_idx is not None and option_elems and matched_idx < len(option_elems):
            target_elem = option_elems[matched_idx]
        elif container:
            # 通过文本匹配元素
            try:
                target_elem = container.query_selector(f":has-text('{clean_target}')")
            except Exception:
                pass

        if target_elem:
            try:
                # 检查是否已勾选
                is_checked = False
                try:
                    if hasattr(target_elem, "is_checked"):
                        is_checked = target_elem.is_checked()
                    else:
                        cls = target_elem.get_attribute("class") or ""
                        is_checked = any(c in cls for c in ["checked", "active", "is-checked", "ant-radio-checked"])
                except Exception:
                    pass

                if is_checked:
                    skipped_options.append(clean_target)
                    continue

                random_delay(0.2, 0.5)
                target_elem.click()
                clicked_options.append(clean_target)
            except Exception as ce:
                logger.debug(f"点击子题 [{sub_q.index}] 选项 {clean_target} 异常: {ce}")
                failed_options.append(clean_target)
        else:
            failed_options.append(clean_target)

    return {
        "status": "success" if (clicked_options or skipped_options) else "failed",
        "clicked": clicked_options,
        "already_selected": skipped_options,
        "failed": failed_options,
    }


def _solve_sub_blank(
    page: Page,
    container: Optional[ElementHandle],
    sub_q: SubQuestion,
    target_answer: Union[str, List[str]],
) -> Dict[str, Any]:
    """处理单个子填空题的输入槽位填充"""
    answers = [target_answer] if isinstance(target_answer, str) else list(target_answer)

    input_elems: List[ElementHandle] = []
    if container:
        try:
            input_elems = list(
                container.query_selector_all(
                    "input.blank-input, input.answer-input, input.fill-input, .blank-item input, input[type='text']:not(.search-input)"
                )
            )
        except Exception:
            pass

    filled_count = 0
    details = []

    for idx, ans in enumerate(answers):
        ans_str = str(ans)
        slot_status = "failed"
        if idx < len(input_elems):
            elem = input_elems[idx]
            random_delay(0.1, 0.3)
            if _fill_single_blank(page, elem, ans_str):
                slot_status = "filled"
                filled_count += 1
        details.append({"slot_index": idx + 1, "answer": ans_str, "status": slot_status})

    return {
        "status": "success" if filled_count > 0 else "failed",
        "filled_count": filled_count,
        "total_slots": len(answers),
        "details": details,
    }


def submit_paper_answers(
    page: Page,
    answers: Union[Dict[Any, Any], List[Any], str],
    question_data: Optional[QuestionData] = None,
    auto_eval: bool = False,
    eval_manager: Optional[EvaluationManager] = None,
    timeout: int = 60,
) -> Dict[str, Any]:
    """批量提交试卷型与复合客观/填空题的所有子题目答案。

    Args:
        page: Playwright Page 实例
        answers: 待作答的答案映射或列表，格式支持：
            - Dict: {"1": "A", "2": ["ans1", "ans2"], "3": "C"} 或 {1: "A", 2: "B"}
            - List: ["A", ["ans1", "ans2"], "C"] (依序匹配第 1、2、3 题)
            - JSON 字符串: 序列化的上述结构
        question_data: 可选的预提取 QuestionData
        auto_eval: 是否在全部填写完毕后自动触发评测监听 (默认 False)
        eval_manager: 可选的 EvaluationManager 实例
        timeout: 评测超时秒数 (默认 60s)

    Returns:
        dict: 批量作答结果回执
    """
    if isinstance(answers, str):
        try:
            answers = json.loads(answers)
        except Exception as e:
            logger.error(f"解析 answers JSON 字符串失败: {e}")
            return {"status": "error", "message": f"解析 answers JSON 失败: {e}"}

    # 1. 规范化 answers 为 Dict[int, Any] (1-indexed)
    normalized_answers: Dict[int, Any] = {}
    if isinstance(answers, list):
        for idx, item in enumerate(answers):
            normalized_answers[idx + 1] = item
    elif isinstance(answers, dict):
        for k, v in answers.items():
            try:
                normalized_answers[int(k)] = v
            except ValueError:
                pass

    if not normalized_answers:
        return {"status": "error", "message": "未提供任何有效答案或答案格式不正确"}

    # 2. 清理阻塞弹窗与遮罩
    dismiss_blocking_overlays(page)

    # 3. 提取题目元数据
    if question_data is None:
        try:
            question_data = extract_question(page)
        except Exception as e:
            logger.warning(f"自动提取试卷题目异常: {e}")
            question_data = QuestionData(type=QuestionType.EXAM_PAPER)

    sub_questions = question_data.sub_questions
    sub_containers = _find_sub_containers(page)

    logger.info(
        f"开始批量作答试卷型大题: 待作答题数={len(normalized_answers)}, 识别子题数={len(sub_questions)}, 页面容器数={len(sub_containers)}"
    )

    results: List[Dict[str, Any]] = []
    success_count = 0

    # 4. 逐道子题分发作答
    for sub_idx, sub_ans in normalized_answers.items():
        # 寻找对应的 SubQuestion
        sub_q = None
        for sq in sub_questions:
            if sq.index == sub_idx:
                sub_q = sq
                break

        if not sub_q:
            # 自动推断或构造兜底 SubQuestion
            sub_q = SubQuestion(
                index=sub_idx,
                type=QuestionType.BLANK if isinstance(sub_ans, list) else QuestionType.CHOICE,
                title=f"子题目 #{sub_idx}",
            )

        container_elem = sub_containers[sub_idx - 1] if (sub_idx - 1 < len(sub_containers)) else None

        if sub_q.type in (QuestionType.CHOICE, QuestionType.MULTIPLE_CHOICE, QuestionType.JUDGMENT):
            sub_res = _solve_sub_choice(page, container_elem, sub_q, sub_ans)
        elif sub_q.type == QuestionType.BLANK:
            sub_res = _solve_sub_blank(page, container_elem, sub_q, sub_ans)
        else:
            # 兜底根据 sub_ans 类型判定
            if isinstance(sub_ans, list):
                sub_res = _solve_sub_blank(page, container_elem, sub_q, sub_ans)
            else:
                sub_res = _solve_sub_choice(page, container_elem, sub_q, sub_ans)

        sub_res["sub_index"] = sub_idx
        sub_res["sub_type"] = sub_q.type.value if hasattr(sub_q.type, "value") else str(sub_q.type)
        results.append(sub_res)

        if sub_res.get("status") == "success":
            success_count += 1

    total_submitted = len(normalized_answers)
    all_ok = success_count == total_submitted

    response_payload: Dict[str, Any] = {
        "status": "success" if all_ok else "partial_success",
        "total_submitted": total_submitted,
        "success_count": success_count,
        "details": results,
        "message": f"已完成 {success_count}/{total_submitted} 道子题目的拟真输入",
    }

    # 5. 联动触发评测与监听
    if auto_eval:
        logger.info("已配置 auto_eval=True，正在触发试卷评测监听...")
        eval_mgr = eval_manager or EvaluationManager()
        eval_res = eval_mgr.trigger_and_wait_eval(page, timeout_seconds=timeout)
        response_payload["eval_result"] = eval_res
        response_payload["passed"] = eval_res.get("passed", False)
        response_payload["pass_ratio"] = eval_res.get("pass_ratio", "")
        response_payload["diff_hint"] = eval_res.get("diff_hint", "")

    return response_payload
