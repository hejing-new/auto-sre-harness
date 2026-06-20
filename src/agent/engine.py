"""
Agent Loop 引擎 (Core Agent Loop)

这是 Auto-SRE 的核心组件，负责：
1. 接收告警/任务
2. 调用 LLM 生成诊断/修复命令
3. 使用安全拦截器检查命令
4. 执行安全命令
5. 收集结果并反馈给 LLM
6. 循环直到完成诊断或达到最大轮次

工作流程:
    ┌─────────────────────────────────────────────┐
    │                  Agent Loop                  │
    │                                              │
    │  [告警输入] → [LLM思考] → [生成命令]          │
    │       ↑           ↓                          │
    │       │     [安全拦截器]                      │
    │       │           ↓                          │
    │       │     [执行命令]                        │
    │       │           ↓                          │
    │       └──── [结果反馈] ←─────────────┘       │
    │                                              │
    │  [完成] → 生成 RCA 报告                       │
    └─────────────────────────────────────────────┘
"""

import time
import sys
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional, Callable
from enum import Enum, auto

# 添加 src 目录到 Python 路径
src_path = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(src_path))

# 添加项目根目录到 Python 路径（用于 executor）
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

# 导入我们已有的模块
from executor import DockerExecutor
from utils.mock_llm import MockLLMClient, LLMResponse, ResponseType
from security.interceptor import CommandInterceptor, InterceptResult, CommandRisk


class LoopState(Enum):
    """Agent Loop 状态"""
    IDLE = auto()           # 空闲
    REASONING = auto()      # LLM 思考中
    INTERCEPTING = auto()   # 命令拦截检查
    EXECUTING = auto()      # 执行命令
    COLLECTING = auto()     # 收集结果
    COMPLETED = auto()      # 完成
    BLOCKED = auto()        # 被拦截器阻止
    ERROR = auto()          # 错误


@dataclass
class LoopStep:
    """单次循环的步骤记录"""
    step_number: int
    state: LoopState
    command: Optional[str] = None
    intercept_result: Optional[InterceptResult] = None
    execute_result: Optional[dict] = None
    llm_response: Optional[LLMResponse] = None
    timestamp: float = field(default_factory=time.time)


@dataclass
class LoopResult:
    """循环执行结果"""
    success: bool
    total_steps: int
    commands_executed: int
    commands_blocked: int
    steps: List[LoopStep]
    final_analysis: str = ""
    error_message: str = ""


class AgentEngine:
    """
    Agent Loop 引擎

    核心循环逻辑，协调 LLM、拦截器和执行器。
    """

    def __init__(
        self,
        executor: Optional[DockerExecutor] = None,
        llm_client: Optional[MockLLMClient] = None,
        interceptor: Optional[CommandInterceptor] = None,
        max_iterations: int = 10,
        on_step: Optional[Callable[[LoopStep], None]] = None
    ):
        """
        初始化 Agent 引擎

        Args:
            executor: 命令执行器（Docker）
            llm_client: LLM 客户端
            interceptor: 命令拦截器
            max_iterations: 最大迭代次数
            on_step: 每步回调函数（用于打印状态）
        """
        self.executor = executor or DockerExecutor()
        self.llm = llm_client or MockLLMClient(scenario="cpu_high")
        self.interceptor = interceptor or CommandInterceptor(strict_mode=True)
        self.max_iterations = max_iterations
        self.on_step = on_step or self._default_step_handler

        self.current_state = LoopState.IDLE
        self.steps: List[LoopStep] = []
        self.iteration_count = 0

        print("🚀 Agent Loop 引擎初始化完成")
        print(f"   - 最大迭代次数: {max_iterations}")
        print(f"   - LLM 类型: {type(self.llm).__name__}")
        print(f"   - 执行器类型: {type(self.executor).__name__}")
        print(f"   - 拦截器类型: {type(self.interceptor).__name__}")

    def run(self, initial_prompt: str) -> LoopResult:
        """
        运行 Agent Loop

        Args:
            initial_prompt: 初始提示（如告警信息）

        Returns:
            LoopResult: 执行结果
        """
        print("\n" + "="*70)
        print("🎯 启动 Agent Loop")
        print("="*70)
        print(f"\n📝 初始提示: {initial_prompt}\n")

        self._reset()
        current_context = initial_prompt

        while self.iteration_count < self.max_iterations:
            self.iteration_count += 1
            print(f"\n{'─'*70}")
            print(f"🔄 第 {self.iteration_count}/{self.max_iterations} 轮迭代")
            print(f"{'─'*70}")

            # 步骤 1: LLM 思考
            self._set_state(LoopState.REASONING)
            llm_response = self._call_llm(current_context)

            step = LoopStep(
                step_number=self.iteration_count,
                state=LoopState.REASONING,
                llm_response=llm_response
            )

            # 通知回调
            self.on_step(step)

            # 检查是否完成
            if llm_response.response_type == ResponseType.CONCLUSION:
                print("\n✅ LLM 输出结论，诊断完成")
                step.state = LoopState.COMPLETED
                self.steps.append(step)
                break

            # 步骤 2: 检查是否有命令
            if not llm_response.command:
                print("\n⚠️  LLM 未生成命令，跳过执行")
                self.steps.append(step)
                continue

            step.command = llm_response.command

            # 步骤 3: 安全拦截
            self._set_state(LoopState.INTERCEPTING)
            intercept_result = self._intercept_command(llm_response.command)
            step.intercept_result = intercept_result

            if not intercept_result.allowed:
                print(f"\n🚫 命令被拦截: {intercept_result.reason}")
                step.state = LoopState.BLOCKED

                # 反馈给 LLM
                current_context = f"命令 '{llm_response.command}' 被拦截: {intercept_result.reason}"
                self.steps.append(step)

                # 通知回调
                self.on_step(step)
                continue

            # 步骤 4: 执行命令
            self._set_state(LoopState.EXECUTING)
            execute_result = self._execute_command(llm_response.command)
            step.execute_result = execute_result

            # 步骤 5: 收集结果
            self._set_state(LoopState.COLLECTING)

            # 构建反馈上下文
            if execute_result["exit_code"] == 0:
                output_preview = execute_result["stdout"][:200]  # 截取前200字符
                current_context = f"命令 '{llm_response.command}' 执行成功:\n{output_preview}"
            else:
                current_context = f"命令 '{llm_response.command}' 执行失败 (exit_code={execute_result['exit_code']}): {execute_result['stderr']}"

            self.steps.append(step)

            # 通知回调
            self.on_step(step)

            # 短暂延迟避免过快循环
            time.sleep(0.3)

        # 生成最终结果
        return self._generate_result()

    def _reset(self):
        """重置状态"""
        self.steps.clear()
        self.iteration_count = 0
        self.current_state = LoopState.IDLE
        self.llm.reset()

    def _set_state(self, state: LoopState):
        """设置当前状态"""
        self.current_state = state
        state_icons = {
            LoopState.REASONING: "🧠",
            LoopState.INTERCEPTING: "🛡️",
            LoopState.EXECUTING: "⚡",
            LoopState.COLLECTING: "📊",
            LoopState.COMPLETED: "✅",
            LoopState.BLOCKED: "🚫",
            LoopState.ERROR: "❌",
        }
        icon = state_icons.get(state, "➡️")
        print(f"\n{icon} 状态切换: {state.name}")

    def _call_llm(self, context: str) -> LLMResponse:
        """调用 LLM"""
        print(f"🤖 调用 LLM...")
        prompt = f"上下文: {context}\n请分析并提供下一步诊断命令或结论。"
        return self.llm.chat(prompt)

    def _intercept_command(self, command: str) -> InterceptResult:
        """拦截检查命令"""
        print(f"🛡️  检查命令安全性: {command}")
        return self.interceptor.intercept(command)

    def _execute_command(self, command: str) -> dict:
        """执行命令"""
        print(f"⚡ 执行命令: {command}")
        return self.executor.execute(command)

    def _generate_result(self) -> LoopResult:
        """生成最终结果"""
        executed = sum(1 for s in self.steps if s.execute_result and s.execute_result.get("exit_code") == 0)
        blocked = sum(1 for s in self.steps if s.intercept_result and not s.intercept_result.allowed)

        # 获取最后一步的结论
        final_step = self.steps[-1] if self.steps else None
        final_analysis = final_step.llm_response.content if final_step and final_step.llm_response else ""

        result = LoopResult(
            success=final_step and final_step.state == LoopState.COMPLETED,
            total_steps=len(self.steps),
            commands_executed=executed,
            commands_blocked=blocked,
            steps=self.steps,
            final_analysis=final_analysis
        )

        self._print_summary(result)
        return result

    def _print_summary(self, result: LoopResult):
        """打印执行摘要"""
        print("\n" + "="*70)
        print("📊 Agent Loop 执行摘要")
        print("="*70)
        print(f"  总步骤数: {result.total_steps}")
        print(f"  成功执行: {result.commands_executed}")
        print(f"  拦截阻止: {result.commands_blocked}")
        print(f"  最终状态: {'✅ 完成' if result.success else '❌ 未完成'}")
        print(f"\n📝 最终分析: {result.final_analysis}")
        print("="*70)

    @staticmethod
    def _default_step_handler(step: LoopStep):
        """默认步骤处理（打印状态）"""
        if step.llm_response:
            print(f"\n💭 LLM 思考: {step.llm_response.thinking}")

        if step.command:
            print(f"\n📌 生成命令: {step.command}")

        if step.intercept_result:
            status = "✅ 放行" if step.intercept_result.allowed else "🚫 拦截"
            print(f"\n{status} | 风险: {step.intercept_result.risk_level.value}")
            print(f"   原因: {step.intercept_result.reason}")

        if step.execute_result:
            exit_code = step.execute_result.get("exit_code", -1)
            print(f"\n📤 执行结果 (exit_code={exit_code}):")
            if step.execute_result.get("stdout"):
                print(f"   stdout: {step.execute_result['stdout'][:100]}...")
            if step.execute_result.get("stderr"):
                print(f"   stderr: {step.execute_result['stderr'][:100]}...")


# ==========================================
# 主入口
# ==========================================
if __name__ == "__main__":
    print("="*70)
    print("[Auto-SRE Harness] MVP Agent Loop Demo")
    print("="*70)

    # 初始化组件
    print("\n[Init] Components...")

    # 创建 Docker 执行器
    try:
        executor = DockerExecutor(container_name="auto-sre-sandbox")
    except Exception as e:
        print(f"❌ Docker 连接失败: {e}")
        print("💡 请确保已运行: docker-compose up -d")
        sys.exit(1)

    # 创建 Mock LLM
    llm = MockLLMClient(scenario="cpu_high")

    # 创建拦截器
    interceptor = CommandInterceptor(strict_mode=True)

    # 创建 Agent 引擎
    engine = AgentEngine(
        executor=executor,
        llm_client=llm,
        interceptor=interceptor,
        max_iterations=8
    )

    # 运行场景 1: CPU 飙高诊断
    print("\n\n" + "="*70)
    print("🎬 场景 1: CPU 飙高诊断（安全命令）")
    print("="*70)

    result1 = engine.run("🚨 告警: 服务器 CPU 使用率 95%，持续 5 分钟")

    # 运行场景 2: Nginx 错误（包含危险命令）
    print("\n\n" + "="*70)
    print("🎬 场景 2: Nginx 错误（包含危险命令测试）")
    print("="*70)

    # 重置 LLM 场景
    engine.llm = MockLLMClient(scenario="nginx_error")
    result2 = engine.run("🚨 告警: Nginx 返回 502 错误，错误日志激增")

    # 最终总结
    print("\n\n" + "="*70)
    print("🏁 所有演示完成！")
    print("="*70)
    print(f"\n场景 1 (CPU 飙高): {'✅ 完成' if result1.success else '❌ 未完成'}")
    print(f"  - 执行命令: {result1.commands_executed}")
    print(f"  - 拦截命令: {result1.commands_blocked}")
    print(f"\n场景 2 (Nginx 错误): {'✅ 完成' if result2.success else '❌ 未完成'}")
    print(f"  - 执行命令: {result2.commands_executed}")
    print(f"  - 拦截命令: {result2.commands_blocked}")
    print("\n✅ MVP 核心流程验证成功！")
    print("="*70)
