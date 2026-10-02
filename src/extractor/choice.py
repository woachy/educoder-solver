"""客观选择题与判断题提取器 (Choice & Judgment Extractor).

支持提取头歌平台的单选题、多选题、判断题：
- 题干与题目描述清洗
- 选项标识 (A, B, C, D / 对, 错 / T, F) 精准识别
- 纯净选项文本提纯 (剔除字母序号与单选/复选框杂质)
- 识别选项当前选中状态 (checked/selected)
- 生成供执行引擎使用的元素选择器与下标
"""

import re
from typing import Any, List, Optional, Tuple
from bs4 import BeautifulSoup, Tag

from src.extractor.base import (
    BaseExtractor,
    ChoiceOption,
    QuestionData,
    QuestionType,
    get_page_html,
)
from src.utils.logger import logger


class ChoiceExtractor(BaseExtractor):
    """客观选择题/判断题提取器"""

    # 常见选择题容器类名
    QUESTION_CONTAINER_SELECTORS = [
        ".subject-item",
        ".test-question",
        ".question-item",
        ".single-choice",
        ".multiple-choice",
        ".judgment-item",
        ".judgement-item",
        ".shixun-task",
        ".exercise-item",
        ".exam-item",
        ".question-wrap",
        ".t-question",
    ]

    # 常见题干选择器
    TITLE_SELECTORS = [
        ".subject-title",
        ".question-title",
        ".stem",
        ".question-stem",
        ".subject_title",
        ".t-title",
        ".question-name",
        "h3.title",
        "h4.title",
        ".title",
        ".desc",
    ]

    # 常见选项项选择器
    OPTION_ITEM_SELECTORS = [
        ".option-item",
        ".subject-options li",
        ".options-list > li",
        ".options li",
        ".choice-option",
        ".ant-radio-wrapper",
        ".ant-checkbox-wrapper",
        ".el-radio",
        ".el-checkbox",
        ".custom-radio",
        ".custom-checkbox",
        "label.option",
        "div.option",
        "li.option",
    ]

    def can_extract(self, page_or_html: Any) -> bool:
        """检查页面是否包含选择题或判断题特征"""
        try:
            html = get_page_html(page_or_html)
            soup = BeautifulSoup(html, "html.parser")

            # 检查是否有单选/多选 input
            if soup.find("input", attrs={"type": ["radio", "checkbox"]}):
                return True

            # 检查是否有通用选项容器
            for selector in self.OPTION_ITEM_SELECTORS:
                if soup.select(selector):
                    return True

            # 检查文本关键词
            text = soup.get_text()
            if any(k in text for k in ["单选题", "多选题", "判断题", "下列关于", "以下说法正确"]):
                return True

            return False
        except Exception as e:
            logger.debug(f"ChoiceExtractor.can_extract 判定异常: {e}")
            return False

    def extract(self, page_or_html: Any) -> QuestionData:
        """从页面中提取客观题结构化数据"""
        html = get_page_html(page_or_html)
        soup = BeautifulSoup(html, "html.parser")

        # 1. 查找题目容器
        container = self._find_question_container(soup)

        # 2. 提取题干与描述
        title, raw_desc = self._extract_title_and_desc(container, soup)

        # 3. 提取选项列表
        options = self._extract_options(container, soup, page_or_html)

        # 4. 判断题型 (单选 / 多选 / 判断)
        q_type = self._determine_question_type(container, soup, options, title)

        return QuestionData(
            type=q_type,
            title=title,
            description=raw_desc,
            options=options,
            blanks=[],
            practical_details=None,
            metadata={"total_options": len(options)},
        )

    def _find_question_container(self, soup: BeautifulSoup) -> Tag:
        """查找题目外层容器"""
        for selector in self.QUESTION_CONTAINER_SELECTORS:
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
            # 尝试在全局查找
            for selector in self.TITLE_SELECTORS:
                title_node = soup.select_one(selector)
                if title_node:
                    break

        if title_node:
            full_title = title_node.get_text(strip=True)
        else:
            # 兜底：获取容器第一段或前 200 字符
            full_title = ""
            p = container.find("p")
            if p:
                full_title = p.get_text(strip=True)
            elif container.get_text(strip=True):
                full_title = container.get_text(strip=True)[:150]

        # 清洗题干，提取题号与纯文本
        cleaned_title = self._clean_title(full_title)
        return cleaned_title, full_title

    def _clean_title(self, raw_title: str) -> str:
        """清洗题干文本中的题型标签与编号"""
        cleaned = raw_title
        # 移除类似 "[单选题]", "【多选题】", "(判断题)", "第1题"
        cleaned = re.sub(r"^[第\s]*\d+[\s\.\、\:]*", "", cleaned)
        cleaned = re.sub(r"^[\(\[\（【]\s*(单选题|多选题|判断题|单选|多选|判断)\s*[\)\]\）】]", "", cleaned)
        cleaned = re.sub(r"[\(\[\（【]\s*(单选题|多选题|判断题|单选|多选|判断)\s*[\)\]\）】]$", "", cleaned)
        return cleaned.strip()

    def _extract_options(self, container: Tag, soup: BeautifulSoup, page_or_html: Any) -> List[ChoiceOption]:
        """提取所有选项"""
        option_nodes: List[Tag] = []

        # 依次尝试匹配候选选择器
        for selector in self.OPTION_ITEM_SELECTORS:
            nodes = container.select(selector)
            if nodes:
                option_nodes = nodes
                break

        if not option_nodes:
            # 尝试查找包含 radio 或 checkbox 的父元素
            inputs = container.find_all("input", attrs={"type": ["radio", "checkbox"]})
            if inputs:
                for inp in inputs:
                    parent = inp.parent
                    if parent and parent not in option_nodes:
                        option_nodes.append(parent)

        if not option_nodes and container != soup:
            # 回退在全局 soup 查找
            for selector in self.OPTION_ITEM_SELECTORS:
                nodes = soup.select(selector)
                if nodes:
                    option_nodes = nodes
                    break

        options: List[ChoiceOption] = []
        for idx, node in enumerate(option_nodes):
            opt_id, opt_text = self._extract_option_key_and_text(node, idx)
            is_selected = self._check_option_selected(node, idx, page_or_html)
            selector = self._generate_option_selector(node, idx)

            options.append(
                ChoiceOption(
                    id=opt_id,
                    text=opt_text,
                    selected=is_selected,
                    selector=selector,
                    locator_index=idx,
                )
            )

        return options

    def _extract_option_key_and_text(self, node: Tag, index: int) -> Tuple[str, str]:
        """从选项节点中提取选项字母/标识和纯净文本"""
        # 1. 查找明确标记字母的子节点
        key_elem = node.select_one(
            ".option-key, .option-letter, .letter, .key, span[class*='key'], span[class*='letter']"
        )
        opt_id = ""
        if key_elem:
            opt_id = key_elem.get_text(strip=True).rstrip(".:、 ")

        full_text = node.get_text(" ", strip=True)

        # 2. 如果未找到 key 节点，从文本前缀提取 (例如 "A. 内容", "A、内容", "A: 内容")
        if not opt_id:
            m = re.match(r"^([A-Za-z])[\.\、\:\s\)](.*)$", full_text)
            if m:
                opt_id = m.group(1).upper()
                full_text = m.group(2).strip()
            else:
                # 检查判断题前缀
                judge_m = re.match(r"^(正确|错误|对|错|True|False|T|F)[\.\、\:\s\)]*(.*)$", full_text, re.IGNORECASE)
                if judge_m:
                    opt_id = judge_m.group(1)
                    full_text = judge_m.group(2).strip() or opt_id

        # 3. 检查 input 的 value 属性
        if not opt_id:
            inp = node.find("input")
            if inp and inp.get("value"):
                val = str(inp["value"]).strip()
                if len(val) == 1 and val.isalpha():
                    opt_id = val.upper()
                elif val in ("1", "0", "true", "false", "对", "错"):
                    opt_id = val

        # 4. 兜底分配序号
        if not opt_id:
            opt_id = chr(ord("A") + index) if index < 26 else str(index + 1)

        # 清洗 option 纯文本
        cleaned_text = self._clean_option_text(full_text, opt_id)
        return opt_id, cleaned_text

    def _clean_option_text(self, text: str, opt_id: str) -> str:
        """剥离选项文本中的前缀字母与多余空格"""
        cleaned = text.strip()
        # 剔除开头的字母标识如 "A. " 或 "A、"
        prefix_pattern = rf"^{re.escape(opt_id)}[\.\、\:\s\)]*\s*"
        cleaned = re.sub(prefix_pattern, "", cleaned, flags=re.IGNORECASE)
        # 压缩多余空白
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    def _check_option_selected(self, node: Tag, index: int, page_or_html: Any) -> bool:
        """判断选项是否处于选中状态"""
        # 1. 检查 inner input checked 属性
        inp = node.find("input")
        if inp:
            if inp.has_attr("checked"):
                return True

        # 2. 检查节点或子节点是否有选中状态类名
        selected_classes = {
            "checked",
            "selected",
            "active",
            "ant-radio-checked",
            "ant-checkbox-checked",
            "is-checked",
            "el-radio__input.is-checked",
            "custom-radio-checked",
        }
        classes = set(node.get("class", []))
        if classes.intersection(selected_classes):
            return True

        # 检查子元素中的 class
        for sub in node.find_all(True):
            sub_classes = set(sub.get("class", []))
            if sub_classes.intersection(selected_classes):
                return True

        # 3. 如果是真实 Playwright 页面且有 input
        if hasattr(page_or_html, "query_selector_all") and callable(page_or_html.query_selector_all):
            try:
                inputs = page_or_html.query_selector_all("input[type='radio'], input[type='checkbox']")
                if index < len(inputs):
                    return inputs[index].is_checked()
            except Exception:
                pass

        return False

    def _generate_option_selector(self, node: Tag, index: int) -> str:
        """生成选项定位 CSS 选择器"""
        # 如果有 input 标签且有 id
        inp = node.find("input")
        if inp and inp.get("id"):
            return f"#{inp['id']}"

        # 尝试使用 input[type]
        if inp and inp.get("name"):
            return f"input[name='{inp['name']}']:nth-of-type({index + 1})"

        # 使用 class
        classes = node.get("class", [])
        if classes:
            primary_class = classes[0]
            return f".{primary_class}:nth-of-type({index + 1})"

        return f".option-item:nth-of-type({index + 1})"

    def _determine_question_type(
        self,
        container: Tag,
        soup: BeautifulSoup,
        options: List[ChoiceOption],
        title: str,
    ) -> QuestionType:
        """精准判断题型：单选、多选还是判断题"""
        container_text = container.get_text()
        full_text = soup.get_text()

        # 1. 判断题特征判定
        # 标题中明确提及判断
        if any(k in title for k in ["判断题", "判断正误", "判断下列"]):
            return QuestionType.JUDGMENT

        # 选项仅 2 项且为对/错/正确/错误/T/F
        if len(options) == 2:
            opt_ids = {opt.id.strip().upper() for opt in options}
            opt_texts = {opt.text.strip().upper() for opt in options}
            judgment_keywords = {"对", "错", "正确", "错误", "T", "F", "TRUE", "FALSE"}
            if opt_ids.issubset(judgment_keywords) or opt_texts.issubset(judgment_keywords):
                return QuestionType.JUDGMENT

        # 2. 多选题特征判定
        # 页面存在 checkbox 或 checkbox 类名
        if container.find("input", attrs={"type": "checkbox"}) or soup.select(".ant-checkbox, .el-checkbox"):
            return QuestionType.MULTIPLE_CHOICE

        # 文本中包含多选题字样
        if any(k in title or k in container_text for k in ["多选题", "多选", "复选题", "下列哪些", "以下哪些"]):
            return QuestionType.MULTIPLE_CHOICE

        # 3. 默认为单选题
        return QuestionType.CHOICE
