"""高信息密度测试集 Diff 提取器 (Testcase Diff Extractor).

负责从头歌平台实训评测结果面板与控制台中，提纯极简、高密度、低熵的评测反馈：
1. passed: bool (全部通过为 True)
2. pass_ratio: str (如 "1/1", "0/2", "3/5")
3. expected: str (预期输出，清洗掉多余 HTML/脚本与空白杂质)
4. actual: str (实际输出)
5. diff_hint: str (人类与大模型易读的精炼提示)
6. stdout_msg: str (标准控制台输出)
7. error_msg: str (错误日志/异常栈)

严禁向外抛出庞大的 DOM 树或杂质，保持输出极简、聚焦。
"""

import html
import re
from typing import Any, Dict, List, Optional, Tuple, Union
from bs4 import BeautifulSoup, Tag
from playwright.sync_api import Page


# ANSI 转义序列清洗正则
ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def clean_text_content(raw: Optional[str], preserve_trailing_spaces: bool = True) -> str:
    """清洗提取到的文本内容：去除 ANSI 码、反转义实体、规整首尾多余空行。"""
    if not raw:
        return ""
    # 去除 ANSI 终端颜色码
    cleaned = ANSI_ESCAPE_RE.sub("", raw)
    # 反转义 HTML 实体 (&nbsp;, &lt;, &gt;, &amp; 等)
    cleaned = html.unescape(cleaned)
    # 替换不可见特殊空格为普通空格
    cleaned = cleaned.replace("\u00a0", " ").replace("\u200b", "").replace("\ufeff", "")
    # 规整行尾多余空白，保留换行
    if preserve_trailing_spaces:
        lines = [line.rstrip("\r") for line in cleaned.splitlines()]
    else:
        lines = [line.rstrip() for line in cleaned.splitlines()]
    # 去除首尾多余空行
    while len(lines) > 1 and not lines[0].strip():
        lines.pop(0)
    while len(lines) > 1 and not lines[-1].strip():
        lines.pop()
    if len(lines) == 1 and not lines[0]:
        return ""
    return "\n".join(lines)


def _extract_labeled_content(soup: BeautifulSoup, labels: List[str]) -> str:
    """从 HTML 树中定位特定标签 (如 '预期输出', '实际输出') 对应的内容区块。"""
    is_expected = any("预期" in l or "expected" in l.lower() for l in labels)
    is_actual = any("实际" in l or "actual" in l.lower() for l in labels)

    # 1. 优先根据 class 名直接匹配
    if is_expected:
        target_elem = soup.select_one(".expected-output, .expected, [data-test='expected'], .expect-box, .testcase-expected")
        if target_elem:
            return clean_text_content(target_elem.get_text(), preserve_trailing_spaces=True)
    elif is_actual:
        target_elem = soup.select_one(".actual-output, .actual, [data-test='actual'], .actual-box, .testcase-actual")
        if target_elem:
            return clean_text_content(target_elem.get_text(), preserve_trailing_spaces=True)

    # 2. 定位文本标签 (寻找最内层标签元素，避免外层容器干扰)
    for tag_name in ["h4", "h5", "h3", "h6", "label", "span", "b", "strong", "p", "div"]:
        for el in soup.find_all(tag_name):
            text = el.get_text(strip=True)
            if not text:
                continue

            # 确保该元素包含当前目标 label
            if not any(l in text for l in labels):
                continue

            # 排除同时包含对立 label 的外层混杂容器
            if is_expected and any(a in text for a in ["实际输出", "Actual", "你的输出"]):
                continue
            if is_actual and any(e in text for e in ["预期输出", "Expected", "期望输出"]):
                continue

            # 确保 el 为最内层包含目标 label 的元素
            child_matches = [
                c for c in el.find_all(True)
                if any(l in c.get_text(strip=True) for l in labels)
            ]
            if child_matches:
                continue

            # A. 检查自身的同级后续兄弟节点 (如 <h4>预期输出</h4><pre>content</pre>)
            sibling = el.find_next_sibling()
            if sibling:
                sub_pre = sibling.find(["pre", "code"]) or (sibling if sibling.name in ["pre", "code"] else None)
                if sub_pre:
                    return clean_text_content(sub_pre.get_text(), preserve_trailing_spaces=True)
                sib_text = sibling.get_text()
                if sib_text and not any(other in sib_text for other in ["实际输出", "预期输出", "控制台"]):
                    return clean_text_content(sib_text, preserve_trailing_spaces=True)

            # B. 检查父节点的下一个兄弟节点 (如 <div class="title">预期输出</div><div class="content"><pre>...</pre></div>)
            parent = el.parent
            if parent and parent.name != "[document]":
                p_sibling = parent.find_next_sibling()
                if p_sibling:
                    sub_pre = p_sibling.find(["pre", "code"]) or p_sibling
                    sib_text = sub_pre.get_text()
                    if sib_text and not any(other in sib_text for other in ["实际输出", "预期输出", "控制台"]):
                        return clean_text_content(sib_text, preserve_trailing_spaces=True)

            # C. 自身包含 pre / code
            nested_pre = el.find(["pre", "code"])
            if nested_pre:
                return clean_text_content(nested_pre.get_text(), preserve_trailing_spaces=True)

            # D. 单行内文本切分 (如 "预期输出：8")
            for l in labels:
                if l in text:
                    parts = text.split(l, 1)
                    if len(parts) > 1 and parts[1].strip():
                        content = parts[1].lstrip(":： \t\r\n").rstrip("\r\n")
                        if not content and parts[1].lstrip(":："):
                            content = parts[1].lstrip(":：").rstrip("\r\n")
                        if content:
                            return clean_text_content(content, preserve_trailing_spaces=True)

    return ""


def _parse_pass_status_and_ratio(full_text: str) -> Tuple[bool, str]:
    """从评测全文本中解析通过状态与测试集比例。"""
    # 1. 匹配 Educoder 典型的 "共有X组测试集...通过Y组"
    m_educoder = re.search(r"共有\s*(\d+)\s*组测试[集用]?[例]?.*?通过\s*(\d+)\s*组", full_text)
    if m_educoder:
        total = int(m_educoder.group(1))
        passed_cnt = int(m_educoder.group(2))
        ratio = f"{passed_cnt}/{total}"
        return (passed_cnt == total and total > 0), ratio

    # 2. 匹配 "通过 1/1 组测试用例" / "已通过 2/3"
    m_ratio_alt = re.search(r"(?:通过|已通过)\s*(\d+)\s*/\s*(\d+)", full_text)
    if m_ratio_alt:
        passed_cnt = int(m_ratio_alt.group(1))
        total = int(m_ratio_alt.group(2))
        ratio = f"{passed_cnt}/{total}"
        return (passed_cnt == total and total > 0), ratio

    # 3. 匹配通用 "X/Y"
    m_generic = re.search(r"(\d+)\s*/\s*(\d+)", full_text)
    ratio = ""
    passed_count = 0
    total_count = 0
    if m_generic:
        passed_count = int(m_generic.group(1))
        total_count = int(m_generic.group(2))
        if total_count > 0 and total_count <= 100:  # 排除日期或无关大数字
            ratio = f"{passed_count}/{total_count}"

    # 4. 判定通过布尔值
    passed = False
    if ratio and total_count > 0 and passed_count == total_count:
        passed = True
    elif any(k in full_text for k in ["全部通过", "通关成功", "测试通过", "恭喜通过", "通过所有测试用例", "All Passed"]):
        passed = True
        if not ratio:
            ratio = "1/1"

    # 若存在明确错误标识且未满足比例全过，则判定为未通过
    if any(k in full_text for k in ["评测未通过", "错误", "Error", "Traceback", "未通过", "Fail", "AssertionError"]):
        if not (ratio and total_count > 0 and passed_count == total_count):
            passed = False

    return passed, ratio


def _line_by_line_diff(expected: str, actual: str) -> Optional[str]:
    """逐行比对预期与实际输出，优先定位并生成高精度的行级差异提示。

    当某行核心文本一致但存在空白字符（如末尾空格、制表符等）差异时，返回精准的行级提示：
    "第 {i + 1} 行文本一致但空白字符不匹配: 预期={line_exp!r} vs 实际={line_act!r} (请检查末尾空格或制表符)"
    """
    exp_lines = expected.splitlines()
    act_lines = actual.splitlines()

    # 1. 逐行比对共同行
    min_len = min(len(exp_lines), len(act_lines))
    for i in range(min_len):
        line_exp = exp_lines[i]
        line_act = act_lines[i]
        if line_exp != line_act:
            if line_exp.strip() == line_act.strip():
                return f"第 {i + 1} 行文本一致但空白字符不匹配: 预期={line_exp!r} vs 实际={line_act!r} (请检查末尾空格或制表符)"
            if line_exp.lower() == line_act.lower():
                return f"第 {i + 1} 行大小写不匹配: 预期 '{line_exp[:40]}' vs 实际 '{line_act[:40]}'"
            if len(exp_lines) == len(act_lines):
                return f"第 {i + 1} 行内容不匹配: 预期 '{line_exp[:40]}' vs 实际 '{line_act[:40]}'"
            return (
                f"行数不匹配 (预期 {len(exp_lines)} 行, 实际 {len(act_lines)} 行); "
                f"第 {i + 1} 行首度不匹配: 预期 '{line_exp[:40]}' vs 实际 '{line_act[:40]}'"
            )

    # 2. 公共行全部一致但总行数不同
    if len(exp_lines) != len(act_lines):
        return f"行数不匹配: 预期输出 {len(exp_lines)} 行，实际输出 {len(act_lines)} 行"

    return None


line_by_line_diff = _line_by_line_diff


def generate_diff_hint(
    expected: str,
    actual: str,
    error_msg: str,
    passed: bool,
    pass_ratio: str,
) -> str:
    """生成高信息密度、人类与大模型易读的精炼差异提示。"""
    if passed:
        return f"全部通过 ({pass_ratio})" if pass_ratio else "全部通过"

    # 若存在运行时异常报错，优先提示核心异常行
    if error_msg:
        err_lines = [l.strip() for l in error_msg.splitlines() if l.strip()]
        last_err = ""
        for line in reversed(err_lines):
            if any(k in line for k in ["Error", "Exception", "Fail", "错误", "AssertionError"]):
                last_err = line
                break
        if not last_err and err_lines:
            last_err = err_lines[-1]
        if last_err:
            return f"代码执行异常: {last_err}"

    # 比对预期输出与实际输出
    if expected or actual:
        if expected.strip() and not actual.strip():
            return "实际输出为空 (无任何控制台输出或返回值)"

        # 隐形字符/行尾空格不一致专项优先比对
        if expected != actual and expected.strip() == actual.strip():
            return (
                f"⚠️ 核心文本完全一致，但存在隐形空白字符/换行不匹配！"
                f"预期长度 {len(expected)} (尾部 repr: {expected[-10:]!r}) vs "
                f"实际长度 {len(actual)} (尾部 repr: {actual[-10:]!r})。"
                f"请特别检查输出末尾是否缺少或多出空格/换行！"
            )

        if expected == actual:
            return f"当前测试集输出与预期一致 (可能存在其他未通过的隐藏测试集: {pass_ratio})" if pass_ratio else "当前测试集输出与预期一致"

        # 逐行内容与行数比对
        line_diff = _line_by_line_diff(expected, actual)
        if line_diff:
            return line_diff

    if pass_ratio:
        return f"测试用例未通过 ({pass_ratio})"
    return "评测未通过，请结合控制台报错检查代码逻辑"


def extract_testcase_diff(
    page_or_html: Union[Page, str, Any] = "",
    error_output: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """从头歌评测结果 DOM 或 HTML 源码中提取高密度测试集 Diff。

    Args:
        page_or_html: Playwright Page 实例、静态 HTML 字符串或控制台标准输出 stdout
        error_output: 可选的控制台标准错误/异常输出

    Returns:
        dict:
            - passed (bool): 是否全部通过
            - pass_ratio (str): 测试用例通过比例 (如 "1/1", "0/2")
            - expected (str): 预期输出 (已清洗多余格式)
            - actual (str): 实际输出
            - diff_hint (str): 人类与 AI 易读的高密度提示
            - stdout_msg (str): 控制台标准输出
            - error_msg (str): 错误日志或异常栈
    """
    if not page_or_html and "stdout" in kwargs:
        page_or_html = kwargs["stdout"]
    if not error_output and "error_msg" in kwargs:
        error_output = kwargs["error_msg"]

    html_content = ""

    # 1. 统一提取 HTML 源码
    if isinstance(page_or_html, str):
        html_content = page_or_html
    elif hasattr(page_or_html, "content") and callable(page_or_html.content):
        try:
            html_content = page_or_html.content()
        except Exception:
            html_content = ""
    elif hasattr(page_or_html, "inner_html") and callable(page_or_html.inner_html):
        try:
            html_content = page_or_html.inner_html("body")
        except Exception:
            html_content = ""

    if not html_content.strip():
        err = clean_text_content(error_output) if error_output else ""
        return {
            "passed": False,
            "pass_ratio": "",
            "expected": "",
            "actual": "",
            "diff_hint": f"代码执行异常: {err}" if err else "未获取到评测输出",
            "stdout_msg": "",
            "error_msg": err,
        }

    soup = BeautifulSoup(html_content, "html.parser")

    # 清理无用的 script, style 等标签以防干扰
    for tag in soup(["script", "style", "svg", "noscript"]):
        tag.decompose()

    # 0. 若为 Page 实例，优先从 React Fiber 状态树精准提取测试集数据 (避免 canvas/xterm 渲染导致的文本丢失)
    if hasattr(page_or_html, "evaluate"):
        try:
            fiber_data = page_or_html.evaluate("""() => {
                const el = document.querySelector('.test-set-container___JHp4n') || document.querySelector('.item-desc___ivltA') || document.querySelector('.btn-run___fh7pl');
                if (!el) return null;
                const key = Object.keys(el).find(k => k.startsWith('__reactFiber$') || k.startsWith('__reactInternalInstance$'));
                if (!key) return null;
                let curr = el[key];
                while (curr) {
                    if (curr.memoizedProps && curr.memoizedProps.test_sets) return curr.memoizedProps.test_sets;
                    if (curr.memoizedProps && curr.memoizedProps.children && curr.memoizedProps.children.props && curr.memoizedProps.children.props.test_sets) return curr.memoizedProps.children.props.test_sets;
                    curr = curr.return;
                }
                return null;
            }""")
            if fiber_data and isinstance(fiber_data, list) and len(fiber_data) > 0:
                total_cnt = len(fiber_data)
                pass_cnt = sum(1 for ts in fiber_data if ts.get("result") is True)
                ratio_str = f"{pass_cnt}/{total_cnt}"
                is_all_passed = (pass_cnt == total_cnt)

                # 多测试集比对：优先寻找存在隐形字符/行尾空格差异的失败用例
                target_fail = None
                for ts in fiber_data:
                    if ts.get("result") is not True:
                        exp_cand = clean_text_content(ts.get("output", ""), preserve_trailing_spaces=True)
                        act_cand = clean_text_content(ts.get("actual_output", ""), preserve_trailing_spaces=True)
                        if exp_cand != act_cand and exp_cand.strip() == act_cand.strip():
                            target_fail = (exp_cand, act_cand)
                            break

                if target_fail:
                    expected_str, actual_str = target_fail
                else:
                    first_fail = next((ts for ts in fiber_data if ts.get("result") is not True), None)
                    expected_str = clean_text_content(first_fail.get("output", ""), preserve_trailing_spaces=True) if first_fail else ""
                    actual_str = clean_text_content(first_fail.get("actual_output", ""), preserve_trailing_spaces=True) if first_fail else ""

                diff_hint_str = generate_diff_hint(expected_str, actual_str, "", is_all_passed, ratio_str)
                return {
                    "passed": is_all_passed,
                    "pass_ratio": ratio_str,
                    "expected": expected_str,
                    "actual": actual_str,
                    "diff_hint": diff_hint_str,
                    "stdout_msg": f"测试用例通过率: {ratio_str}",
                    "error_msg": "",
                }
        except Exception:
            pass

    full_text = soup.get_text(separator="\n", strip=True)

    # 2. 优先检测通关弹窗 .evaluate-result-container
    modal = soup.select_one(".evaluate-result-container")
    if modal:
        modal_text = modal.get_text(separator=" ", strip=True)
        if any(k in modal_text for k in ["下一关", "通过", "恭喜", "+100", "经验值", "金币"]):
            return {
                "passed": True,
                "pass_ratio": "1/1",
                "expected": "",
                "actual": "",
                "diff_hint": "全部通过 (通关成功)",
                "stdout_msg": modal_text,
                "error_msg": "",
            }

    # 3. 解析通过状态与用例通过比例
    passed, pass_ratio = _parse_pass_status_and_ratio(full_text)

    # 4. 提取预期输出与实际输出
    expected = _extract_labeled_content(soup, ["预期输出", "Expected", "期望输出"])
    actual = _extract_labeled_content(soup, ["实际输出", "Actual", "你的输出"])

    # 兜底：若 DOM 结构较深，尝试通过正则在纯文本中捕获
    if not expected:
        m_exp = re.search(
            r"(?:【?预期输出】?|【?期望输出】?|Expected)\s*[:：]?\s*\n?([\s\S]*?)(?=(?:【?实际输出】?|【?你的输出】?|Actual|【?控制台输出】?|测试说明|\Z))",
            full_text,
            re.IGNORECASE,
        )
        if m_exp:
            exp_cand = m_exp.group(1).rstrip("\r\n")
            if exp_cand.startswith("\n"):
                exp_cand = exp_cand.lstrip("\n")
            # 过滤包含实际输出关键字的情况
            if "实际输出" not in exp_cand and len(exp_cand) < 2000:
                expected = clean_text_content(exp_cand, preserve_trailing_spaces=True)

    if not actual:
        m_act = re.search(
            r"(?:【?实际输出】?|【?你的输出】?|Actual)\s*[:：]?\s*\n?([\s\S]*?)(?=(?:【?预期输出】?|【?期望输出】?|Expected|【?控制台输出】?|测试说明|\Z))",
            full_text,
            re.IGNORECASE,
        )
        if m_act:
            act_cand = m_act.group(1).rstrip("\r\n")
            if act_cand.startswith("\n"):
                act_cand = act_cand.lstrip("\n")
            if "预期输出" not in act_cand and len(act_cand) < 2000:
                actual = clean_text_content(act_cand, preserve_trailing_spaces=True)

    # 5. 提取控制台输出 (stdout) 与 报错日志 (error_msg)
    stdout_lines: List[str] = []
    error_lines: List[str] = []

    # 检查专属控制台/报错容器
    console_elems = soup.select(".console-output, .terminal-window, .error-output, .output-box, pre.output, #console")
    console_text = "\n".join([el.get_text() for el in console_elems]) if console_elems else ""

    text_source = console_text if console_text.strip() else full_text

    # 检测完整的 Python/Java Traceback 异常栈
    tb_match = re.search(
        r"(Traceback \(most recent call last\):[\s\S]*?(?:[A-Za-z]+Error|Exception):[^\n]*)",
        text_source,
    )
    if tb_match:
        error_lines.append(clean_text_content(tb_match.group(1)))

    for line in text_source.splitlines():
        line_s = line.strip()
        if not line_s:
            continue
        # 错误特征行
        if any(k in line_s for k in ["Error", "Exception", "Fail", "Traceback", "未通过", "错误", "AssertionError"]):
            if line_s not in error_lines:
                error_lines.append(line_s)
        elif any(k in line_s for k in ["print", "output", ">>", "INFO", "Result", "测试"]):
            if line_s not in stdout_lines and len(stdout_lines) < 30:
                stdout_lines.append(line_s)

    error_msg = clean_text_content("\n".join(error_lines[:15]))
    stdout_msg = clean_text_content("\n".join(stdout_lines[:30]))

    if error_output and not error_msg:
        error_msg = clean_text_content(error_output)

    # 若通过，则清空报错
    if passed:
        error_msg = ""

    # 6. 生成高密度提示
    diff_hint = generate_diff_hint(expected, actual, error_msg, passed, pass_ratio)

    return {
        "passed": passed,
        "pass_ratio": pass_ratio,
        "expected": expected,
        "actual": actual,
        "diff_hint": diff_hint,
        "stdout_msg": stdout_msg,
        "error_msg": error_msg,
    }


__all__ = [
    "clean_text_content",
    "extract_testcase_diff",
    "generate_diff_hint",
    "_line_by_line_diff",
    "line_by_line_diff",
]
