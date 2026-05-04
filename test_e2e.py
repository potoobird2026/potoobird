"""独立 HTTP 请求测试"""
import urllib.request
import urllib.error
import time
import subprocess
import os
import signal

# 启动服务器
os.chdir(r"D:\github\三家PK\qwenpaw\代码")
proc = subprocess.Popen(
    [r"E:\QwenPaw\python.exe", "-m", "uvicorn", "src.entry.web_ui:app",
     "--host", "0.0.0.0", "--port", "8080", "--log-level", "info"],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    cwd=r"D:\github\三家PK\qwenpaw\代码",
)

print(f"Server PID: {proc.pid}")
time.sleep(4)

try:
    # 测试 health
    r = urllib.request.urlopen("http://localhost:8080/api/health", timeout=5)
    print(f"Health: {r.status} {r.read().decode()}")

    # 测试主页
    try:
        r = urllib.request.urlopen("http://localhost:8080", timeout=5)
        print(f"Index: {r.status}, length: {len(r.read())}")
    except urllib.error.HTTPError as e:
        print(f"Index Error: {e.code} {e.reason}")
        print(f"Body: {e.read().decode()[:1000]}")

    # 测试静态文件
    r = urllib.request.urlopen("http://localhost:8080/static/style.css", timeout=5)
    print(f"CSS: {r.status}, length: {len(r.read())}")

finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except:
        proc.kill()
    print("\nServer output:")
    print(proc.stdout.read().decode("utf-8", errors="replace")[-2000:])
