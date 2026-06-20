"""
Auto-SRE Web 管理界面 - FastAPI 后端

功能：
1. 提供静态 HTML 页面渲染
2. 异步 API 路由触发 Agent 诊断
3. SSE 实时推送 Agent 日志

启动命令：
    uvicorn src.web.app:app --reload --host 0.0.0.0 --port 8000
"""

import sys
import json
import asyncio
from pathlib import Path
from typing import AsyncGenerator
from datetime import datetime

# 修复 Windows 编码
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# 添加项目根目录到 Python 路径
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

# 导入核心组件
from executor import DockerExecutor
from utils.llm_client import LLMClient
from security.interceptor import CommandInterceptor
from core.memory import ContextManager
from agent.engine import AgentEngine
from agent.subagents import LogAnalyzerAgent

# ==========================================
# 全局变量
# ==========================================

app = FastAPI(
    title="Auto-SRE 自动化运维总控台",
    description="基于 AI Agent 的自动化 SRE 诊断系统",
    version="1.0.0"
)

# 日志队列（用于 SSE 推送）
log_queue: asyncio.Queue = asyncio.Queue()

# Agent 运行状态
agent_running = False
agent_result: Optional[dict] = None


# ==========================================
# 数据模型
# ==========================================

class AlertRequest(BaseModel):
    """告警请求模型"""
    alert: str
    container: str = "auto-sre-sandbox"
    max_iterations: int = 10


class LogEntry(BaseModel):
    """日志条目模型"""
    timestamp: str
    level: str  # INFO, REASONING, INTERCEPTING, EXECUTING, BLOCKED, ERROR, SUCCESS
    message: str
    details: Optional[dict] = None


# ==========================================
# 自定义日志处理器
# ==========================================

class QueueHandler:
    """将日志推送到 asyncio 队列的处理器"""

    def __init__(self, queue: asyncio.Queue):
        self.queue = queue

    async def log(self, level: str, message: str, details: dict = None):
        """发送日志到队列"""
        entry = LogEntry(
            timestamp=datetime.now().strftime("%H:%M:%S.%f")[:-3],
            level=level,
            message=message,
            details=details
        )
        await self.queue.put(entry.dict())


# ==========================================
# 页面路由
# ==========================================

@app.get("/", response_class=HTMLResponse)
async def index():
    """返回主页面 HTML"""
    html_path = Path(__file__).parent / "templates" / "index.html"
    return html_path.read_text(encoding="utf-8")


# ==========================================
# API 路由
# ==========================================

@app.post("/api/trigger-agent")
async def trigger_agent(request: AlertRequest):
    """
    触发 Agent 诊断

    异步启动 AgentEngine，开始诊断流程。
    日志通过 SSE 实时推送到前端。
    """
    global agent_running, agent_result

    if agent_running:
        raise HTTPException(status_code=409, detail="Agent 正在运行中，请等待完成")

    # 重置状态
    agent_running = True
    agent_result = None
    log_queue = asyncio.Queue()

    # 启动异步任务
    asyncio.create_task(run_agent_task(request, log_queue))

    return {
        "status": "started",
        "message": "Agent 诊断已启动",
        "alert": request.alert
    }


async def run_agent_task(request: AlertRequest, queue: asyncio.Queue):
    """异步运行 Agent 任务"""
    global agent_running, agent_result

    handler = QueueHandler(queue)

    try:
        # 步骤 1: 初始化组件
        await handler.log("INFO", "初始化 Agent 组件...")

        # Docker 执行器
        await handler.log("INFO", "连接 Docker 容器...")
        executor = DockerExecutor(container_name=request.container)
        await handler.log("SUCCESS", f"已连接到容器: {request.container}")

        # LLM 客户端
        await handler.log("INFO", "初始化 LLM 客户端...")
        llm = LLMClient()
        await handler.log("SUCCESS", f"LLM 模型: {llm.model}")

        # 拦截器
        await handler.log("INFO", "初始化命令拦截器...")
        interceptor = CommandInterceptor(strict_mode=True)

        # 上下文管理器
        await handler.log("INFO", "初始化上下文管理器...")
        context_manager = ContextManager(max_turns=20, tail_turns=5)

        # 日志分析器
        await handler.log("INFO", "初始化日志分析子智能体...")
        log_analyzer = LogAnalyzerAgent(executor=executor)

        # 步骤 2: 创建 Agent 引擎
        await handler.log("INFO", "创建 Agent 引擎...")
        engine = AgentEngine(
            executor=executor,
            llm_client=llm,
            interceptor=interceptor,
            context_manager=context_manager,
            log_analyzer=log_analyzer,
            max_iterations=request.max_iterations
        )

        # 步骤 3: 运行 Agent Loop
        await handler.log("REASONING", f"开始诊断: {request.alert}")

        # 自定义步骤处理器，用于推送日志
        original_handler = engine.on_step

        def custom_step_handler(step):
            # 推送步骤日志
            if step.llm_response:
                asyncio.create_task(
                    handler.log("REASONING", f"LLM 思考: {step.llm_response.thinking}")
                )
            if step.command:
                asyncio.create_task(
                    handler.log("EXECUTING", f"执行命令: {step.command}")
                )
            if step.intercept_result:
                status = "PASS" if step.intercept_result.allowed else "BLOCKED"
                asyncio.create_task(
                    handler.log("INTERCEPTING", f"拦截检查: {status} - {step.intercept_result.reason}")
                )
            if step.execute_result:
                exit_code = step.execute_result.get("exit_code", -1)
                stdout_preview = step.execute_result.get("stdout", "")[:100]
                asyncio.create_task(
                    handler.log("INFO", f"执行结果 (exit_code={exit_code}): {stdout_preview}")
                )

        engine.on_step = custom_step_handler

        # 运行引擎
        result = engine.run(request.alert)

        # 步骤 4: 输出结果
        if result.success:
            await handler.log("SUCCESS", "诊断完成！")
            await handler.log("SUCCESS", f"RCA 报告: {result.final_analysis[:200]}...")
        else:
            await handler.log("ERROR", "诊断失败或未完成")

        # 保存结果
        agent_result = {
            "success": result.success,
            "total_steps": result.total_steps,
            "commands_executed": result.commands_executed,
            "commands_blocked": result.commands_blocked,
            "final_analysis": result.final_analysis,
            "compression_stats": result.compression_stats
        }

        # 发送完成信号
        await handler.log("DONE", "诊断流程结束", {"result": agent_result})

    except Exception as e:
        await handler.log("ERROR", f"Agent 运行异常: {str(e)}")
        agent_result = {"success": False, "error": str(e)}

    finally:
        agent_running = False


@app.get("/api/logs")
async def stream_logs():
    """
    SSE 日志流

    实时推送 Agent 执行过程中的日志到前端。
    """
    async def event_generator() -> AsyncGenerator[str, None]:
        while True:
            try:
                # 等待日志，超时则发送心跳
                log_entry = await asyncio.wait_for(log_queue.get(), timeout=1.0)
                yield f"data: {json.dumps(log_entry, ensure_ascii=False)}\n\n"
            except asyncio.TimeoutError:
                # 发送心跳保持连接
                yield f"data: {json.dumps({'type': 'heartbeat', 'timestamp': datetime.now().isoformat()}, ensure_ascii=False)}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
                break

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@app.get("/api/status")
async def get_status():
    """获取 Agent 运行状态"""
    return {
        "running": agent_running,
        "result": agent_result
    }


# ==========================================
# 启动入口
# ==========================================

if __name__ == "__main__":
    import uvicorn

    print("="*60)
    print("[Auto-SRE Web] 启动管理界面")
    print("="*60)
    print("访问地址: http://localhost:8000")
    print("API 文档: http://localhost:8000/docs")
    print("="*60)

    uvicorn.run(
        "src.web.app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
