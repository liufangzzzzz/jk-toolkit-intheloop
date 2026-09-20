#!/bin/zsh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

if [[ -n "${PYTHON_BIN:-}" ]]; then
  PYTHON_BIN="$PYTHON_BIN"
elif command -v python3.12 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3.12)"
elif command -v python3.13 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3.13)"
else
  PYTHON_BIN="$(command -v python3)"
fi

if [[ -z "$PYTHON_BIN" ]]; then
  echo "没有找到 Python 3，请先安装 Python 后再重试。"
  exit 1
fi

if [[ ! -x .venv312/bin/python ]]; then
  "$PYTHON_BIN" -m venv .venv312
fi

if ! .venv312/bin/python -c 'import bs4, fastapi, feishu_docx, mammoth, multipart, PIL, playwright, uvicorn' 2>/dev/null; then
  .venv312/bin/pip install -r backend/requirements.txt
  .venv312/bin/python -m playwright install chromium
fi

if [[ ! -d node_modules ]]; then
  npm install
fi

cleanup() {
  [[ -n "${BACKEND_PID:-}" ]] && kill "$BACKEND_PID" 2>/dev/null || true
  [[ -n "${FRONTEND_PID:-}" ]] && kill "$FRONTEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

ITL_SETTINGS_PATH="$PROJECT_DIR/.local-data/toolkit-settings.json" ITL_COOKIE_SECURE=false PYTHONPATH=backend .venv312/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!
npm run dev -- --hostname localhost &
FRONTEND_PID=$!

sleep 3
open http://localhost:3000
echo "本机测试版已打开：http://localhost:3000"
echo "关闭这个终端窗口即可停止服务。"
wait
