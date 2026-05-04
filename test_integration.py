"""完整集成测试 - 模拟 FastAPI 请求"""
import asyncio
import sys
import os

os.chdir(r"D:\github\三家PK\qwenpaw\代码")
sys.path.insert(0, r"D:\github\三家PK\qwenpaw\代码")

from starlette.testclient import TestClient
from starlette.requests import Request
from src.entry.web_ui import app
from pathlib import Path

# 先清理 Jinja2 缓存 - 强制重新加载模板
import jinja2
jinja2.Environment._load_template = jinja2.Environment._load_template

try:
    client = TestClient(app, raise_server_exceptions=False)
    print("TestClient created")

    # 测试 health
    r = client.get("/api/health")
    print(f"Health: {r.status_code} {r.json()}")

    # 测试主页
    r = client.get("/")
    print(f"Index: {r.status_code}")
    if r.status_code != 200:
        print(f"Index body: {r.text[:1000]}")
    else:
        print(f"Index length: {len(r.text)}")

    # 测试静态文件
    r = client.get("/static/style.css")
    print(f"CSS: {r.status_code}, length: {len(r.text)}")

    r = client.get("/static/app.js")
    print(f"JS: {r.status_code}, length: {len(r.text)}")

    # 测试 memory API
    r = client.get("/api/memory")
    print(f"Memory: {r.status_code} {r.json()}")

    # 测试 personality API
    r = client.get("/api/personality")
    print(f"Personality: {r.status_code} {r.json()}")

except Exception as e:
    import traceback
    traceback.print_exc()
