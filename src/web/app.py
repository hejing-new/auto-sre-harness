"""
Auto-SRE Web 管理界面 - FastAPI 后端

功能：
1. 提供静态 HTML 页面渲染
2. SSE 流式诊断端点（实时推送 Agent 日志）
3. 钉钉审批回调

启动命令：
    uvicorn src.web.app:app --reload --host 0.0.0.0 --port 8000
"""

import sys
import os
import json
import asyncio
from pathlib import Path
from typing import AsyncGenerator, Optional
from datetime import datetime

# 修复 Windows 编码
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# 添加项目根目录到 Python 路径
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# 导入核心组件
from executor import DockerExecutor
from utils.llm_client import LLMClient
from security.interceptor import CommandInterceptor
from core.memory import ContextManager
from core.log_broadcaster import LogBroadcaster, get_broadcaster, LogLevel
from web.history_store import history_store
from agent.engine import AgentEngine
from agent.subagents import LogAnalyzerAgent

# ==========================================
# 加载 .env 文件
# ==========================================
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print("[App] 已加载 .env 文件")
except ImportError:
    pass

# ==========================================
# 初始化钉钉机器人（如果配置了 Webhook）
# ==========================================
try:
    from utils.dingtalk_bot import init_dingtalk_bot
    dingtalk_webhook = os.getenv("DINGTALK_WEBHOOK_URL")
    if dingtalk_webhook:
        init_dingtalk_bot(dingtalk_webhook)
        print("[App] 钉钉机器人已启用")
    else:
        print("[App] 未配置 DINGTALK_WEBHOOK_URL，钉钉审批功能未启用")
except ImportError:
    print("[App] dingtalk_bot 模块未安装，钉钉审批功能未启用")
except Exception as e:
    print(f"[App] 钉钉机器人初始化失败: {e}")

# ==========================================
# 全局变量
# ==========================================

app = FastAPI(
    title="Auto-SRE 自动化运维总控台",
    description="基于 AI Agent 的自动化 SRE 诊断系统",
    version="1.0.0"
)

# Agent 运行状态（保留用于 /api/status）
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
# 页面路由
# ==========================================

@app.get("/", response_class=HTMLResponse)
async def index():
    dist_path = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist" / "index.html"
    if dist_path.exists():
        return dist_path.read_text(encoding="utf-8")
    html_path = Path(__file__).parent / "templates" / "index.html"
    return html_path.read_text(encoding="utf-8")


# ==========================================
# API 路由
# ==========================================

@app.get("/api/stream-diagnose")
async def stream_diagnose(
    alert: str = Query(..., description="告警信息", min_length=1),
    container: str = Query("auto-sre-sandbox", description="容器名称"),
    max_iterations: int = Query(10, description="最大迭代次数", ge=1, le=50)
):
    """
    SSE 流式诊断端点

    实时推送 Agent 诊断过程的全部日志（思考、执行、拦截、结果）。
    前端通过 EventSource 连接此端点即可获得实时流式输出。

    参数:
        alert: 告警信息（必填）
        container: 容器名称（默认 auto-sre-sandbox）
        max_iterations: 最大迭代次数（默认 10，最大 50）

    SSE 事件格式:
        - {"type": "log", "timestamp": ..., "level": ..., "message": ...}
        - {"type": "done", "timestamp": ..., "level": "DONE", "details": {"result": ...}}
        - {"type": "error", "timestamp": ..., "message": ...}
    """
    # 重置日志广播器（新会话）
    LogBroadcaster.reset_instance()
    broadcaster = await get_broadcaster()

    async def event_generator() -> AsyncGenerator[str, None]:
        # 订阅日志广播器
        queue = await broadcaster.subscribe()

        try:
            # 在后台运行 Agent
            asyncio.create_task(
                _run_agent_and_log(alert, container, max_iterations)
            )

            # 持续消费日志队列
            while True:
                try:
                    entry = await asyncio.wait_for(queue.get(), timeout=120.0)

                    # None 表示流结束（理论上不会到这里，由 DONE 事件处理）
                    if entry is None:
                        break

                    # 序列化为 SSE 格式
                    yield f"data: {json.dumps(entry, ensure_ascii=False)}\n\n"

                    # 如果收到 DONE 事件，结束流
                    if entry.get("type") == "done":
                        break

                except asyncio.TimeoutError:
                    # 发送心跳保持连接（前端可忽略）
                    yield f"data: {json.dumps({'type': 'heartbeat', 'timestamp': datetime.now().isoformat()}, ensure_ascii=False)}\n\n"

        except asyncio.CancelledError:
            # 客户端断开连接（正常行为，不记录错误）
            pass
        except Exception as e:
            # 其他异常，发送错误信息给前端
            error_entry = {
                "timestamp": datetime.now().strftime("%H:%M:%S.%f")[:-3],
                "level": "ERROR",
                "message": f"流式传输异常: {str(e)}",
                "type": "error"
            }
            yield f"data: {json.dumps(error_entry, ensure_ascii=False)}\n\n"
        finally:
            # 确保取消订阅
            await broadcaster.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


async def _run_agent_and_log(alert: str, container: str, max_iterations: int):
    """
    运行 AgentEngine 并通过 LogBroadcaster 推送日志。

    此函数作为后台任务运行，负责：
    1. 初始化 Agent 组件
    2. 注册回调以捕获每一步的日志
    3. 运行 Agent Loop
    4. 通过 broadcaster.complete() 发送完成信号
    """
    broadcaster = await get_broadcaster()

    try:
        # === 步骤 1: 初始化组件 ===
        await broadcaster.log_info("初始化 Agent 组件...")

        await broadcaster.log_info("连接 Docker 容器...")
        executor = DockerExecutor(container_name=container)
        await broadcaster.log_success(f"已连接到容器: {container}")

        await broadcaster.log_info("初始化 LLM 客户端...")
        llm = LLMClient()
        await broadcaster.log_success(f"LLM 模型: {llm.model}")

        await broadcaster.log_info("初始化命令拦截器...")
        interceptor = CommandInterceptor(strict_mode=True)

        await broadcaster.log_info("初始化上下文管理器...")
        context_manager = ContextManager(max_turns=20, tail_turns=5)

        await broadcaster.log_info("初始化日志分析子智能体...")
        log_analyzer = LogAnalyzerAgent(executor=executor)

        # === 步骤 2: 创建 Agent 引擎 ===
        await broadcaster.log_info("创建 Agent 引擎...")

        # 定义回调函数，将每一步的日志推送到广播器
        def on_step_callback(step):
            """Agent 每步执行的回调（在线程中运行，使用同步方法）"""
            # 使用同步方法，避免阻塞主事件循环
            if step.llm_response:
                if isinstance(step.llm_response, dict):
                    thinking = step.llm_response.get("content", "")
                else:
                    thinking = getattr(step.llm_response, "thinking", "")
                if thinking:
                    broadcaster.log_reasoning_sync(f"LLM 思考: {thinking}")

            if step.command:
                broadcaster.log_executing_sync(f"执行命令: {step.command}")

            if step.intercept_result:
                status = "PASS" if step.intercept_result.allowed else "BLOCKED"
                broadcaster.log_intercepting_sync(
                    f"拦截检查: {status} - {step.intercept_result.reason}"
                )

            if step.execute_result:
                exit_code = step.execute_result.get("exit_code", -1)
                stdout_preview = step.execute_result.get("stdout", "")[:100]
                broadcaster.log_info_sync(
                    f"执行结果 (exit_code={exit_code}): {stdout_preview}"
                )

        engine = AgentEngine(
            executor=executor,
            llm_client=llm,
            interceptor=interceptor,
            context_manager=context_manager,
            log_analyzer=log_analyzer,
            max_iterations=max_iterations,
            on_step=on_step_callback
        )

        # === 步骤 3: 运行 Agent Loop ===
        await broadcaster.log_reasoning(f"开始诊断: {alert}")

        # AgentEngine.run() 是同步方法，在异步线程中运行
        # 使用 loop.run_in_executor 而不是 asyncio.to_thread，以便主事件循环可以继续处理其他任务
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, engine.run, alert)

        # === 步骤 4: 输出结果 ===
        if result.success:
            await broadcaster.log_success("诊断完成！")
            await broadcaster.log_success(f"RCA 报告: {result.final_analysis[:200]}...")
        else:
            await broadcaster.log_error("诊断失败或未完成")

        # 构建最终结果
        final_result = {
            "success": result.success,
            "total_steps": result.total_steps,
            "commands_executed": result.commands_executed,
            "commands_blocked": result.commands_blocked,
            "final_analysis": result.final_analysis,
            "compression_stats": result.compression_stats
        }

        # 保存到历史记录
        try:
            history_store.add_record({
                "alert": alert,
                "container": container,
                "success": result.success,
                "total_steps": result.total_steps,
                "commands_executed": result.commands_executed,
                "commands_blocked": result.commands_blocked,
                "final_analysis": result.final_analysis,
                "compression_stats": result.compression_stats,
            })
            await broadcaster.log_info("[History] 诊断记录已保存")
        except Exception as e:
            await broadcaster.log_error(f"[History] 保存失败: {str(e)}")

        # 发送完成信号
        await broadcaster.complete(final_result)

    except Exception as e:
        await broadcaster.log_error(f"Agent 运行异常: {str(e)}")
        # 保存失败记录
        try:
            history_store.add_record({
                "alert": alert,
                "container": container,
                "success": False,
                "error": str(e),
                "final_analysis": "",
            })
        except:
            pass
        await broadcaster.complete({
            "success": False,
            "error": str(e)
        })


@app.get("/api/status")
async def get_status():
    """获取 Agent 运行状态"""
    broadcaster = await get_broadcaster()
    return {
        "completed": broadcaster.is_completed,
        "result": broadcaster.get_result()
    }

# ==========================================
# 历史记录 API 路由
# ==========================================

@app.get("/api/history")
async def get_history(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    """
    获取诊断历史列表

    Args:
        limit: 返回数量（默认50，最大200）
        offset: 偏移量（用于分页）

    Returns:
        list: 历史记录列表
    """
    records = history_store.get_list(limit=limit, offset=offset)
    total = history_store.count()
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "records": records
    }


@app.get("/api/history/{task_id}")
async def get_history_detail(task_id: str):
    """
    获取单次诊断的完整 RCA 报告详情

    Args:
        task_id: 诊断任务ID

    Returns:
        dict: 诊断详情，包括完整 RCA 报告
    """
    record = history_store.get_detail(task_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"未找到任务: {task_id}")
    return record




# ==========================================
# 钉钉审批回调路由
# ==========================================

@app.get("/api/dingtalk/callback")
async def dingtalk_callback(task_id: str, action: str):
    """
    钉钉审批回调

    接收钉钉卡片的审批结果，更新审批状态。

    Args:
        task_id: 任务 ID
        action: 审批动作 ("approve" 或 "reject")

    Returns:
        dict: 响应结果
    """
    if action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="无效的审批动作")

    # 更新审批状态
    CommandInterceptor.set_approval_status(task_id, action)

    print(f"[DingTalk Callback] task_id={task_id}, action={action}")

    # 返回成功响应（钉钉会显示这个响应）
    return {
        "status": "success",
        "message": f"操作已记录，Agent 将继续执行",
        "task_id": task_id,
        "action": action
    }


@app.get("/api/approval/{task_id}")
async def get_approval_status(task_id: str):
    """
    查询审批状态

    Args:
        task_id: 任务 ID

    Returns:
        dict: 审批状态
    """
    status = CommandInterceptor.get_approval_status(task_id)
    return {
        "task_id": task_id,
        "status": status or "not_found"
    }


# ==========================================
# 启动入口
# ==========================================


# ==========================================
# Mount static files for frontend (production)
# ==========================================
_frontend_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=str(_frontend_dist / "assets")), name="frontend-assets")

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
