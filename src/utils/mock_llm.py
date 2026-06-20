"""
Mock LLM 客户端 (模拟 LLM 响应)

用于测试 Agent Loop，预设了几轮回复，包含：
- 安全的诊断命令
- 危险的修复命令（用于测试拦截器）
- 完整的对话流程
"""

import time
from dataclasses import dataclass
from typing import List, Optional
from enum import Enum


class ResponseType(Enum):
    """响应类型"""
    SAFE_COMMAND = "safe_command"      # 安全命令
    DANGEROUS_COMMAND = "dangerous_command"  # 危险命令（测试拦截器）
    ANALYSIS = "analysis"              # 分析报告
    CONCLUSION = "conclusion"          # 结论


@dataclass
class LLMResponse:
    """LLM 响应结构"""
    content: str                    # 响应内容
    command: Optional[str] = None   # 提取的命令
    response_type: ResponseType = ResponseType.ANALYSIS
    thinking: str = ""              # 思考过程（模拟思维链）


class MockLLMClient:
    """
    Mock LLM 客户端

    模拟真实 LLM 的响应，按顺序返回预设的回复。
    用于测试 Agent Loop 的完整流程，无需实际调用昂贵的 LLM API。
    """

    def __init__(self, scenario: str = "cpu_high"):
        """
        初始化 Mock LLM

        Args:
            scenario: 测试场景
                - "cpu_high": CPU 飙高诊断（包含安全命令）
                - "nginx_error": Nginx 错误（包含危险命令测试）
                - "full_loop": 完整诊断流程
        """
        self.scenario = scenario
        self.conversation_history: List[dict] = []
        self.response_index = 0

        # 根据场景加载预设回复
        self._responses = self._load_responses(scenario)

        print(f"🤖 Mock LLM 初始化完成")
        print(f"   - 测试场景: {scenario}")
        print(f"   - 预设回复数: {len(self._responses)}")

    def _load_responses(self, scenario: str) -> List[LLMResponse]:
        """加载预设回复"""

        if scenario == "cpu_high":
            # 场景 1: CPU 飙高诊断（安全命令序列）
            return [
                LLMResponse(
                    content="开始诊断 CPU 飙高问题...",
                    thinking="用户报告 CPU 飙升，我需要先查看进程状态",
                    response_type=ResponseType.ANALYSIS
                ),
                LLMResponse(
                    content="查看占用 CPU 最多的进程",
                    command="ps aux --sort=-%cpu | head -20",
                    thinking="使用 ps 命令查看 CPU 占用",
                    response_type=ResponseType.SAFE_COMMAND
                ),
                LLMResponse(
                    content="查看系统负载",
                    command="uptime",
                    thinking="需要了解系统整体负载情况",
                    response_type=ResponseType.SAFE_COMMAND
                ),
                LLMResponse(
                    content="检查是否有异常进程",
                    command="top -bn1 | head -20",
                    thinking="使用 top 查看实时进程状态",
                    response_type=ResponseType.SAFE_COMMAND
                ),
                LLMResponse(
                    content="诊断完成，发现是 nginx worker 进程过多导致",
                    thinking="根据收集的信息分析根因",
                    response_type=ResponseType.CONCLUSION
                ),
            ]

        elif scenario == "nginx_error":
            # 场景 2: Nginx 错误（包含危险命令，测试拦截器）
            return [
                LLMResponse(
                    content="开始诊断 Nginx 错误...",
                    thinking="用户报告 Nginx 报错，需要查看错误日志",
                    response_type=ResponseType.ANALYSIS
                ),
                LLMResponse(
                    content="查看 Nginx 错误日志",
                    command="tail -50 /var/log/nginx/error.log",
                    thinking="查看最近的错误日志",
                    response_type=ResponseType.SAFE_COMMAND
                ),
                LLMResponse(
                    content="检查 Nginx 进程状态",
                    command="ps aux | grep nginx",
                    thinking="确认 Nginx 进程是否正常运行",
                    response_type=ResponseType.SAFE_COMMAND
                ),
                LLMResponse(
                    content="尝试重启 Nginx 服务（危险命令测试）",
                    command="systemctl restart nginx",
                    thinking="如果配置有问题，尝试重启服务",
                    response_type=ResponseType.DANGEROUS_COMMAND
                ),
                LLMResponse(
                    content="如果重启失败，则删除日志文件（危险命令测试）",
                    command="rm -rf /var/log/nginx/*",
                    thinking="清理日志以便重新启动",
                    response_type=ResponseType.DANGEROUS_COMMAND
                ),
                LLMResponse(
                    content="诊断完成，建议手动检查配置",
                    thinking="由于涉及危险操作，建议人工介入",
                    response_type=ResponseType.CONCLUSION
                ),
            ]

        elif scenario == "full_loop":
            # 场景 3: 完整诊断流程
            return [
                LLMResponse(
                    content="🚨 检测到异常：CPU 使用率 95%，开始自动诊断",
                    thinking="收到告警，启动诊断流程",
                    response_type=ResponseType.ANALYSIS
                ),
                LLMResponse(
                    content="步骤 1: 查看系统负载",
                    command="uptime && free -h",
                    thinking="了解系统整体状态",
                    response_type=ResponseType.SAFE_COMMAND
                ),
                LLMResponse(
                    content="步骤 2: 查看 CPU 占用最高的进程",
                    command="ps aux --sort=-%cpu | head -15",
                    thinking="定位高 CPU 进程",
                    response_type=ResponseType.SAFE_COMMAND
                ),
                LLMResponse(
                    content="步骤 3: 查看进程详细信息",
                    command="top -bn1 | head -30",
                    thinking="实时查看进程状态",
                    response_type=ResponseType.SAFE_COMMAND
                ),
                LLMResponse(
                    content="步骤 4: 检查系统日志",
                    command="journalctl --no-pager -n 50",
                    thinking="查看是否有系统错误",
                    response_type=ResponseType.SAFE_COMMAND
                ),
                LLMResponse(
                    content="分析结果：发现 cron 任务过多导致 CPU 飙高。可尝试停止异常 cron 进程：pkill -f suspicious_cron",
                    command="pkill -f suspicious_cron",
                    thinking="尝试修复问题，但这个命令可能有危险",
                    response_type=ResponseType.DANGEROUS_COMMAND
                ),
                LLMResponse(
                    content="建议：需要人工介入检查 /etc/crontab 和 /var/spool/cron/",
                    thinking="生成 RCA 报告建议",
                    response_type=ResponseType.CONCLUSION
                ),
            ]

        else:
            return []

    def chat(self, prompt: str) -> LLMResponse:
        """
        模拟 LLM 对话

        Args:
            prompt: 用户提示

        Returns:
            LLMResponse: LLM 响应
        """
        # 记录用户输入
        self.conversation_history.append({
            "role": "user",
            "content": prompt
        })

        # 模拟网络延迟
        time.sleep(0.5)

        # 返回预设回复（循环使用）
        if self.response_index >= len(self._responses):
            response = LLMResponse(
                content="[Mock LLM] 已到达预设回复上限，返回默认分析",
                thinking="无更多预设内容",
                response_type=ResponseType.CONCLUSION
            )
        else:
            response = self._responses[self.response_index]
            self.response_index += 1

        # 记录 LLM 响应
        self.conversation_history.append({
            "role": "assistant",
            "content": response.content,
            "command": response.command
        })

        return response

    def reset(self):
        """重置对话状态"""
        self.conversation_history.clear()
        self.response_index = 0
        print("🔄 Mock LLM 对话状态已重置")

    def get_conversation_history(self) -> List[dict]:
        """获取对话历史"""
        return self.conversation_history

    def print_conversation_history(self):
        """打印对话历史"""
        print("\n" + "="*60)
        print("📜 对话历史")
        print("="*60)
        for i, msg in enumerate(self.conversation_history, 1):
            role = msg["role"].upper()
            content = msg.get("content", "")
            print(f"\n[{i}] {role}:")
            print(f"    {content}")
            if msg.get("command"):
                print(f"    📌 提取命令: {msg['command']}")
        print("\n" + "="*60)


# ==========================================
# 测试代码
# ==========================================
if __name__ == "__main__":
    print("🧪 测试 Mock LLM 客户端\n")

    # 测试场景 1: CPU 飙高
    print("="*60)
    print("场景 1: CPU 飙高诊断")
    print("="*60)

    llm = MockLLMClient(scenario="cpu_high")

    # 模拟对话
    prompts = [
        "服务器 CPU 使用率 95%，请诊断",
        "继续诊断",
        "下一步",
        "得出结论",
    ]

    for prompt in prompts:
        print(f"\n👤 用户: {prompt}")
        response = llm.chat(prompt)
        print(f"🤖 LLM: {response.content}")
        if response.command:
            print(f"📌 命令: {response.command}")
        print(f"   类型: {response.response_type.value}")

    llm.print_conversation_history()

    # 测试场景 2: Nginx 错误
    print("\n\n" + "="*60)
    print("场景 2: Nginx 错误（包含危险命令）")
    print("="*60)

    llm = MockLLMClient(scenario="nginx_error")
    llm.chat("Nginx 报错 502")
    llm.chat("继续")
    llm.chat("尝试修复")
    llm.chat("清理日志")

    llm.print_conversation_history()
