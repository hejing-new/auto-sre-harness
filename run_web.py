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
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()
# 修复 Windows 编码
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# 添加项目根目录到 Python 路径
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

# 设置 PYTHONPATH 环境变量，确保 uvicorn reload 子进程也能找到模块
# 当 reload=True 时，uvicorn 使用 spawn 模式创建子进程，子进程不继承父进程的 sys.path
os.environ["PYTHONPATH"] = os.pathsep.join([
    str(project_root),
    str(project_root / "src"),
    os.environ.get("PYTHONPATH", "")
])

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

# 检查钉钉配置（可选）
dingtalk_webhook = os.getenv("DINGTALK_WEBHOOK_URL")
dingtalk_secret = os.getenv("Dingding_Secret")

print("[DingTalk] 配置状态:")
print(f"   - Webhook: {'已配置' if dingtalk_webhook else '未配置'}")
print(f"   - Secret: {'已配置' if dingtalk_secret else '未配置'}")

if dingtalk_webhook and not dingtalk_secret:
    print("\n[提示] 已配置 DINGTALK_WEBHOOK_URL 但未配置 Dingding_Secret")
    print("      钉钉消息将不生成签名，可能存在安全风险")
    print("      建议在 .env 文件中添加: Dingding_Secret=your-secret")
elif dingtalk_webhook and dingtalk_secret:
    print("   - 状态: 钉钉审批功能已启用")
else:
    print("   - 状态: 钉钉审批功能未启用")

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
        reload=False,
        log_level="info"
    )
