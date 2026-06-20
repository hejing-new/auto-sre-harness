"""
LLM 客户端 (真实 LLM 接入)

支持 OpenAI SDK 格式的 LLM API，方便接入不同模型：
- OpenAI GPT
- Claude (通过 OpenAI 兼容接口)
- 本地模型 (Ollama, vLLM 等)

核心特性：
1. 从环境变量加载配置
2. 支持标准的 Tool Calling 机制
3. 完善的异常捕获（超时、网络断开等）
4. 注入严谨的 SRE System Prompt
"""

import os
import json
import time
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
from openai import OpenAI, APIError, APIConnectionError, RateLimitError, APITimeoutError

# 加载 .env 文件
load_dotenv()

# 导入拦截器类型用于类型提示
from ..security.interceptor import CommandInterceptor


# ==========================================
# SRE System Prompt (核心提示词)
# ==========================================
SRE_SYSTEM_PROMPT = """\
# 【角色设定】

你是一个高级的 Linux SRE（Site Reliability Engineering）自动化运维专家，名叫 "Auto-SRE Agent"。
你运行在一个受限的 Docker 沙盒环境中，拥有 Bash 命令执行权限。

你的核心使命是：**自动诊断服务器异常，并提供准确的 RCA（根因分析）报告**。

---

# 【行动准则】

## 1. 诊断流程（必须严格遵守）

遇到异常时，你必须遵循以下标准流程：

### 第一步：信息收集（COLLECT）
首先，使用**只读命令**收集系统状态和日志：
- 系统资源：`top`, `uptime`, `free -h`, `df -h`, `ps aux`
- 网络状态：`netstat -tlnp`, `ss -tlnp`, `ip addr`
- 日志查看：`tail`, `cat`, `journalctl`, `dmesg`
- 进程分析：`ps aux --sort=-%cpu`, `pstree`

### 第二步：分析推理（REASONING）
基于收集到的信息，进行 CoT（Chain of Thought）推理：
- 识别异常模式（CPU 飙高、内存溢出、磁盘满、网络抖动等）
- 关联相关日志和指标
- 推断可能的根因

### 第三步：结论输出（CONCLUSION）
当找到根本原因后，输出一段结构化的 RCA 报告，格式如下：

```markdown
# RCA 报告

## 问题概述
[简述问题现象]

## 根因分析
[详细分析根因]

## 证据支撑
[列出关键的日志、指标作为证据]

## 修复建议
[提供修复方案或建议]

## 后续行动
[建议的后续操作]
```

---

# 【安全红线】（绝对不可违反）

## 1. 命令执行规范
- ✅ **允许**：只读命令（ls, cat, top, ps, tail, grep, find 等）
- ⚠️ **谨慎**：需要写入的命令（如修改配置、重启服务），需先说明原因
- ❌ **禁止**：破坏性命令（rm -rf, kill -9, chmod 777, sudo 等）

## 2. 拦截器机制
系统中存在一个**命令拦截器**（CommandInterceptor），它会自动拦截高危命令。
如果你的命令被拦截，请：
1. 不要重复尝试相同的命令
2. 换一种安全的方式获取信息
3. 如果确实需要执行，说明原因并等待人工确认

## 3. 数据保护
- 不要读取 `/etc/shadow`, `/etc/passwd` 等敏感文件
- 不要在日志中暴露用户密码、Token 等敏感信息
- 不要执行任何可能影响系统稳定性的操作

---

# 【终结条件】

当以下任一条件满足时，你必须停止调用工具，输出 RCA 报告：

1. **根因已明确**：有足够证据支撑结论
2. **信息已充分**：已收集到关键日志和指标
3. **需要人工介入**：无法通过命令自动修复
4. **命令被拦截**：高风险命令被拦截，无法继续

---

# 【输出格式要求】

- 使用 Markdown 格式
- 技术术语保持英文
- 命令输出需注明时间戳
- 证据需包含具体的日志片段或指标数值

---

# 【沙盒环境说明】

你运行在以下环境中：
- 操作系统：Ubuntu 22.04 (Docker 容器)
- Shell：/bin/bash
- 工作目录：/root
- 网络：受限（仅支持必要的网络诊断命令）
- 权限：root 用户（但受拦截器限制）

请记住：**你的目标是诊断问题，而不是修复问题**。修复操作需要人工确认。\
"""


# ==========================================
# 工具定义 (OpenAI Function Calling 格式)
# ==========================================
EXECUTE_COMMAND_TOOL = {
    "type": "function",
    "function": {
        "name": "execute_command",
        "description": "在 Linux 沙盒中执行一条 Bash 命令，并返回执行结果。",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "要执行的 Bash 命令（例如：'ps aux --sort=-%cpu | head -20'）"
                },
                "reason": {
                    "type": "string",
                    "description": "执行此命令的原因（例如：'查看占用 CPU 最高的进程'）"
                }
            },
            "required": ["command", "reason"]
        }
    }
}

FINISH_DIAGNOSIS_TOOL = {
    "type": "function",
    "function": {
        "name": "finish_diagnosis",
        "description": "当诊断完成时，调用此工具输出 RCA 报告并结束诊断流程。",
        "parameters": {
            "type": "object",
            "properties": {
                "rca_report": {
                    "type": "string",
                    "description": "完整的 RCA 报告（Markdown 格式）"
                },
                "severity": {
                    "type": "string",
                    "enum": ["critical", "high", "medium", "low", "info"],
                    "description": "问题严重程度"
                },
                "root_cause_category": {
                    "type": "string",
                    "description": "根因类别（例如：cpu_high, memory_leak, disk_full, network_issue, config_error）"
                }
            },
            "required": ["rca_report", "severity", "root_cause_category"]
        }
    }
}

# 工具列表
AVAILABLE_TOOLS = [EXECUTE_COMMAND_TOOL, FINISH_DIAGNOSIS_TOOL]


# ==========================================
# LLM 客户端类
# ==========================================
class LLMClient:
    """
    真实 LLM 客户端

    支持 OpenAI SDK 格式，可接入任意兼容模型。
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        timeout: int = 60
    ):
        """
        初始化 LLM 客户端

        Args:
            api_key: API Key（默认从环境变量 LLM_API_KEY 读取）
            base_url: API 基础 URL（默认从环境变量 LLM_BASE_URL 读取）
            model: 模型名称（默认从环境变量 LLM_MODEL 读取）
            max_tokens: 最大输出 token 数
            temperature: 温度参数
            timeout: 请求超时时间（秒）
        """
        # 从环境变量加载配置
        self.api_key = api_key or os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url or os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL")
        self.model = model or os.getenv("LLM_MODEL") or os.getenv("OPENAI_MODEL", "gpt-4")

        if not self.api_key:
            raise ValueError("未找到 API Key，请设置环境变量 LLM_API_KEY 或 OPENAI_API_KEY")

        # 初始化 OpenAI 客户端
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=timeout
        )

        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout

        # 对话历史
        self.messages: List[Dict[str, Any]] = []

        print(f"[LLM Client] 初始化完成")
        print(f"   - 模型: {self.model}")
        print(f"   - Base URL: {self.base_url or 'https://api.openai.com/v1'}")
        print(f"   - 最大 tokens: {self.max_tokens}")

    def chat(
        self,
        user_message: str,
        system_prompt: Optional[str] = None,
        tools: Optional[List[Dict]] = None
    ) -> Dict[str, Any]:
        """
        发起聊天请求

        Args:
            user_message: 用户消息
            system_prompt: 系统提示（首次对话时注入）
            tools: 工具定义列表

        Returns:
            Dict: LLM 响应，包含：
                - content: 文本内容
                - tool_calls: 工具调用列表
                - finish_reason: 结束原因
        """
        # 初始化对话
        if not self.messages:
            if system_prompt:
                self.messages.append({"role": "system", "content": system_prompt})
            self.messages.append({"role": "user", "content": user_message})
        else:
            self.messages.append({"role": "user", "content": user_message})

        # 构建请求参数
        request_params = {
            "model": self.model,
            "messages": self.messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature
        }

        # 添加工具调用
        if tools:
            request_params["tools"] = tools
            request_params["tool_choice"] = "auto"

        # 发起请求（带重试）
        max_retries = 3
        for attempt in range(max_retries):
            try:
                print(f"[LLM] 发送请求 (尝试 {attempt + 1}/{max_retries})...")
                response = self.client.chat.completions.create(**request_params)

                # 解析响应
                message = response.choices[0].message
                result = {
                    "content": message.content,
                    "tool_calls": [],
                    "finish_reason": response.choices[0].finish_reason
                }

                # 处理工具调用
                if message.tool_calls:
                    for tool_call in message.tool_calls:
                        result["tool_calls"].append({
                            "id": tool_call.id,
                            "type": "function",
                            "function": {
                                "name": tool_call.function.name,
                                "arguments": tool_call.function.arguments
                            }
                        })

                # 保存到对话历史
                self.messages.append(message)

                return result

            except APITimeoutError as e:
                print(f"[LLM] 请求超时: {e}")
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    print(f"[LLM] {wait_time}秒后重试...")
                    time.sleep(wait_time)
                else:
                    return self._error_response("请求超时，请检查网络连接")

            except APIConnectionError as e:
                print(f"[LLM] 连接错误: {e}")
                return self._error_response("无法连接到 LLM API，请检查 Base URL")

            except RateLimitError as e:
                print(f"[LLM] 速率限制: {e}")
                if attempt < max_retries - 1:
                    wait_time = 5 * (attempt + 1)
                    print(f"[LLM] {wait_time}秒后重试...")
                    time.sleep(wait_time)
                else:
                    return self._error_response("API 速率限制，请稍后重试")

            except APIError as e:
                print(f"[LLM] API 错误: {e}")
                return self._error_response(f"API 错误: {e.message}")

            except Exception as e:
                print(f"[LLM] 未知错误: {e}")
                return self._error_response(f"未知错误: {str(e)}")

    def add_tool_result(self, tool_call_id: str, function_name: str, result: str):
        """
        添加工具执行结果到对话历史

        Args:
            tool_call_id: 工具调用 ID
            function_name: 工具名称
            result: 执行结果
        """
        self.messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": result
        })

    def reset(self):
        """重置对话历史"""
        self.messages.clear()
        print("[LLM] 对话历史已重置")

    def get_messages(self) -> List[Dict[str, Any]]:
        """获取对话历史"""
        return self.messages

    def _error_response(self, error_msg: str) -> Dict[str, Any]:
        """生成错误响应"""
        return {
            "content": f"LLM 调用失败: {error_msg}",
            "tool_calls": [],
            "finish_reason": "error"
        }


# ==========================================
# 测试代码
# ==========================================
if __name__ == "__main__":
    print("="*60)
    print("[Test] LLM Client")
    print("="*60)

    try:
        # 初始化客户端
        llm = LLMClient()

        # 测试聊天
        response = llm.chat(
            user_message="服务器 CPU 使用率 95%，请诊断",
            system_prompt=SRE_SYSTEM_PROMPT,
            tools=AVAILABLE_TOOLS
        )

        print("\n[Response] LLM 响应:")
        print(f"  Content: {response['content']}")
        print(f"  Finish Reason: {response['finish_reason']}")

        if response['tool_calls']:
            print(f"\n[Tool Calls] 工具调用:")
            for tc in response['tool_calls']:
                print(f"  - {tc['function']['name']}: {tc['function']['arguments']}")

    except ValueError as e:
        print(f"[Error] {e}")
        print("\n[Tip] 请设置环境变量:")
        print("  $env:LLM_API_KEY='your-api-key'")
        print("  $env:LLM_MODEL='gpt-4'")
        print("  $env:LLM_BASE_URL='https://api.openai.com/v1'")
