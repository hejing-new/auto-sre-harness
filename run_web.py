#!/usr/bin/env python3
"""
Auto-SRE Web 管理界面 - 启动脚本

使用方式:
    python run_web.py

或者使用 uvicorn 直接启动:
    uvicorn src.web.app:app --reload --host 0.0.0.0 --port 8000
"""

import sys
import os
from pathlib import Path

# 修复 Windows 编码
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# 添加项目根目录到 Python 路径
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

# 检查环境变量
required_env_vars = ["LLM_API_KEY"]
missing_vars = [var for var in required_env_vars if not os.getenv(var)]

if missing_vars:
    print("="*60)
    print("[警告] 缺少以下环境变量:")
    for var in missing_vars:
        print(f"  - {var}")
    print("\n请设置环境变量后再启动:")
    print('  $env:LLM_API_KEY="your-api-key"')
    print("="*60)
    print()

# 启动 FastAPI 服务
if __name__ == "__main__":
    import uvicorn

    print("="*60)
    print("[Auto-SRE Web] 启动管理界面")
    print("="*60)
    print()
    print("  访问地址: http://localhost:8000")
    print("  API 文档: http://localhost:8000/docs")
    print()
    print("  按 Ctrl+C 停止服务")
    print("="*60)
    print()

    uvicorn.run(
        "src.web.app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
