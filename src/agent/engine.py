"""
Agent Loop 引擎 (Core Agent Loop) - V2

支持真实 LLM 的 Tool Calling 机制。

工作流程:
    ┌─────────────────────────────────────────────┐
    │                  Agent Loop                  │
    │                                              │
    │  [告警输入] → [LLM思考] → [Tool Calls]       │
    │       ↑           ↓                          │
    │       │     [安全拦截器]                      │
    │       │           ↓                          │
    │       │     [执行工具]                        │
    │       │           ↓                          │
    │       └──── [结果反馈] ←─────────────┘       │
    │                                              │
    │  [完成] → 生成 RCA 报告                       │
    └─────────────────────────────────────────────┘
"""

import time
import sys
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional, Callable, Any, Dict
from enum import Enum, auto

# 添加 src 目录到 Python 路径
src_path = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(src_path))

# 添加项目根目录到 Python 路径（用于 executor）
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

# 导入模块
from executor import DockerExecutor
from utils.mock_llm import MockLLMClient, ResponseType
from utils.llm_client import LLMClient, SRE_SYSTEM_PROMPT, AVAILABLE_TOOLS
from security.interceptor import CommandInterceptor, InterceptResult, CommandRisk


class LoopState(Enum):
    """Agent Loop 状态"""
    IDLE = auto()           # 空闲
    REASONING = auto()      # LLM 思考中
    INTERCEPTING = auto()   # 命令拦截检查
    EXECUTING = auto()      # 执行工具
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
    llm_response: Optional[Dict[str, Any]] = None
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

    支持两种模式：
    1. Mock 模式：使用 MockLLMClient（测试用）
    2. LLM 模式：使用 LLMClient（真实 LLM）
    """

    def __init__(
        self,
        executor: Optional[DockerExecutor] = None,
        llm_client: Optional[Any] = None,
        interceptor: Optional[CommandInterceptor] = None,
        max_iterations: int = 10,
        on_step: Optional[Callable[[LoopStep], None]] = None
    ):
        """
        初始化 Agent 引擎

        Args:
            executor: 命令执行器（Docker）
            llm_client: LLM 客户端（MockLLMClient 或 LLMClient）
            interceptor: 命令拦截器
            max_iterations: 最大迭代次数
            on_step: 每步回调函数（用于打印状态）
        """
        self.executor = executor or DockerExecutor()
        self.llm = llm_client
        self.interceptor = interceptor or CommandInterceptor(strict_mode=True)
        self.max_iterations = max_iterations
        self.on_step = on_step or self._default_step_handler

        self.current_state = LoopState.IDLE
        self.steps: List[LoopStep] = []
        self.iteration_count = 0

        # 判断是否为真实 LLM 模式
        self.is_real_llm = isinstance(self.llm, LLMClient)

        print("[Agent Engine] 初始化完成")
        print(f"   - 最大迭代次数: {max_iterations}")
        print(f"   - LLM 类型: {type(self.llm).__name__}")
        print(f"   - 执行器类型: {type(self.executor).__name__}")
        print(f"   - 拦截器类型: {type(self.interceptor).__name__}")
        print(f"   - 模式: {'真实 LLM' if self.is_real_llm else 'Mock 测试'}")

    def run(self, initial_prompt: str) -> LoopResult:
        """
        运行 Agent Loop

        Args:
            initial_prompt: 初始提示（如告警信息）

        Returns:
            LoopResult: 执行结果
        """
        print("\n" + "="*70)
        print("[Agent Loop] 启动")
        print("="*70)
        print(f"\n[Input] 初始提示: {initial_prompt}\n")

        self._reset()
        current_context = initial_prompt

        while self.iteration_count < self.max_iterations:
            self.iteration_count += 1
            print(f"\n{'─'*70}")
            print(f"[Iteration] 第 {self.iteration_count}/{self.max_iterations} 轮")
            print(f"{'─'*70}")

            # 步骤 1: LLM 思考
            self._set_state(LoopState.REASONING)

            if self.is_real_llm:
                llm_response = self._call_real_llm(current_context)
            else:
                llm_response = self._call_mock_llm(current_context)

            step = LoopStep(
                step_number=self.iteration_count,
                state=LoopState.REASONING,
                llm_response=llm_response if not self.is_real_llm else None
            )

            # 通知回调
            self.on_step(step)

            # 步骤 2: 处理响应
            if self.is_real_llm:
                result = self._handle_real_llm_response(llm_response, step)
            else:
                result = self._handle_mock_llm_response(llm_response, step)

            # 检查是否完成
            if result == "COMPLETED":
                step.state = LoopState.COMPLETED
                self.steps.append(step)
                break
            elif result == "CONTINUE":
                self.steps.append(step)
                continue
            elif result == "ERROR":
                step.state = LoopState.ERROR
                self.steps.append(step)
                break

        # 生成最终结果
        return self._generate_result()

    def _reset(self):
        """重置状态"""
        self.steps.clear()
        self.iteration_count = 0
        self.current_state = LoopState.IDLE
        if hasattr(self.llm, 'reset'):
            self.llm.reset()

    def _set_state(self, state: LoopState):
        """设置当前状态"""
        self.current_state = state
        state_icons = {
            LoopState.REASONING: "[REASONING]",
            LoopState.INTERCEPTING: "[INTERCEPTING]",
            LoopState.EXECUTING: "[EXECUTING]",
            LoopState.COLLECTING: "[COLLECTING]",
            LoopState.COMPLETED: "[COMPLETED]",
            LoopState.BLOCKED: "[BLOCKED]",
            LoopState.ERROR: "[ERROR]",
        }
        icon = state_icons.get(state, "[STATE]")
        print(f"\n{icon} 状态切换: {state.name}")

    def _call_mock_llm(self, context: str):
        """调用 Mock LLM"""
        print("[LLM] 调用 Mock LLM...")
        prompt = f"上下文: {context}\n请分析并提供下一步诊断命令或结论。"
        return self.llm.chat(prompt)

    def _call_real_llm(self, context: str) -> Dict[str, Any]:
        """调用真实 LLM"""
        print("[LLM] 调用真实 LLM...")
        return self.llm.chat(
            user_message=context,
            system_prompt=SRE_SYSTEM_PROMPT,
            tools=AVAILABLE_TOOLS
        )

    def _handle_mock_llm_response(self, llm_response, step: LoopStep) -> str:
        """处理 Mock LLM 响应"""
        # 检查是否完成
        if llm_response.response_type == ResponseType.CONCLUSION:
            print("\n[Done] LLM 输出结论，诊断完成")
            return "COMPLETED"

        # 检查是否有命令
        if not llm_response.command:
            print("\n[Skip] LLM 未生成命令，跳过执行")
            return "CONTINUE"

        step.command = llm_response.command

        # 安全拦截
        self._set_state(LoopState.INTERCEPTING)
        intercept_result = self._intercept_command(llm_response.command)
        step.intercept_result = intercept_result

        if not intercept_result.allowed:
            print(f"\n[Blocked] 命令被拦截: {intercept_result.reason}")
            step.state = LoopState.BLOCKED
            return "CONTINUE"

        # 执行命令
        self._set_state(LoopState.EXECUTING)
        execute_result = self._execute_command(llm_response.command)
        step.execute_result = execute_result

        # 收集结果
        self._set_state(LoopState.COLLECTING)
        return "CONTINUE"

    def _handle_real_llm_response(self, llm_response: Dict[str, Any], step: LoopStep) -> str:
        """处理真实 LLM 响应（支持 Tool Calling）"""
        # 检查是否有错误
        if llm_response.get("finish_reason") == "error":
            print(f"\n[Error] LLM 调用失败: {llm_response['content']}")
            return "ERROR"

        # 显示 LLM 思考内容
        if llm_response.get("content"):
            print(f"\n[Thinking] LLM 思考: {llm_response['content']}")

        # 检查是否有工具调用
        tool_calls = llm_response.get("tool_calls", [])
        if not tool_calls:
            print("\n[Skip] LLM 未生成工具调用")
            return "CONTINUE"

        # 处理每个工具调用
        for tool_call in tool_calls:
            function_name = tool_call["function"]["name"]
            function_args = json.loads(tool_call["function"]["arguments"])

            print(f"\n[Tool Call] {function_name}")
            print(f"   参数: {json.dumps(function_args, ensure_ascii=False)}")

            # 处理 execute_command 工具
            if function_name == "execute_command":
                command = function_args.get("command", "")
                reason = function_args.get("reason", "")

                step.command = command
                print(f"   命令: {command}")
                print(f"   原因: {reason}")

                # 安全拦截
                self._set_state(LoopState.INTERCEPTING)
                intercept_result = self._intercept_command(command)
                step.intercept_result = intercept_result

                if not intercept_result.allowed:
                    print(f"\n[Blocked] 命令被拦截: {intercept_result.reason}")
                    step.state = LoopState.BLOCKED

                    # 将拦截结果反馈给 LLM
                    self.llm.add_tool_result(
                        tool_call_id=tool_call["id"],
                        function_name=function_name,
                        result=f"命令被拦截: {intercept_result.reason}"
                    )
                    continue

                # 执行命令
                self._set_state(LoopState.EXECUTING)
                execute_result = self._execute_command(command)
                step.execute_result = execute_result

                # 将执行结果反馈给 LLM
                result_str = json.dumps({
                    "exit_code": execute_result["exit_code"],
                    "stdout": execute_result["stdout"],
                    "stderr": execute_result["stderr"]
                }, ensure_ascii=False)

                self.llm.add_tool_result(
                    tool_call_id=tool_call["id"],
                    function_name=function_name,
                    result=result_str
                )

            # 处理 finish_diagnosis 工具
            elif function_name == "finish_diagnosis":
                rca_report = function_args.get("rca_report", "")
                severity = function_args.get("severity", "unknown")
                root_cause_category = function_args.get("root_cause_category", "unknown")

                print(f"\n[Finish] 诊断完成")
                print(f"   严重程度: {severity}")
                print(f"   根因类别: {root_cause_category}")
                print(f"   RCA 报告长度: {len(rca_report)} 字符")

                # 将结论保存到 step
                step.llm_response = {"content": rca_report}

                return "COMPLETED"

        return "CONTINUE"

    def _intercept_command(self, command: str) -> InterceptResult:
        """拦截检查命令"""
        print(f"[Interceptor] 检查命令安全性: {command}")
        return self.interceptor.intercept(command)

    def _execute_command(self, command: str) -> dict:
        """执行命令"""
        print(f"[Executor] 执行命令: {command}")
        return self.executor.execute(command)

    def _generate_result(self) -> LoopResult:
        """生成最终结果"""
        executed = sum(1 for s in self.steps if s.execute_result and s.execute_result.get("exit_code") == 0)
        blocked = sum(1 for s in self.steps if s.intercept_result and not s.intercept_result.allowed)

        # 获取最后一步的结论
        final_step = self.steps[-1] if self.steps else None
        final_analysis = ""
        if final_step and final_step.llm_response:
            if isinstance(final_step.llm_response, dict):
                final_analysis = final_step.llm_response.get("content", "")
            else:
                # Mock LLM 的 LLMResponse 对象
                final_analysis = getattr(final_step.llm_response, 'content', '')

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
        print("[Summary] Agent Loop 执行摘要")
        print("="*70)
        print(f"  总步骤数: {result.total_steps}")
        print(f"  成功执行: {result.commands_executed}")
        print(f"  拦截阻止: {result.commands_blocked}")
        print(f"  最终状态: {'[SUCCESS] 完成' if result.success else '[FAILED] 未完成'}")
        if result.final_analysis:
            print(f"\n[RCA Report] 最终分析:")
            print(result.final_analysis)
        print("="*70)

    @staticmethod
    def _default_step_handler(step: LoopStep):
        """默认步骤处理（打印状态）"""
        if step.llm_response and not isinstance(step.llm_response, dict):
            # Mock LLM 响应
            print(f"\n[LLM Response] 思考: {step.llm_response.thinking}")

        if step.command:
            print(f"\n[Command] 生成命令: {step.command}")

        if step.intercept_result:
            status = "[PASS]" if step.intercept_result.allowed else "[BLOCKED]"
            print(f"\n{status} | 风险: {step.intercept_result.risk_level.value}")
            print(f"   原因: {step.intercept_result.reason}")

        if step.execute_result:
            exit_code = step.execute_result.get("exit_code", -1)
            print(f"\n[Execute Result] (exit_code={exit_code}):")
            if step.execute_result.get("stdout"):
                print(f"   stdout: {step.execute_result['stdout'][:100]}...")
            if step.execute_result.get("stderr"):
                print(f"   stderr: {step.execute_result['stderr'][:100]}...")


# ==========================================
# 主入口
# ==========================================
if __name__ == "__main__":
    print("="*70)
    print("[Auto-SRE Harness] Agent Loop Demo")
    print("="*70)

    # 初始化组件
    print("\n[Init] Components...")

    # 创建 Docker 执行器
    try:
        executor = DockerExecutor(container_name="auto-sre-sandbox")
    except Exception as e:
        print(f"[Error] Docker 连接失败: {e}")
        print("[Tip] 请确保已运行: docker-compose up -d")
        sys.exit(1)

    # 选择模式：Mock 或真实 LLM
    use_real_llm = False

    if use_real_llm:
        # 真实 LLM 模式
        try:
            llm = LLMClient()
        except ValueError as e:
            print(f"[Error] LLM 初始化失败: {e}")
            print("[Tip] 请设置环境变量: LLM_API_KEY, LLM_MODEL, LLM_BASE_URL")
            sys.exit(1)
    else:
        # Mock 模式
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

    # 运行演示
    print("\n\n" + "="*70)
    print("[Demo] 场景: CPU 飙高诊断")
    print("="*70)

    result = engine.run("[Alert] 服务器 CPU 使用率 95%，持续 5 分钟")

    # 最终总结
    print("\n\n" + "="*70)
    print("[Done] 演示完成！")
    print("="*70)
    print(f"\n结果: {'[SUCCESS] 成功' if result.success else '[FAILED] 失败'}")
    print(f"执行命令: {result.commands_executed}")
    print(f"拦截命令: {result.commands_blocked}")
    print("="*70)
