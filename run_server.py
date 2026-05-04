"""启动 Web 服务器"""
import sys
import os

os.chdir(r"D:\github\三家PK\qwenpaw\代码")
sys.path.insert(0, r"D:\github\三家PK\qwenpaw\代码")

import uvicorn

uvicorn.run(
    "src.entry.web_ui:app",
    host="0.0.0.0",
    port=8080,
    log_level="debug",
)
