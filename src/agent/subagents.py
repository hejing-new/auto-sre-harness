"""
子智能体模块 (Sub-Agents)

包含专门处理特定任务的子智能体：
- LogAnalyzerAgent: 专门处理长日志文件的分析

设计原则：
- 使用更小、更快的模型
- 专注于单一职责
- 返回高度精炼的摘要
"""

import json
import sys
from pathlib import Path
from typing import Optional, Dict, Any

# 添加项目路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from executor import DockerExecutor
from utils.llm_client import LLMClient


# ==========================================
# LogAnalyzerAgent 专用 System Prompt
# ==========================================
LOG_ANALYZER_SYSTEM_PROMPT = """\
# 【角色设定】

你是一个专业的日志分析助手，名叫 "LogAnalyzer"。
你的唯一职责是：从庞大的日志文件中提炼出关键的错误信息。

---

# 【工作流程】

## 1. 接收输入
你会收到一个长日志文件路径或大段日志文本。

## 2. 初步切片
使用以下命令进行初步过滤：

### 提取错误行
```bash
grep -i "error\|fail\|exception\|fatal\|panic" <file_path> | tail -100
```

### 提取最近的日志
```bash
tail -n 500 <file_path>
```

### 提取特定状态码（如 HTTP 5xx）
```bash
grep -E "5[0-9]{2}" <file_path> | tail -50
```

### 提取堆栈跟踪
```bash
grep -A 10 "Traceback\|Exception\|Error:" <file_path> | head -100
```

## 3. 精炼输出
基于初步切片的结果，输出一份不超过 500 字的精炼摘要，包含：

### 必须包含的内容
- **错误类型**：主要错误类型（如 ConnectionRefused, OOM, Timeout）
- **错误堆栈**：关键的堆栈跟踪信息
- **影响范围**：受影响的接口或服务
- **时间范围**：错误发生的时间段
- **频率**：错误出现的频率

### 输出格式
```markdown
## 日志分析摘要

### 错误类型
[主要错误类型]

### 关键堆栈
[关键堆栈信息]

### 影响范围
[受影响的组件]

### 时间分布
[错误发生的时间段]

### 建议
[初步建议]
```

---

# 【约束条件】

1. **输出长度**：严格控制在 500 字以内
2. **只读操作**：只使用 grep, tail, head 等只读命令
3. **不执行修复**：只分析问题，不尝试修复
4. **专注错误**：忽略正常的日志，只关注异常信息
5. **结构化**：使用 Markdown 格式输出

---

# 【示例】

**输入**：`/var/log/nginx/error.log` (100MB)

**初步切片**：
```bash
grep -i error /var/log/nginx/error.log | tail -50
```

**输出**：
```markdown
## 日志分析摘要

### 错误类型
- Connection refused (111)
- Upstream timeout (110)

### 关键堆栈
```
2024/01/15 10:23:45 [error] 1234#0: *56789 connect() failed (111: Connection refused)
while connecting to upstream, client: 192.168.1.100,
server: 10.0.0.5:8080
```

### 影响范围
- 后端服务 10.0.0.5:8080 不可用
- 影响所有依赖该服务的接口

### 时间分布
- 错误集中在 10:20 - 10:30
- 频率：约 100 次/分钟

### 建议
- 检查后端服务 10.0.0.5:8080 是否存活
- 检查网络连通性
```
"""


class LogAnalyzerAgent:
    """
    日志分析子智能体

    专门处理长日志文件的分析，使用更小、更快的模型，
    返回高度精炼的错误摘要。

    Attributes:
        executor: Docker 执行器
        llm_client: LLM 客户端（使用小模型）
        max_output_length: 最大输出长度（默认 500 字）
    """

    def __init__(
        self,
        executor: Optional[DockerExecutor] = None,
        llm_client: Optional[LLMClient] = None,
        max_output_length: int = 500,
        model: str = "gpt-3.5-turbo"
    ):
        """
        初始化 LogAnalyzerAgent

        Args:
            executor: Docker 执行器（默认创建新实例）
            llm_client: LLM 客户端（默认创建小模型实例）
            max_output_length: 最大输出长度（默认 500 字）
            model: 模型名称（默认 gpt-3.5-turbo，便宜且快速）
        """
        self.executor = executor or DockerExecutor()
        self.max_output_length = max_output_length

        # 使用小模型（便宜、快速）
        if llm_client:
            self.llm = llm_client
        else:
            try:
                self.llm = LLMClient(
                    model=model,
                    max_tokens=1024,  # 限制输出长度
                    temperature=0.3   # 降低随机性
                )
            except ValueError:
                # 如果没有 API Key，使用 Mock
                from utils.mock_llm import MockLLMClient
                self.llm = MockLLMClient(scenario="cpu_high")

        print(f"[LogAnalyzerAgent] 初始化完成")
        print(f"   - 模型: {getattr(self.llm, 'model', 'Mock')}")
        print(f"   - 最大输出长度: {max_output_length} 字")

    def analyze(
        self,
        file_path: Optional[str] = None,
        log_content: Optional[str] = None,
        context: Optional[str] = None
    ) -> str:
        """
        分析日志文件或日志内容

        Args:
            file_path: 日志文件路径（优先）
            log_content: 日志内容（当 file_path 为空时使用）
            context: 上下文信息（如告警描述）

        Returns:
            str: 精炼的日志分析摘要（不超过 max_output_length 字）
        """
        print(f"\n[LogAnalyzer] 开始分析...")

        # 步骤 1: 初步切片
        if file_path:
            sliced_content = self._slice_log_file(file_path)
        elif log_content:
            sliced_content = self._slice_log_content(log_content)
        else:
            return "错误: 必须提供 file_path 或 log_content"

        # 步骤 2: 使用 LLM 精炼
        prompt = self._build_analysis_prompt(sliced_content, context)

        response = self.llm.chat(
            user_message=prompt,
            system_prompt=LOG_ANALYZER_SYSTEM_PROMPT
        )

        # 提取内容
        if isinstance(response, dict):
            analysis = response.get("content", "")
        else:
            analysis = getattr(response, 'content', '')

        # 步骤 3: 截断过长的输出
        if len(analysis) > self.max_output_length:
            analysis = analysis[:self.max_output_length]
            analysis += "\n\n[截断] 摘要已截断至 500 字"

        print(f"[LogAnalyzer] 分析完成，输出长度: {len(analysis)} 字")

        return analysis

    def _slice_log_file(self, file_path: str) -> str:
        """
        对日志文件进行初步切片

        Args:
            file_path: 日志文件路径

        Returns:
            str: 切片后的日志内容
        """
        print(f"[LogAnalyzer] 切片文件: {file_path}")

        # 构建切片命令
        slice_commands = [
            # 提取错误行
            f"grep -i 'error\\|fail\\|exception\\|fatal\\|panic' {file_path} 2>/dev/null | tail -50",
            # 提取最近的日志
            f"tail -n 100 {file_path}",
            # 提取 HTTP 5xx 错误
            f"grep -E '5[0-9]{{2}}' {file_path} 2>/dev/null | tail -30",
        ]

        results = []
        for cmd in slice_commands:
            result = self.executor.execute(cmd)
            if result["exit_code"] == 0 and result["stdout"]:
                results.append(result["stdout"])

        return "\n---\n".join(results)

    def _slice_log_content(self, log_content: str) -> str:
        """
        对日志内容进行初步切片

        Args:
            log_content: 日志内容

        Returns:
            str: 切片后的日志内容
        """
        print(f"[LogAnalyzer] 切片内容: {len(log_content)} 字符")

        # 按行分割
        lines = log_content.split("\n")

        # 提取包含错误关键字的行
        error_keywords = ["error", "fail", "exception", "fatal", "panic", "5xx"]
        error_lines = [
            line for line in lines
            if any(kw in line.lower() for kw in error_keywords)
        ]

        # 取最近的 50 行错误
        recent_errors = error_lines[-50:]

        # 取最后 100 行日志
        recent_logs = lines[-100:]

        return "\n---\n".join([
            "## 错误行\n" + "\n".join(recent_errors),
            "## 最近日志\n" + "\n".join(recent_logs)
        ])

    def _build_analysis_prompt(
        self,
        sliced_content: str,
        context: Optional[str] = None
    ) -> str:
        """
        构建分析提示

        Args:
            sliced_content: 切片后的日志内容
            context: 上下文信息

        Returns:
            str: 分析提示
        """
        prompt = f"""请分析以下日志内容，提取关键错误信息，输出一份精炼的摘要。

"""

        if context:
            prompt += f"""
### 上下文信息
{context}

"""

        prompt += f"""
### 日志内容
{sliced_content}

---

请输出一份不超过 500 字的日志分析摘要。
"""

        return prompt


# ==========================================
# 测试代码
# ==========================================
if __name__ == "__main__":
    print("="*60)
    print("[Test] LogAnalyzerAgent")
    print("="*60)

    # 创建 LogAnalyzerAgent
    agent = LogAnalyzerAgent()

    # 测试内容分析
    test_log = """
2024-01-15 10:23:45 [error] 1234#0: *56789 connect() failed (111: Connection refused)
2024-01-15 10:23:46 [error] 1234#0: *56790 connect() failed (111: Connection refused)
2024-01-15 10:23:47 [warn] 1234#0: *56791 upstream timed out (110: Connection timed out)
2024-01-15 10:23:48 [info] 1234#0: *56792 client disconnected
2024-01-15 10:23:49 [error] 1234#0: *56793 connect() failed (111: Connection refused)
    """ * 100  # 模拟长日志

    result = agent.analyze(
        log_content=test_log,
        context="Nginx 返回 502 错误"
    )

    print("\n[Result] 分析结果:")
    print(result)
    print(f"\n[Result] 输出长度: {len(result)} 字")
