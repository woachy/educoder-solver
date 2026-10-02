"""填空题提取器 (Blank Extractor).

支持提取头歌平台的文本填空题：
- 识别题干与题目上下文描述
- 定位行内嵌入式输入框 (inline inputs) 与列表式输入框 (slot list)
- 提取每个空位的序号、提示文本 (placeholder)、前置上下文文本、后置上下文文本
- 提取当前输入框中已有的答案文本
- 生成精准供动作执行器使用的定位选择器
"""

import re
from typing import Any, List, Optional, Tuple
from bs4 import BeautifulSoup, NavigableString, Tag

from src.extractor.base import (
    BaseExtractor,
    BlankItem,
    QuestionData,
    QuestionType,
    get_page_html,
)
from src.utils.logger import logger


class BlankExtractor(BaseExtractor):
    """文本填空题提取器"""

    # 常见填空题容器选择器
    CONTAINER_SELECTORS = [
        ".subject-item",
        ".test-question",
        ".question-item",
        ".blank-question",
        ".fill-blank-item",
        ".shixun-task",
        ".exercise-item",
        ".question-wrap",
    ]

    # 常见题干选择器
    TITLE_SELECTORS = [
        ".subject-title",
        ".question-title",
        ".stem",
        ".question-stem",
        ".desc",
        ".subject_title",
        "h3.title",
        "h4.title",
        ".title",
    ]

    # 常见填空输入框选择器
    BLANK_INPUT_SELECTORS = [
        "input.blank-input",
        "input.answer-input",
        "input.fill-input",
        ".blank-item input",
        ".blank-fill input",
        ".fill-blank input",
        ".fill-in input",
        ".blank-wrap input",
        "span.fill-blank",
        "div[contenteditable='true']",
        "input[type='text']:not(.search-input):not(.filter-input)",
    ]

    def can_extract(self, page_or_html: Any) -> bool:
        """检查页面是否包含填空题特征"""
        try:
            html = get_page_html(page_or_html)
            soup = BeautifulSoup(html, "html.parser")

            # 排除选择题 (如果有单选/多选/判断，优先归选择题)
            if soup.find("input", attrs={"type": ["radio", "checkbox"]}):
                return False

            # 检查是否有明确填空输入框
            for selector in self.BLANK_INPUT_SELECTORS[:5]:
                if soup.select(selector):
                    return True

            text = soup.get_text()
            if any(k in text for k in ["填空题", "请在横线上填写", "填入正确答案"]):
                return True

            # 检查文本输入框且题干包含下划线
            text_inputs = soup.find_all("input", attrs={"type": "text"})
            if text_inputs and any(marker in text for marker in ["____", "（  ）", "【  】", "(  )"]):
                return True

            return False
        except Exception as e:
            logger.debug(f"BlankExtractor.can_extract 异常: {e}")
            return False

    def extract(self, page_or_html: Any) -> QuestionData:
        """从页面提取填空题结构化数据"""
        html = get_page_html(page_or_html)
        soup = BeautifulSoup(html, "html.parser")

        # 1. 查找题目容器
        container = self._find_question_container(soup)

        # 2. 提取题干与说明
        title, raw_desc = self._extract_title_and_desc(container, soup)

        # 3. 提取空位列表
        blanks = self._extract_blanks(container, soup, page_or_html)

        return QuestionData(
            type=QuestionType.BLANK,
            title=title,
            description=raw_desc,
            options=[],
            blanks=blanks,
            practical_details=None,
            metadata={"total_blanks": len(blanks)},
        )

    def _find_question_container(self, soup: BeautifulSoup) -> Tag:
        """查找题目外层容器"""
        for selector in self.CONTAINER_SELECTORS:
            node = soup.select_one(selector)
            if node:
                return node
        return soup.body if soup.body else soup

    def _extract_title_and_desc(self, container: Tag, soup: BeautifulSoup) -> Tuple[str, str]:
        """提取题干标题与描述"""
        title_node = None
        for selector in self.TITLE_SELECTORS:
            title_node = container.select_one(selector)
            if title_node:
                break

        if not title_node and container != soup:
            for selector in self.TITLE_SELECTORS:
                title_node = soup.select_one(selector)
                if title_node:
                    break

        if title_node:
            full_title = title_node.get_text(" ", strip=True)
        else:
            p = container.find("p")
            full_title = p.get_text(" ", strip=True) if p else container.get_text(" ", strip=True)[:150]

        # 清洗题目标签
        cleaned = re.sub(r"^[第\s]*\d+[\s\.\、\:]*", "", full_title)
        cleaned = re.sub(r"^[\(\[\（【]\s*(填空题|填空)\s*[\)\]\）】]", "", cleaned)
        cleaned = re.sub(r"[\(\[\（【]\s*(填空题|填空)\s*[\)\]\）】]$", "", cleaned)
        return cleaned.strip(), full_title

    def _extract_blanks(self, container: Tag, soup: BeautifulSoup, page_or_html: Any) -> List[BlankItem]:
        """提取所有填空槽位"""
        input_nodes: List[Tag] = []

        # 优先匹配特定的填空输入框选择器
        for selector in self.BLANK_INPUT_SELECTORS:
            nodes = container.select(selector)
            if nodes:
                input_nodes = nodes
                break

        if not input_nodes and container != soup:
            for selector in self.BLANK_INPUT_SELECTORS:
                nodes = soup.select(selector)
                if nodes:
                    input_nodes = nodes
                    break

        blanks: List[BlankItem] = []
        for idx, node in enumerate(input_nodes):
            index = self._extract_blank_index(node, idx)
            hint = self._extract_hint(node)
            current_value = self._extract_current_value(node, idx, page_or_html)
            prefix, suffix = self._extract_surrounding_context(node)
            selector = self._generate_selector(node, idx)

            blanks.append(
                BlankItem(
                    index=index,
                    hint=hint,
                    prefix_text=prefix,
                    suffix_text=suffix,
                    current_value=current_value,
                    selector=selector,
                )
            )

        return blanks

    def _extract_blank_index(self, node: Tag, default_idx: int) -> int:
        """提取空位序号 (1-indexed)"""
        # 1. 检查属性 data-index, data-slot, data-blank-id
        for attr in ["data-index", "data-slot", "data-blank-id", "data-order"]:
            if node.has_attr(attr):
                try:
                    return int(node[attr])
                except ValueError:
                    pass

        # 2. 检查父级或同级 label
        parent = node.parent
        if parent:
            text = parent.get_text()
            m = re.search(r"第\s*(\d+)\s*空", text)
            if m:
                return int(m.group(1))

        # 3. 兜底按列表序号
        return default_idx + 1

    def _extract_hint(self, node: Tag) -> str:
        """提取占位符或提示文本"""
        if node.has_attr("placeholder"):
            return str(node["placeholder"]).strip()
        if node.has_attr("title"):
            return str(node["title"]).strip()
        return ""

    def _extract_current_value(self, node: Tag, index: int, page_or_html: Any) -> str:
        """提取输入框当前的值"""
        # 1. 如果是 contenteditable 元素
        if node.has_attr("contenteditable") and node["contenteditable"] in ["true", ""]:
            return node.get_text(strip=True)

        # 2. 如果带有 value 属性
        if node.has_attr("value"):
            return str(node["value"])

        # 3. 如果是真实 Playwright 页面
        if hasattr(page_or_html, "query_selector_all") and callable(page_or_html.query_selector_all):
            try:
                inputs = page_or_html.query_selector_all("input[type='text'], input:not([type])")
                if index < len(inputs):
                    val = inputs[index].input_value()
                    if val is not None:
                        return val
            except Exception:
                pass

        return ""

    def _extract_surrounding_context(self, node: Tag) -> Tuple[str, str]:
        """提取空位前后上下文文本 (各截取最近 40 个字符)"""
        prefix_parts: List[str] = []
        suffix_parts: List[str] = []

        # 获取前一个兄弟节点或前置文字
        prev = node.previous_sibling
        while prev and len("".join(prefix_parts)) < 40:
            if isinstance(prev, NavigableString):
                prefix_parts.insert(0, str(prev))
            elif isinstance(prev, Tag):
                prefix_parts.insert(0, prev.get_text())
            prev = prev.previous_sibling

        # 获取后一个兄弟节点或后置文字
        nxt = node.next_sibling
        while nxt and len("".join(suffix_parts)) < 40:
            if isinstance(nxt, NavigableString):
                suffix_parts.append(str(nxt))
            elif isinstance(nxt, Tag):
                suffix_parts.append(nxt.get_text())
            nxt = nxt.next_sibling

        prefix = "".join(prefix_parts).strip()
        suffix = "".join(suffix_parts).strip()

        # 清洗换行多余空格
        prefix = re.sub(r"\s+", " ", prefix)
        suffix = re.sub(r"\s+", " ", suffix)

        return prefix[-40:] if len(prefix) > 40 else prefix, suffix[:40]

    def _generate_selector(self, node: Tag, index: int) -> str:
        """生成唯一定位选择器"""
        if node.has_attr("id"):
            return f"#{node['id']}"

        if node.has_attr("name"):
            return f"input[name='{node['name']}']"

        classes = node.get("class", [])
        if classes:
            primary_class = classes[0]
            return f".{primary_class}:nth-of-type({index + 1})"

        return f"input[type='text']:nth-of-type({index + 1})"
