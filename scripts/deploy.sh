#!/bin/bash
# Long Agent 一键部署脚本

set -e

echo "🚀 Long Agent 部署"
echo "===================="

# 激活虚拟环境
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# 运行测试
echo "📋 运行测试..."
python -m pytest tests/ -q --tb=short

# 检查覆盖率
echo "📊 检查覆盖率..."
python -m pytest tests/ -q --cov=src --cov-report=term-missing | grep "TOTAL"

# 构建
echo "🏗️ 构建..."
pip install -e .

echo ""
echo "✅ 部署完成！"
echo ""
echo "启动方式："
echo "  CLI:  python -m src.entry.cli run"
echo "  Web:  python -m uvicorn src.entry.web_ui:app --host 0.0.0.0 --port 8080"
