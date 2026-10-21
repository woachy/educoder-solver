"""智能题型探测与统一提取路由 (Detector & Dispatcher).

负责自动分析当前激活页面的 DOM 拓扑结构与关键特征，实现：
- 零人工干预自动识别题型 (单选、多选、判断、填空、编程实训)
- 调度对应的专用提取器完成高保真信息抽取
- 对外输出标准化统一结构 QuestionData
"""

import time
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
from src.extractor.paper import PaperExtractor
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

        # 2. 探测试卷型 / 复合连排客观与填空题 (多道题目并列或混合客观填空)
        paper_extractor = PaperExtractor()
        if paper_extractor.can_extract(page_or_html):
            logger.info("题型探测结果: 试卷型/复合客观填空题 (EXAM_PAPER)")
            return QuestionType.EXAM_PAPER

        html = get_page_html(page_or_html)
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text()

        # 3. 探测单道客观题 (单选 / 多选 / 判断)
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

        # 4. 探测单道填空题
        blank_extractor = BlankExtractor()
        if blank_extractor.can_extract(page_or_html):
            logger.info("题型探测结果: 填空题 (BLANK)")
            return QuestionType.BLANK

    except Exception as e:
        logger.warning(f"题型自动探测过程出现异常: {e}")

    logger.warning("未能精确匹配已知题型特征，归类为 UNKNOWN")
    return QuestionType.UNKNOWN


def wait_for_spa_loading(page_or_html: Any, timeout: float = 3.5, poll_interval: float = 0.3) -> bool:
    """SPA 页面加载态防抖自愈等待。

    检测页面是否包含加载文案（如“努力请求数据中”、“努力加载中”、“正在努力加载”）
    或加载类名选择器（如 .ldsRing___mpBZC, [class*='ldsRing'], [class*='loading'], .ant-spin-spinning）。
    若检测到加载中，循环等待至加载指示器消失且题目容器/编辑器呈现，最多等待 timeout 秒。

    Args:
        page_or_html: Playwright Page 实例、Mock 对象或 HTML 字符串
        timeout: 最长等待超时时间（秒，默认 3.5 秒）
        poll_interval: 轮询等待间隔（秒，默认 0.3 秒）

    Returns:
        bool: True 表示页面已就绪（未处于加载态或加载已完成呈现内容），False 表示超时仍处于加载态
    """
    if not hasattr(page_or_html, "evaluate") or not callable(page_or_html.evaluate):
        return True

    js_detect_loading = """
    () => {
        try {
            const body = document.body;
            const text = body ? (body.innerText || body.textContent || "") : "";
            const loadingTexts = ["努力请求数据中", "努力加载中", "正在努力加载"];
            const hasLoadingText = loadingTexts.some(t => text.includes(t));

            const loadingSelectors = [
                ".ldsRing___mpBZC",
                "[class*='ldsRing']",
                "[class*='loading']",
                ".ant-spin-spinning"
            ];
            let hasLoadingEl = false;
            for (const sel of loadingSelectors) {
                const els = document.querySelectorAll(sel);
                for (const el of els) {
                    const style = window.getComputedStyle ? window.getComputedStyle(el) : null;
                    if (!style || (style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0')) {
                        hasLoadingEl = true;
                        break;
                    }
                }
                if (hasLoadingEl) break;
            }

            const isLoading = hasLoadingText || hasLoadingEl;

            // 检查题目容器或编辑器是否已呈现
            const contentSelectors = [
                ".monaco-editor",
                ".my-monaco-editor",
                ".ace_editor",
                "#monaco-editor",
                ".shixun-left",
                ".task-description",
                ".task-content",
                "#task-content",
                ".markdown-body",
                ".subject-item",
                ".question-item",
                ".choice-item",
                ".exercise-item",
                ".ant-radio-group",
                ".ant-checkbox-group",
                ".choice-option",
                ".blank-item",
                "textarea.editor-input"
            ];
            let hasContent = false;
            for (const sel of contentSelectors) {
                const el = document.querySelector(sel);
                if (el) {
                    const style = window.getComputedStyle ? window.getComputedStyle(el) : null;
                    if (!style || (style.display !== 'none' && style.visibility !== 'hidden')) {
                        hasContent = true;
                        break;
                    }
                }
            }

            const hasMonaco = !!(((window.monaco || window.Monaco) && (window.monaco || window.Monaco).editor && (window.monaco || window.Monaco).editor.getModels && (window.monaco || window.Monaco).editor.getModels().length > 0));
            if (hasMonaco) {
                hasContent = true;
            }

            return {
                is_loading: isLoading,
                has_content: hasContent
            };
        } catch (e) {
            return { is_loading: false, has_content: true };
        }
    }
    """

    start_time = time.time()
    try:
        status = page_or_html.evaluate(js_detect_loading)
    except Exception as e:
        logger.debug(f"wait_for_spa_loading 初始探查异常: {e}")
        return True

    is_loading = False
    has_content = True
    if isinstance(status, dict):
        is_loading = status.get("is_loading", False)
        has_content = status.get("has_content", False)
    elif isinstance(status, bool):
        is_loading = status
        has_content = not status

    if not is_loading:
        return True

    logger.info("检测到 SPA 关卡正在异步加载数据，启动加载态防抖自愈等待...")
    while (time.time() - start_time) < timeout:
        if hasattr(page_or_html, "wait_for_timeout") and callable(page_or_html.wait_for_timeout):
            try:
                page_or_html.wait_for_timeout(int(poll_interval * 1000))
            except Exception:
                time.sleep(poll_interval)
        else:
            time.sleep(poll_interval)

        try:
            status = page_or_html.evaluate(js_detect_loading)
            if isinstance(status, dict):
                is_loading = status.get("is_loading", False)
                has_content = status.get("has_content", False)
            elif isinstance(status, bool):
                is_loading = status
                has_content = not status

            if not is_loading and has_content:
                logger.info("SPA 加载指示器已消失且题目内容容器已呈现，加载态防抖等待完成")
                return True
            if not is_loading:
                logger.info("SPA 加载指示器已消失，加载态防抖等待完成")
                return True
        except Exception as e:
            logger.debug(f"wait_for_spa_loading 轮询探查异常: {e}")
            break

    logger.warning(f"SPA 加载态防抖等待超过 {timeout} 秒，强制放行继续尝试提取")
    return False


def extract_question(page_or_html: Any, force_type: Optional[QuestionType] = None) -> QuestionData:
    """统一题目提取入口。

    自动探测页面题型并路由至专有提取器，输出结构化 QuestionData。

    Args:
        page_or_html: Playwright Page 实例、Mock 对象或 HTML 字符串
        force_type: 可选，强制指定题型而不进行自动探测

    Returns:
        QuestionData: 结构化题目数据模型
    """
    if hasattr(page_or_html, "evaluate") and callable(page_or_html.evaluate):
        wait_for_spa_loading(page_or_html)

    target_type = force_type or detect_question_type(page_or_html)

    if target_type == QuestionType.EXAM_PAPER:
        extractor = PaperExtractor()
        data = extractor.extract(page_or_html)
        if force_type:
            data.type = force_type
        return data

    elif target_type in (QuestionType.CHOICE, QuestionType.MULTIPLE_CHOICE, QuestionType.JUDGMENT):
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
        # UNKNOWN 类型兜底：尝试依次用 Paper -> Choice -> Blank -> Practical 抽取
        logger.info("未识别题型，尝试通用抽取兜底...")
        for ext in [PaperExtractor(), ChoiceExtractor(), BlankExtractor(), PracticalExtractor()]:
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
