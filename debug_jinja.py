"""调试 Jinja2 缓存问题"""
import sys, os
os.chdir(r"D:\github\三家PK\qwenpaw\代码")
sys.path.insert(0, r"D:\github\三家PK\qwenpaw\代码")

# 完全隔离的测试
import subprocess
proc = subprocess.Popen(
    [r"E:\QwenPaw\python.exe", "-c", """
import sys, os
os.chdir(r"D:\\github\\三家PK\\qwenpaw\\代码")
sys.path.insert(0, r"D:\\github\\三家PK\\qwenpaw\\代码")

import sqlite3
from pathlib import Path

# 先测试 Jinja2 模板
from starlette.templating import Jinja2Templates
from starlette.requests import Request

# 创建模板实例
templates = Jinja2Templates(directory=str(Path(r"D:\\github\\三家PK\\qwenpaw\\代码") / "templates"))

# 创建假请求
scope = {"type": "http", "method": "GET", "path": "/", "query_string": b"", "headers": []}
request = Request(scope)

# 测试 get_template
try:
    t = templates.get_template("index.html")
    print("get_template OK")
except Exception as e:
    print(f"get_template Error: {e}")

# 测试 TemplateResponse
try:
    resp = templates.TemplateResponse(request, "index.html", {"memory_count": 5, "personality": {"H": 50, "E": 50, "X": 50}})
    print(f"TemplateResponse OK, body length: {len(resp.body)}")
except Exception as e:
    import traceback
    traceback.print_exc()

print("ALL OK")
"""],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    cwd=r"D:\github\三家PK\qwenpaw\代码",
)
out, _ = proc.communicate(timeout=15)
print(out.decode("utf-8", errors="replace"))
