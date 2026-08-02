#!/usr/bin/env bash
# GraphRAG Agent Backend - 一键启动脚本
# 使用 uv 创建虚拟环境并安装所有依赖

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  GraphRAG Agent Backend v2.0 启动脚本"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 1. 检查 uv
if ! command -v uv &>/dev/null; then
  echo "❌ 未找到 uv，请先安装：curl -LsSf https://astral.sh/uv/install.sh | sh"
  exit 1
fi
echo "✅ uv $(uv --version)"

# 2. 创建/激活虚拟环境
if [ ! -d ".venv" ]; then
  echo "→ 创建虚拟环境 .venv ..."
  uv venv .venv
fi
source .venv/bin/activate
echo "✅ 虚拟环境就绪：$(python --version)"

# 3. 安装依赖
echo "→ 安装依赖（含 test 组）..."
uv pip install -e ".[test]" --quiet
echo "✅ 依赖安装完成"

# 4. 准备存储目录
mkdir -p storage/uploads storage/kg
echo "✅ 存储目录就绪"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  启动 FastAPI 服务（后台）..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-level warning &
SERVER_PID=$!
echo "✅ 服务已启动 PID=$SERVER_PID，端口 8000"

# 等待服务就绪
sleep 2
for i in {1..10}; do
  if curl -s http://localhost:8000/api/v1/health >/dev/null 2>&1; then
    echo "✅ 服务健康检查通过"
    break
  fi
  sleep 1
done

echo ""
echo "  API 文档：http://localhost:8000/docs"
echo ""
echo "  使用 Ctrl+C 停止服务"
wait $SERVER_PID
