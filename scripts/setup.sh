#!/bin/bash
# Long Agent 一键搭建环境脚本

set -e

echo "🚀 Long Agent 环境搭建"
echo "========================"

# 检查 Python 版本
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "📌 Python 版本: $python_version"

# 创建虚拟环境
if [ ! -d "venv" ]; then
    echo "📦 创建虚拟环境..."
    python3 -m venv venv
fi

# 激活虚拟环境
source venv/bin/activate

# 安装依赖
echo "📦 安装依赖..."
pip install -e ".[dev]"

# 安装 Web UI 依赖
echo "📦 安装 Web UI 依赖..."
pip install fastapi uvicorn jinja2 python-multipart

# 创建必要目录
echo "📁 创建数据目录..."
mkdir -p data/backups logs

# 复制环境变量模板
if [ ! -f ".env" ]; then
    echo "📝 创建 .env 文件..."
    cp .env.example .env
    echo "⚠️  请编辑 .env 文件，填入你的 API Key"
fi

echo ""
echo "✅ 环境搭建完成！"
echo ""
echo "启动方式："
echo "  CLI:     python -m src.entry.cli run"
echo "  Web UI:  python -m uvicorn src.entry.web_ui:app --host 0.0.0.0 --port 8080"
echo "  测试:    ./scripts/test.sh"
