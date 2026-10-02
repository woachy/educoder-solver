"""测试所需的静态 HTML 仿真样本 (HTML Fixtures for Educoder Testing).

仿真头歌平台的实际 DOM 结构：
- 单选题、多选题、判断题
- 填空题 (行内嵌入式与槽位式)
- 编程实训题 (双栏布局 + Monaco 仿真结构 + Begin-End 标记)
"""

SINGLE_CHOICE_HTML = """
<!DOCTYPE html>
<html>
<head><title>单选题 - 头歌实训</title></head>
<body>
<div class="subject-item test-question" id="question_101">
    <div class="subject-title">
        <span class="type-tag">[单选题]</span> 1. 下列关于 Python 列表的描述中，错误的是（ ）
    </div>
    <ul class="subject-options options-list">
        <li class="option-item">
            <input type="radio" name="opt_101" id="opt_a" value="A">
            <span class="option-key">A</span>
            <span class="option-content">列表是可变序列</span>
        </li>
        <li class="option-item checked selected">
            <input type="radio" name="opt_101" id="opt_b" value="B" checked>
            <span class="option-key">B</span>
            <span class="option-content">列表元素必须为同一种类型</span>
        </li>
        <li class="option-item">
            <input type="radio" name="opt_101" id="opt_c" value="C">
            <span class="option-key">C</span>
            <span class="option-content">支持使用 append() 方法在末尾追加元素</span>
        </li>
        <li class="option-item">
            <input type="radio" name="opt_101" id="opt_d" value="D">
            <span class="option-key">D</span>
            <span class="option-content">支持切片与负数索引</span>
        </li>
    </ul>
</div>
</body>
</html>
"""

MULTIPLE_CHOICE_HTML = """
<!DOCTYPE html>
<html>
<head><title>多选题 - 头歌实训</title></head>
<body>
<div class="subject-item multiple-choice" id="question_102">
    <h3 class="subject-title">
        【多选题】以下哪些属于 Python 中的不可变数据类型？
    </h3>
    <div class="options-container">
        <label class="option-item ant-checkbox-wrapper ant-checkbox-checked">
            <input type="checkbox" name="m_opt" value="A" checked>
            <span class="option-key">A</span>
            <span class="option-text">int (整型)</span>
        </label>
        <label class="option-item ant-checkbox-wrapper">
            <input type="checkbox" name="m_opt" value="B">
            <span class="option-key">B</span>
            <span class="option-text">list (列表)</span>
        </label>
        <label class="option-item ant-checkbox-wrapper ant-checkbox-checked">
            <input type="checkbox" name="m_opt" value="C" checked>
            <span class="option-key">C</span>
            <span class="option-text">str (字符串)</span>
        </label>
        <label class="option-item ant-checkbox-wrapper ant-checkbox-checked">
            <input type="checkbox" name="m_opt" value="D" checked>
            <span class="option-key">D</span>
            <span class="option-text">tuple (元组)</span>
        </label>
    </div>
</div>
</body>
</html>
"""

JUDGMENT_HTML = """
<!DOCTYPE html>
<html>
<head><title>判断题 - 头歌实训</title></head>
<body>
<div class="question-item judgment-item" id="question_103">
    <div class="question-title">
        【判断题】Python 中的字典键必须是可哈希（不可变）的对象。
    </div>
    <div class="option-group">
        <div class="option-item checked">
            <input type="radio" name="judge_103" value="正确" checked>
            <span class="option-content">正确</span>
        </div>
        <div class="option-item">
            <input type="radio" name="judge_103" value="错误">
            <span class="option-content">错误</span>
        </div>
    </div>
</div>
</body>
</html>
"""

BLANK_HTML = """
<!DOCTYPE html>
<html>
<head><title>填空题 - 头歌实训</title></head>
<body>
<div class="subject-item blank-question" id="question_104">
    <div class="subject-title">
        【填空题】Python 基础语法填空
    </div>
    <div class="subject-stem">
        在 Python 中，使用
        <input type="text" class="blank-input" data-index="1" placeholder="请输入函数名" value="print">
        函数向控制台输出内容，使用
        <input type="text" class="blank-input" data-index="2" placeholder="请输入函数名" value="">
        函数获取键盘输入。
    </div>
</div>
</body>
</html>
"""

PRACTICAL_HTML = """
<!DOCTYPE html>
<html>
<head><title>实训关卡 - 两数之和 - educoder.net</title></head>
<body>
<div class="shixun-workspace">
    <!-- 左侧任务描述与说明 -->
    <div class="shixun-left task-description">
        <h2 class="task-title">第1关：两数之和</h2>
        <h3>任务描述</h3>
        <p>本关任务：编写一个 Python 函数，计算并返回两个正整数的和。</p>
        <h3>相关知识</h3>
        <p>掌握 Python 中函数的定义以及基本的算术运算操作符。</p>
        <h3>编程要求</h3>
        <p>请仔细阅读右侧编辑器代码，结合相关知识，在 Begin-End 区域内补充代码。</p>
        <h3>测试说明</h3>
        <p>输入：3 5</p>
        <p>输出：8</p>
        <h3>评测说明</h3>
        <p>平台将使用 5 组测试用例验证代码的正确性。</p>
    </div>

    <!-- 右侧 Monaco 在线编辑器区域 -->
    <div class="shixun-right">
        <div class="editor-header">
            <span class="file-tab">solution.py</span>
        </div>
        <div class="monaco-editor" id="monaco-editor">
            <div class="view-lines">
                <div class="view-line"># -*- coding: utf-8 -*-</div>
                <div class="view-line">def solve(a, b):</div>
                <div class="view-line">    # ********** Begin **********</div>
                <div class="view-line">    return a + b</div>
                <div class="view-line">    # ********** End **********</div>
            </div>
        </div>
    </div>
</div>
</body>
</html>
"""

PRACTICAL_NO_MARKER_HTML = """
<!DOCTYPE html>
<html>
<head><title>自由编程实训 - educoder.net</title></head>
<body>
<div class="shixun-left task-description">
    <h3 class="title">全量实现快速排序</h3>
    <p>任务描述：请实现一个完整的快速排序算法。</p>
</div>
<div class="code-editor">
    <div class="file-tab">quick_sort.py</div>
    <textarea class="editor">
def quick_sort(arr):
    if len(arr) <= 1:
        return arr
    pivot = arr[len(arr) // 2]
    left = [x for x in arr if x < pivot]
    middle = [x for x in arr if x == pivot]
    right = [x for x in arr if x > pivot]
    return quick_sort(left) + middle + quick_sort(right)
    </textarea>
</div>
</body>
</html>
"""
