"""关卡拓扑感知与多关卡导航回退器 (Multi-stage Topology & Navigator).

负责头歌多关卡实训大题的关卡拓扑探查、状态感知与按序导航自愈：
1. 拓扑感知：检测大题总关卡数、当前所处关卡序号 (例如 第 2 关 / 共 2 关)。
2. 回退感知 (Rollback Perception)：当大题包含多个关卡 (如 0/2 完成) 且浏览器默认停在后续关卡时，
   自动检测并按序回退导航至首个未完成关卡 (第 1 关)，避免错位作答。
3. 按序流转：提供上一关 (trigger_prev_stage)、下一关 (trigger_next_stage) 与任意目标关卡直达 (navigate_to_stage)。
"""

import re
import time
from typing import Any, Dict, List, Optional
from playwright.sync_api import ElementHandle, Page

from src.executor.eval_action import EvaluationManager
from src.executor.modal_sweeper import dismiss_blocking_overlays
from src.utils.delay import random_delay
from src.utils.logger import logger


# 常见关卡栏/步骤条选择器
STAGE_CONTAINER_SELECTORS = [
    ".stage-list",
    ".shixun-stage-list",
    "[class*='stageList']",
    "[class*='stageContainer']",
    "[class*='stepList']",
    ".ant-steps",
    ".stage-nav",
    ".stage-bar",
    ".task-stages",
    "#stage-list",
]

# 常见单个关卡项选择器
STAGE_ITEM_SELECTORS = [
    ".stage-item",
    "[class*='stageItem']",
    "[class*='stepItem']",
    ".ant-steps-item",
    "li[class*='stage']",
    "div[class*='stage-tab']",
    ".shixun-stage-item",
]


def detect_stage_topology(page: Page) -> Dict[str, Any]:
    """探测当前关卡拓扑结构与所处关卡状态。

    Returns:
        dict:
            - current_stage (int): 当前所在关卡序号 (1-indexed，未知默认 1)
            - total_stages (int): 总关卡数量 (未知默认 1)
            - has_prev (bool): 是否有上一关按钮/回退通道
            - has_next (bool): 是否有下一关按钮
            - stages (list[dict]): 各关卡详情列表
            - raw_text (str): 提取到的关卡说明文本
    """
    if not page:
        return {"current_stage": 1, "total_stages": 1, "has_prev": False, "has_next": False, "stages": []}

    eval_mgr = EvaluationManager()
    has_prev = False
    for p_sel in eval_mgr.PREV_LEVEL_SELECTORS:
        try:
            p_btn = page.query_selector(p_sel)
            if p_btn and hasattr(p_btn, "is_visible") and p_btn.is_visible() is True:
                has_prev = True
                break
        except Exception:
            continue

    has_next = False
    for n_sel in eval_mgr.NEXT_LEVEL_SELECTORS:
        try:
            n_btn = page.query_selector(n_sel)
            if n_btn and hasattr(n_btn, "is_visible") and n_btn.is_visible() is True:
                has_next = True
                break
        except Exception:
            continue

    # 尝试从页面文本或 DOM 结构中提取当前关卡与总关卡数
    current_stage = 1
    total_stages = 1
    raw_text = ""
    stages: List[Dict[str, Any]] = []

    try:
        val = page.evaluate("() => document.body ? (document.body.innerText || '') : ''")
        page_text = val if isinstance(val, str) else ""
    except Exception:
        page_text = ""

    # 正则规则匹配：如 "第 2 关 / 共 2 关", "第2关/共3关", "关卡 2/2", "关卡: 2 / 3"
    patterns = [
        r"第\s*(\d+)\s*关\s*(?:[/／]\s*共?|共)\s*(\d+)\s*关?",
        r"关卡\s*[:：]?\s*(\d+)\s*[/／]\s*(\d+)",
        r"任务\s*[:：]?\s*(\d+)\s*[/／]\s*(\d+)",
        r"(\d+)\s*[/／]\s*(\d+)\s*关",
    ]
    for pat in patterns:
        m = re.search(pat, page_text)
        if m:
            cur, tot = int(m.group(1)), int(m.group(2))
            if 0 < cur <= tot:
                current_stage = cur
                total_stages = tot
                raw_text = m.group(0)
                break

    # 扫描关卡条元素
    for item_sel in STAGE_ITEM_SELECTORS:
        try:
            items = page.query_selector_all(item_sel)
            if isinstance(items, list) and len(items) >= 2:
                total_stages = max(total_stages, len(items))
                for idx, it in enumerate(items, 1):
                    raw_it_text = it.inner_text().strip() if hasattr(it, "inner_text") else ""
                    it_text = raw_it_text if isinstance(raw_it_text, str) else ""
                    raw_class = it.get_attribute("class") if hasattr(it, "get_attribute") else ""
                    it_class = (raw_class or "").lower() if isinstance(raw_class, str) else ""
                    is_active = any(k in it_class for k in ["active", "current", "process", "selected"])
                    is_passed = any(k in it_class for k in ["passed", "finish", "done", "success"]) or "已完成" in it_text
                    if is_active:
                        current_stage = idx
                    stages.append({
                        "index": idx,
                        "title": it_text or f"第 {idx} 关",
                        "is_active": is_active,
                        "is_passed": is_passed,
                    })
                break
        except Exception:
            continue

    # 若检测到存在“上一关”按钮但解析出的 current_stage 仍为 1，则修正为至少第 2 关
    if has_prev and current_stage <= 1:
        current_stage = 2
        total_stages = max(total_stages, 2)

    return {
        "current_stage": current_stage,
        "total_stages": total_stages,
        "has_prev": has_prev,
        "has_next": has_next,
        "stages": stages,
        "raw_text": raw_text,
    }


def trigger_prev_stage(page: Page) -> bool:
    """点击‘上一关’按钮回退至前一关"""
    eval_mgr = EvaluationManager()
    return eval_mgr.trigger_prev_level(page)


def navigate_to_stage(page: Page, stage_index: int) -> bool:
    """尝试点击关卡导航栏直达指定序号的关卡 (1-indexed)"""
    if not page or stage_index < 1:
        return False

    logger.info(f"正在尝试导航直达第 {stage_index} 关...")

    # 1. 尝试匹配明确的文字选择器
    selectors = [
        f"button:has-text('第 {stage_index} 关')",
        f"button:has-text('第{stage_index}关')",
        f"a:has-text('第 {stage_index} 关')",
        f"a:has-text('第{stage_index}关')",
        f"span:has-text('第{stage_index}关')",
        f"div:has-text('第{stage_index}关')",
        f"[data-stage='{stage_index}']",
        f"[data-index='{stage_index}']",
    ]
    for sel in selectors:
        try:
            elem = page.query_selector(sel)
            if elem and elem.is_visible():
                random_delay(0.3, 0.6)
                elem.click()
                logger.success(f"已成功点击直达第 {stage_index} 关")
                random_delay(0.8, 1.5)
                return True
        except Exception:
            continue

    # 2. 尝试从关卡列表项中按下标点击
    for item_sel in STAGE_ITEM_SELECTORS:
        try:
            items = page.query_selector_all(item_sel)
            if items and len(items) >= stage_index:
                target_item = items[stage_index - 1]
                random_delay(0.3, 0.6)
                target_item.click()
                logger.success(f"已成功通过关卡项 #{stage_index} 导航切换")
                random_delay(0.8, 1.5)
                return True
        except Exception:
            continue

    return False


def align_to_first_uncompleted_stage(page: Page, max_rollbacks: int = 5) -> Dict[str, Any]:
    """多关卡自动回退对齐机制 (Multi-stage Rollback Alignment).

    当用户进入多关卡实训大题时，头歌平台有时默认保留并停留在上次的后置关卡（如停留于第 2 关，但整题其实 0/2 未完成）。
    本函数自动探测当前关卡状态：若检测到处于非第 1 关且存在“上一关”可回退通道，则自动循环点击“上一关”
    或直达第 1 关，确保作答流水线从第一道未完成的关卡开始按序推进。

    Args:
        page: Playwright Page 实例
        max_rollbacks: 最大连续回退点击次数限制 (防止异常死循环)

    Returns:
        dict:
            - aligned (bool): 是否进行了回退对齐操作
            - initial_stage (int): 初始所处关卡
            - current_stage (int): 对齐后所处关卡
            - total_stages (int): 总关卡数
            - rollbacks_performed (int): 执行的回退步数
    """
    if not page:
        return {"aligned": False, "initial_stage": 1, "current_stage": 1, "total_stages": 1, "rollbacks_performed": 0}

    dismiss_blocking_overlays(page)
    topo = detect_stage_topology(page)
    init_stage = topo["current_stage"]
    tot_stages = topo["total_stages"]
    has_prev = topo["has_prev"]

    # 若已经在第 1 关且无上一关按钮，无需回退对齐
    if init_stage <= 1 and not has_prev:
        return {
            "aligned": False,
            "initial_stage": init_stage,
            "current_stage": init_stage,
            "total_stages": tot_stages,
            "rollbacks_performed": 0,
        }

    logger.warning(
        f"检测到关卡可能未对齐 (初始停留在第 {init_stage}/{tot_stages} 关，存在上一关: {has_prev})，启动多关卡自动回退对齐..."
    )

    rollbacks = 0
    # 策略 1: 尝试直达第 1 关
    if navigate_to_stage(page, 1):
        random_delay(1.0, 1.5)
        new_topo = detect_stage_topology(page)
        logger.success(f"已通过直达导航回退至第 1 关 (当前关卡: {new_topo['current_stage']})")
        return {
            "aligned": True,
            "initial_stage": init_stage,
            "current_stage": new_topo["current_stage"],
            "total_stages": tot_stages,
            "rollbacks_performed": 1,
        }

    # 策略 2: 迭代点击“上一关”直到退无可退
    eval_mgr = EvaluationManager()
    while rollbacks < max_rollbacks:
        dismiss_blocking_overlays(page)
        clicked = eval_mgr.trigger_prev_level(page)
        if not clicked:
            break
        rollbacks += 1
        random_delay(0.8, 1.5)

    final_topo = detect_stage_topology(page)
    logger.success(
        f"多关卡回退对齐完成: 初始关卡={init_stage}, 最终关卡={final_topo['current_stage']}, 回退步数={rollbacks}"
    )

    return {
        "aligned": rollbacks > 0,
        "initial_stage": init_stage,
        "current_stage": final_topo["current_stage"],
        "total_stages": tot_stages,
        "rollbacks_performed": rollbacks,
    }
