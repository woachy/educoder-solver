"""测试题干表格与多模态结构提纯 (Table to Markdown & Multimodal Cleaners Unit Tests)."""

import pytest
from bs4 import BeautifulSoup

from src.extractor.practical import PracticalExtractor


def test_table_to_markdown_standard():
    html = """
    <table>
      <thead>
        <tr>
          <th>Sno</th>
          <th>Sname</th>
          <th>Age</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>101</td>
          <td>张三</td>
          <td>20</td>
        </tr>
        <tr>
          <td>102</td>
          <td>李四</td>
          <td>22</td>
        </tr>
      </tbody>
    </table>
    """
    soup = BeautifulSoup(html, "html.parser")
    table_el = soup.find("table")
    md = PracticalExtractor.table_to_markdown(table_el)

    assert "| Sno | Sname | Age |" in md
    assert "| --- | --- | --- |" in md
    assert "| 101 | 张三 | 20 |" in md
    assert "| 102 | 李四 | 22 |" in md


def test_table_to_markdown_with_pipes_and_uneven_cells():
    html = """
    <table>
      <tr>
        <td>Col 1</td>
        <td>Col | 2</td>
      </tr>
      <tr>
        <td>Val 1</td>
      </tr>
    </table>
    """
    soup = BeautifulSoup(html, "html.parser")
    table_el = soup.find("table")
    md = PracticalExtractor.table_to_markdown(table_el)

    assert "Col \\| 2" in md
    # 验证第二行自动补齐列数
    assert "| Val 1 |  |" in md


def test_table_to_markdown_empty_or_none():
    assert PracticalExtractor.table_to_markdown(None) == ""
    soup = BeautifulSoup("<table></table>", "html.parser")
    assert PracticalExtractor.table_to_markdown(soup.find("table")) == ""


def test_clean_multimodal_elements():
    html = """
    <div>
      <p>关系模式如下：</p>
      <img src="http://educoder.net/api/attachments/12345/schema_diagram.png" alt="模式关系图" />
      <img src="/api/attachments/88888/student_table.png" />
      <img src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==" alt="base64图标" />
      <img src="https://example.com/images/normal.jpg" />
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    div_node = soup.find("div")
    PracticalExtractor.clean_multimodal_elements(div_node)

    text = div_node.get_text()
    assert "[附图说明: 模式关系图]" in text
    assert "[附图说明: student_table.png]" in text
    assert "[图片: base64图标]" in text
    assert "data:image" not in text
    assert "base64,iVB" not in text
    assert "[图片: normal.jpg]" in text


def test_full_extract_with_table_and_image():
    html = """
    <div class="shixun-left">
      <h2 class="title">SQL数据插入实训</h2>
      <div class="task-description">
        <h3>任务描述</h3>
        <p>本关任务：根据给出的学生表结构与数据向数据库中插入记录。</p>
        <img src="/api/attachments/999/student_info.png" alt="学生表字段说明" />
        <table>
          <tr>
            <th>学号</th>
            <th>姓名</th>
            <th>专业</th>
          </tr>
          <tr>
            <td>2026001</td>
            <td>王小明</td>
            <td>计算机科学与技术</td>
          </tr>
        </table>
      </div>
      <div class="task-requirements">
        <h3>编程要求</h3>
        <p>请编写 INSERT 语句完成数据插入。</p>
      </div>
    </div>
    <div class="monaco-editor">
      <div class="view-lines">
        <div class="view-line">-- Begin --</div>
        <div class="view-line">INSERT INTO student VALUES ('2026001', '王小明', 'CS');</div>
        <div class="view-line">-- End --</div>
      </div>
    </div>
    """
    extractor = PracticalExtractor()
    assert extractor.can_extract(html) is True

    q = extractor.extract(html)
    assert q.title == "SQL数据插入实训"
    assert "[附图说明: 学生表字段说明]" in q.description
    assert "| 学号 | 姓名 | 专业 |" in q.description
    assert "| 2026001 | 王小明 | 计算机科学与技术 |" in q.description
    assert q.practical_details.has_target_marker is True
