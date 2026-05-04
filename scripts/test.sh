#!/bin/bash
# Long Agent 一键运行测试脚本

set -e

echo "🧪 Long Agent 测试"
echo "===================="

# 激活虚拟环境
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# 运行测试
echo "📋 运行测试..."
python -m pytest tests/ -v --tb=short --cov=src --cov-report=term-missing

echo ""
echo "✅ 测试完成！"
