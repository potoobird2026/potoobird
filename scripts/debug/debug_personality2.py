import re
import tempfile
from pathlib import Path

content = (
    "# 人格配置\n\n"
    "| 维度 | 分值 | 说明 |\n"
    "|------|------|------|\n"
    "| H | 60 | 诚实-谦逊 |\n"
    "| E | 40 | 情绪性 |\n"
)

with tempfile.TemporaryDirectory() as d:
    p = Path(d, "personality.md")
    p.write_text(content, encoding="utf-8")

    with open(p, "r", encoding="utf-8") as f:
        lines = f.readlines()

    print("原始行:")
    for i, line in enumerate(lines):
        print(f"  {i}: {repr(line)}")

    # 过滤空行和分隔行
    data_lines = [
        line for line in lines
        if line.strip() and not re.match(r'^\|[-| ]+\|$', line.strip())
    ]

    print(f"\n过滤后行 ({len(data_lines)}):")
    for i, line in enumerate(data_lines):
        print(f"  {i}: {repr(line)}")

    headers = [h.strip() for h in data_lines[0].split("|") if h.strip()]
    print(f"\n表头: {headers}")

    for line in data_lines[1:]:
        cells = [c.strip() for c in line.split("|") if c.strip()]
        print(f"行 cells: {cells}, len={len(cells)}, headers_len={len(headers)}")
