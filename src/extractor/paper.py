"""试卷型与复合客观/填空题提取器 (Exam Paper & Mixed Question Extractor).

支持提取头歌平台的试卷型大题与多题连排复合页面：
- 识别单页中连续多道单选题、多选题、判断题与填空题的题目矩阵
- 提纯题干与行内 LaTeX 数学公式 (KaTeX / MathJax / 关系代数表达式如 \\sigma, \\pi, \\bowtie)
- 为各子题精准划分槽位、选项与输入框定位器
- 结构化输出 SubQuestion 列表与统一 QuestionData(type=EXAM_PAPER)
"""

import re
from typing import Any, Dict, List, Optional, Tuple
from bs4 import BeautifulSoup, Tag

from src.extractor.base import (
    BaseExtractor,
    BlankItem,
    ChoiceOption,
    QuestionData,
    QuestionType,
    SubQuestion,
    get_page_html,
)
from src.extractor.choice import ChoiceExtractor
from src.extractor.blank import BlankExtractor
from src.extractor.practical import PracticalExtractor
from src.utils.logger import logger


# 常见子题容器选择器
SUB_QUESTION_CONTAINER_SELECTORS = [
    ".question-item",
    ".subject-item",
    "div[class*='questionItem']",
    "div[class*='subjectItem']",
    "div[class*='question_item']",
    "div[class*='exerciseItem']",
    ".exam-item",
    ".paper-item",
    ".test-question",
    ".exercise-item",
    ".question-wrap",
    "div[class*='t-question']",
    ".ant-list-item",
]

# 选项子选择器
OPTION_SELECTORS = [
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

# 填空输入框子选择器
BLANK_SELECTORS = [
    "input.blank-input",
    "input.answer-input",
    "input.fill-input",
    ".blank-item input",
    ".blank-fill input",
    ".fill-blank input",
    ".fill-in input",
    "input[type='text']:not(.search-input):not(.filter-input)",
]


def extract_latex_formulas(node: Tag) -> List[str]:
    """从 HTML 节点中提纯 LaTeX 数学公式表达式。

    支持 KaTeX、MathJax、annotation (application/x-tex) 以及文本内 $...$ / $$...$$ / \\(...\\)。
    """
    formulas: List[str] = []
    if not node:
        return formulas

    # 1. KaTeX 与 MathML 中的 <annotation encoding="application/x-tex">
    annotations = node.select("annotation[encoding*='tex'], annotation[encoding*='latex']")
    for ann in annotations:
        f_text = ann.get_text(strip=True)
        if f_text and f_text not in formulas:
            formulas.append(f_text)

    # 2. MathJax script 标签 <script type="math/tex">
    mathjax_scripts = node.select("script[type*='math/tex']")
    for scr in mathjax_scripts:
        f_text = scr.get_text(strip=True)
        if f_text and f_text not in formulas:
            formulas.append(f_text)

    # 3. 元素属性 data-latex 或 data-tex
    for el in node.find_all(attrs={"data-latex": True}):
        val = el["data-latex"].strip()
        if val and val not in formulas:
            formulas.append(val)
    for el in node.find_all(attrs={"data-tex": True}):
        val = el["data-tex"].strip()
        if val and val not in formulas:
            formulas.append(val)

    # 4. 正则检索纯文本中的 LaTeX 标记 ($$...$$, $...$, \(...\), \[...\])
    raw_text = node.get_text(" ", strip=True)
    patterns = [
        r"\$\$(.+?)\$\$",
        r"\\\[(.+?)\\\]",
        r"\\\((.+?)\\\)",
        r"(?<!\$)\$(?!\$)([^\$\n]{2,150}?)(?<!\$)\$(?!\$)",
    ]
    for pat in patterns:
        for match in re.findall(pat, raw_text):
            cleaned_m = match.strip()
            if cleaned_m and cleaned_m not in formulas and len(cleaned_m) > 1:
                # 过滤明显不是公式的纯英文句子
                if any(c in cleaned_m for c in ["\\", "_", "^", "=", "<", ">", "+", "-", "*", "/", "sigma", "pi", "bowtie"]):
                    formulas.append(cleaned_m)

    return formulas


class PaperExtractor(BaseExtractor):
    """试卷型多题连排与复合客观/填空题提取器"""

    def can_extract(self, page_or_html: Any) -> bool:
        """判断页面是否为试卷型连排题或复合题"""
        try:
            # 1. 编程实训题直接排除
            if PracticalExtractor().can_extract(page_or_html):
                return False

            html = get_page_html(page_or_html)
            soup = BeautifulSoup(html, "html.parser")

            # 2. 检查多子题容器
            for sel in SUB_QUESTION_CONTAINER_SELECTORS[:6]:
                containers = soup.select(sel)
                # 只有当容器数量大于等于 2 时，才判定为多题试卷型
                if len(containers) >= 2:
                    return True

            # 3. 检查单选组数量：存在 2 个及以上不同的 radio-group
            radio_groups = soup.select(".ant-radio-group, .ant-checkbox-group, .radio-group, [role='radiogroup']")
            if len(radio_groups) >= 2:
                return True

            # 4. 检查是否同时存在客观选项与填空输入框 (混合客观/填空题)
            has_radios = bool(soup.find("input", attrs={"type": ["radio", "checkbox"]})) or bool(
                soup.select(".ant-radio-wrapper, .choice-option")
            )
            has_blanks = bool(soup.select("input.blank-input, input.answer-input, .blank-item input"))
            if has_radios and has_blanks:
                return True

            # 5. 检查页面中是否包含“试卷”、“题量”、“共 N 题”且包含多个题号
            text = soup.get_text()
            if any(k in text for k in ["试卷", "答卷", "总分", "题量", "关系数据库"]):
                numbered = re.findall(r"(?:第\s*[1-9]\s*题|\b[1-9]\s*[\.、\)])", text)
                if len(numbered) >= 2:
                    return True

            return False
        except Exception as e:
            logger.debug(f"PaperExtractor.can_extract 异常: {e}")
            return False

    def extract(self, page_or_html: Any) -> QuestionData:
        """从页面提取出结构化试卷题目 QuestionData，包含所有 SubQuestion"""
        html = get_page_html(page_or_html)
        soup = BeautifulSoup(html, "html.parser")

        # 1. 提取试卷大题总标题
        title = self._extract_paper_title(soup)

        # 2. 定位所有子题容器
        containers = self._find_sub_question_containers(soup)

        sub_questions: List[SubQuestion] = []
        for idx, container in enumerate(containers):
            sub_q = self._extract_sub_question(container, idx + 1, page_or_html)
            if sub_q:
                sub_questions.append(sub_q)

        # 若容器解析未提取出有效子题，兜底按全局选项与填空聚合
        if not sub_questions:
            choice_ext = ChoiceExtractor()
            if choice_ext.can_extract(page_or_html):
                q = choice_ext.extract(page_or_html)
                sub_questions.append(
                    SubQuestion(
                        index=1,
                        type=q.type,
                        title=q.title,
                        description=q.description,
                        options=q.options,
                        latex_formulas=extract_latex_formulas(soup),
                    )
                )

        # 汇总所有选项与填空
        all_options = []
        all_blanks = []
        for sq in sub_questions:
            all_options.extend(sq.options)
            all_blanks.extend(sq.blanks)

        return QuestionData(
            type=QuestionType.EXAM_PAPER,
            title=title,
            description=f"试卷型大题: 共包含 {len(sub_questions)} 道子题",
            options=all_options,
            blanks=all_blanks,
            sub_questions=sub_questions,
            metadata={
                "total_sub_questions": len(sub_questions),
                "sub_question_types": [sq.type.value for sq in sub_questions],
            },
        )

    def _extract_paper_title(self, soup: BeautifulSoup) -> str:
        """提取试卷主标题"""
        for sel in [".paper-title", ".exam-title", ".task-title", "h2.title", "h3.title", "h2", "h3"]:
            node = soup.select_one(sel)
            if node:
                t = node.get_text(strip=True)
                if t and len(t) > 2 and "努力" not in t:
                    return t
        return "试卷型客观综合测试"

    def _find_sub_question_containers(self, soup: BeautifulSoup) -> List[Tag]:
        """寻找页面中的所有子题容器"""
        for sel in SUB_QUESTION_CONTAINER_SELECTORS:
            nodes = soup.select(sel)
            # 过滤只包含实质内容的容器 (排除纯空白或纯按钮栏)
            valid = [
                n for n in nodes
                if len(n.get_text(strip=True)) > 5 and (
                    n.select(','.join(OPTION_SELECTORS[:4])) or
                    n.select(','.join(BLANK_SELECTORS[:3])) or
                    n.find("input")
                )
            ]
            if len(valid) >= 2:
                return valid

        # 回退：寻找包含 radio-group 或多 input 的 div
        groups = soup.select(".ant-radio-group, .ant-checkbox-group, .radio-group")
        if len(groups) >= 2:
            containers = []
            for g in groups:
                parent = g.parent
                while parent and parent.name not in ["body", "html"] and len(parent.get_text(strip=True)) < 20:
                    parent = parent.parent
                if parent and parent not in containers:
                    containers.append(parent)
                else:
                    containers.append(g)
            return containers

        return []

    def _extract_sub_question(self, container: Tag, index: int, page_or_html: Any) -> Optional[SubQuestion]:
        """提取单个子题目模型"""
        # 1. 提取题干与文本
        title, raw_desc = self._extract_stem(container, index)

        # 2. 提取 LaTeX 公式
        latex_list = extract_latex_formulas(container)

        # 3. 提取选项 (选择/判断)
        options = self._extract_options(container, page_or_html)

        # 4. 提取填空槽位
        blanks = self._extract_blanks(container, page_or_html)

        # 5. 判定子题类型
        sub_type = self._determine_sub_type(container, options, blanks, title)

        return SubQuestion(
            index=index,
            type=sub_type,
            title=title,
            description=raw_desc,
            options=options,
            blanks=blanks,
            latex_formulas=latex_list,
            selector=None,
            metadata={
                "has_latex": len(latex_list) > 0,
                "options_count": len(options),
                "blanks_count": len(blanks),
            },
        )

    def _extract_stem(self, container: Tag, default_idx: int) -> Tuple[str, str]:
        """提取子题题干与原始描述"""
        title_node = None
        for sel in [".subject-title", ".question-title", ".stem", ".question-stem", "h4", "h5", ".title", ".desc"]:
            title_node = container.select_one(sel)
            if title_node:
                break

        if title_node:
            full_title = title_node.get_text(" ", strip=True)
        else:
            # 获取选项/输入框之前的文字
            p = container.find("p")
            if p:
                full_title = p.get_text(" ", strip=True)
            else:
                full_title = container.get_text(" ", strip=True)[:150]

        # 清洗题号
        cleaned = re.sub(r"^[第\s]*\d+[\s\.\、\:\(（题\)]*", "", full_title)
        cleaned = re.sub(r"^[\(\[\（【]\s*(单选题|多选题|判断题|填空题|单选|多选|判断|填空)\s*[\)\]\）】]", "", cleaned)
        cleaned_title = cleaned.strip() or f"子题目 #{default_idx}"

        return cleaned_title, full_title

    def _determine_sub_type(
        self, container: Tag, options: List[ChoiceOption], blanks: List[BlankItem], title: str
    ) -> QuestionType:
        """判定子题目类型"""
        text = container.get_text()

        if blanks and not options:
            return QuestionType.BLANK

        if options:
            if any(k in text for k in ["【判断题】", "(判断题)", "[判断题]", "判断正误"]):
                return QuestionType.JUDGMENT
            if len(options) == 2 and any(opt.id in ["对", "错", "正确", "错误", "T", "F"] for opt in options):
                return QuestionType.JUDGMENT
            if container.find("input", attrs={"type": "checkbox"}) or any(k in text for k in ["多选题", "多选"]):
                return QuestionType.MULTIPLE_CHOICE
            return QuestionType.CHOICE

        if blanks:
            return QuestionType.BLANK

        return QuestionType.CHOICE

    def _extract_options(self, container: Tag, page_or_html: Any) -> List[ChoiceOption]:
        """从子题容器中提取选项列表"""
        option_nodes: List[Tag] = []
        for sel in OPTION_SELECTORS:
            nodes = container.select(sel)
            if nodes:
                option_nodes = nodes
                break

        if not option_nodes:
            inputs = container.find_all("input", attrs={"type": ["radio", "checkbox"]})
            for inp in inputs:
                parent = inp.parent
                if parent and parent not in option_nodes:
                    option_nodes.append(parent)

        options: List[ChoiceOption] = []
        choice_ext = ChoiceExtractor()
        for idx, node in enumerate(option_nodes):
            opt_id, opt_text = choice_ext._extract_option_key_and_text(node, idx)
            is_selected = choice_ext._check_option_selected(node, idx, page_or_html)
            selector = choice_ext._generate_option_selector(node, idx)
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

    def _extract_blanks(self, container: Tag, page_or_html: Any) -> List[BlankItem]:
        """从子题容器中提取填空槽位列表"""
        input_nodes: List[Tag] = []
        for sel in BLANK_SELECTORS:
            nodes = container.select(sel)
            if nodes:
                input_nodes = nodes
                break

        blanks: List[BlankItem] = []
        blank_ext = BlankExtractor()
        for idx, node in enumerate(input_nodes):
            index = blank_ext._extract_blank_index(node, idx)
            hint = blank_ext._extract_hint(node)
            current_value = blank_ext._extract_current_value(node, idx, page_or_html)
            prefix, suffix = blank_ext._extract_surrounding_context(node)
            selector = blank_ext._generate_selector(node, idx)
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
