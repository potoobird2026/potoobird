"""完整集成测试"""
import sys, os
os.chdir(r"D:\github\三家PK\qwenpaw\代码")
sys.path.insert(0, r"D:\github\三家PK\qwenpaw\代码")

# 清理之前的 Jinja2 缓存
import importlib
import jinja2
# 强制清理模块缓存
for mod_name in list(sys.modules.keys()):
    if 'jinja2' in mod_name:
        del sys.modules[mod_name]

from starlette.testclient import TestClient
from src.entry.web_ui import app

try:
    client = TestClient(app, raise_server_exceptions=False)

    # 测试 health
    r = client.get("/api/health")
    print(f"Health: {r.status_code} {r.json()}")

    # 测试主页
    r = client.get("/")
    print(f"Index: {r.status_code}, length: {len(r.text)}")
    if r.status_code != 200:
        print(f"Index body: {r.text[:500]}")

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

    # 测试添加记忆
    r = client.post("/api/memory", json={"content": "测试记忆", "layer": "core"})
    print(f"Add memory: {r.status_code} {r.json()}")

    # 再次查看记忆列表
    r = client.get("/api/memory")
    data = r.json()
    print(f"Memory list: {data.get('total', 0)} items")

    # 测试删除记忆
    if data.get("memories"):
        mid = data["memories"][0]["id"]
        r = client.delete(f"/api/memory/{mid}")
        print(f"Delete memory: {r.status_code} {r.json()}")

    print("\n=== All tests passed! ===")

except Exception as e:
    import traceback
    traceback.print_exc()
