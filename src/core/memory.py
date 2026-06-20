"""
上下文管理器 (Context Manager)

负责管理 Agent Loop 中的对话历史，实现上下文压缩策略，
解决生产环境中的"长日志 Token 灾难"问题。

压缩策略：
    - L1 策略 (条数截断)：对话轮次超过 20 轮时，丢弃中间的无效试错记录，
      只保留 System Prompt（头部）和最近的 5 轮对话（尾部）。
    - L2 策略 (结果折叠)：工具返回超过 2000 字符时，物理截断并追加警告。

使用方式：
    context_manager = ContextManager(max_turns=20, tail_turns=5)
    context_manager.add_message({"role": "user", "content": "..."})
    compressed_messages = context_manager.compress(messages)
"""

import json
import copy
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum


class CompressionStrategy(Enum):
    """压缩策略类型"""
    L1_TURN_TRUNCATION = "l1_turn_truncation"  # 条数截断
    L2_RESULT_FOLDING = "l2_result_folding"    # 结果折叠


@dataclass
class CompressionStats:
    """压缩统计信息"""
    original_count: int = 0          # 原始消息数
    compressed_count: int = 0        # 压缩后消息数
    l1_applied_count: int = 0        # L1 策略应用次数
    l2_applied_count: int = 0        # L2 策略应用次数
    total_chars_saved: int = 0       # 节省的字符数


@dataclass
class TruncationWarning:
    """截断警告"""
    tool_name: str                   # 工具名称
    original_length: int              # 原始长度
    truncated_length: int             # 截断后长度
    warning_message: str              # 警告消息


# 截断警告模板
TRUNCATION_WARNING_TEMPLATE = (
    "\n\n[系统截断] 文本过长（原始 {original_length} 字符），"
    "已截断至 {truncated_length} 字符。"
    "请使用专用的日志分析工具(LogAnalyzer)进行提取。"
)


class ContextManager:
    """
    上下文管理器

    负责管理对话历史，实现 L1 和 L2 压缩策略。

    Attributes:
        max_turns: 最大对话轮次（超过则触发 L1 压缩）
        tail_turns: 保留的尾部对话轮数
        max_result_length: 工具返回结果的最大长度（超过则触发 L2 压缩）
        stats: 压缩统计信息
        truncation_warnings: 截断警告列表
    """

    def __init__(
        self,
        max_turns: int = 20,
        tail_turns: int = 5,
        max_result_length: int = 2000
    ):
        """
        初始化上下文管理器

        Args:
            max_turns: 最大对话轮次（默认 20）
            tail_turns: 保留的尾部对话轮数（默认 5）
            max_result_length: 工具返回结果的最大长度（默认 2000 字符）
        """
        self.max_turns = max_turns
        self.tail_turns = tail_turns
        self.max_result_length = max_result_length

        # 统计信息
        self.stats = CompressionStats()
        self.truncation_warnings: List[TruncationWarning] = []

        print(f"[ContextManager] 初始化完成")
        print(f"   - 最大轮次: {max_turns}")
        print(f"   - 保留尾部: {tail_turns} 轮")
        print(f"   - 最大结果长度: {max_result_length} 字符")

    def compress(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        执行上下文压缩

        依次应用 L1 和 L2 策略，返回压缩后的消息列表。

        Args:
            messages: 原始消息列表

        Returns:
            List[Dict]: 压缩后的消息列表
        """
        self.stats = CompressionStats()
        self.truncation_warnings.clear()

        self.stats.original_count = len(messages)

        # 深拷贝，避免修改原始数据
        compressed = copy.deepcopy(messages)

        # 应用 L1 策略（条数截断）
        compressed = self._apply_l1_truncation(compressed)

        # 应用 L2 策略（结果折叠）
        compressed = self._apply_l2_folding(compressed)

        self.stats.compressed_count = len(compressed)

        return compressed

    def _apply_l1_truncation(
        self,
        messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        应用 L1 策略：条数截断

        如果对话轮次超过 max_turns，丢弃中间的无效试错记录，
        只保留 System Prompt（头部）和最近的 tail_turns 轮对话（尾部）。

        Args:
            messages: 消息列表

        Returns:
            List[Dict]: 截断后的消息列表
        """
        # 计算对话轮次（user + assistant 为一对）
        # 只计算非 system 消息
        non_system_messages = [
            m for m in messages if m.get("role") != "system"
        ]
        turn_count = len(non_system_messages) // 2  # 每轮包含 user + assistant

        if turn_count <= self.max_turns:
            return messages

        print(f"[L1] 触发条数截断: {turn_count} 轮 > {self.max_turns} 轮")

        # 分离 system prompt 和对话消息
        system_messages = [
            m for m in messages if m.get("role") == "system"
        ]
        conversation_messages = [
            m for m in messages if m.get("role") != "system"
        ]

        # 保留最近的 tail_turns 轮（每轮 = user + assistant）
        tail_message_count = self.tail_turns * 2
        tail_messages = conversation_messages[-tail_message_count:]

        # 构建压缩后的消息列表
        compressed = system_messages + tail_messages

        # 更新统计
        self.stats.l1_applied_count += 1
        self.stats.total_chars_saved += self._estimate_chars_saved(
            messages, compressed
        )

        print(f"[L1] 截断完成: {len(messages)} -> {len(compressed)} 条消息")

        return compressed

    def _apply_l2_folding(
        self,
        messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        应用 L2 策略：结果折叠

        当任何工具返回超过 max_result_length 字符时，物理截断并追加警告。

        Args:
            messages: 消息列表

        Returns:
            List[Dict]: 折叠后的消息列表
        """
        compressed = []

        for message in messages:
            # 只处理 tool 角色的消息（工具执行结果）
            if message.get("role") == "tool":
                content = message.get("content", "")

                # 尝试解析 JSON 格式的 tool result
                try:
                    result_data = json.loads(content)
                    stdout = result_data.get("stdout", content)

                    if len(stdout) > self.max_result_length:
                        # 截断 stdout
                        truncated_stdout = stdout[:self.max_result_length]
                        warning = TRUNCATION_WARNING_TEMPLATE.format(
                            original_length=len(stdout),
                            truncated_length=self.max_result_length
                        )

                        # 更新 result_data
                        result_data["stdout"] = truncated_stdout + warning
                        result_data["truncated"] = True

                        # 更新消息内容
                        message["content"] = json.dumps(result_data, ensure_ascii=False)

                        # 记录警告
                        self.truncation_warnings.append(TruncationWarning(
                            tool_name=message.get("name", "unknown"),
                            original_length=len(stdout),
                            truncated_length=self.max_result_length,
                            warning_message=warning.strip()
                        ))

                        self.stats.l2_applied_count += 1
                        self.stats.total_chars_saved += len(stdout) - self.max_result_length

                        print(f"[L2] 触发结果折叠: {message.get('name', 'unknown')} "
                              f"{len(stdout)} -> {self.max_result_length} 字符")

                except (json.JSONDecodeError, TypeError):
                    # 非 JSON 格式，直接截断 content
                    if len(content) > self.max_result_length:
                        truncated = content[:self.max_result_length]
                        warning = TRUNCATION_WARNING_TEMPLATE.format(
                            original_length=len(content),
                            truncated_length=self.max_result_length
                        )
                        message["content"] = truncated + warning

                        self.stats.l2_applied_count += 1
                        self.stats.total_chars_saved += len(content) - self.max_result_length

            compressed.append(message)

        return compressed

    def _estimate_chars_saved(
        self,
        original: List[Dict[str, Any]],
        compressed: List[Dict[str, Any]]
    ) -> int:
        """
        估算节省的字符数

        Args:
            original: 原始消息列表
            compressed: 压缩后的消息列表

        Returns:
            int: 节省的字符数
        """
        original_chars = sum(
            len(json.dumps(m, ensure_ascii=False)) for m in original
        )
        compressed_chars = sum(
            len(json.dumps(m, ensure_ascii=False)) for m in compressed
        )
        return max(0, original_chars - compressed_chars)

    def get_stats(self) -> CompressionStats:
        """获取压缩统计信息"""
        return self.stats

    def get_truncation_warnings(self) -> List[TruncationWarning]:
        """获取截断警告列表"""
        return self.truncation_warnings

    def print_stats(self):
        """打印压缩统计信息"""
        print("\n" + "="*60)
        print("[ContextManager] 压缩统计")
        print("="*60)
        print(f"  原始消息数: {self.stats.original_count}")
        print(f"  压缩后消息数: {self.stats.compressed_count}")
        print(f"  L1 策略应用次数: {self.stats.l1_applied_count}")
        print(f"  L2 策略应用次数: {self.stats.l2_applied_count}")
        print(f"  节省字符数: {self.stats.total_chars_saved}")

        if self.truncation_warnings:
            print(f"\n  截断警告 ({len(self.truncation_warnings)} 条):")
            for w in self.truncation_warnings:
                print(f"    - {w.tool_name}: {w.original_length} -> {w.truncated_length}")

        print("="*60)


# ==========================================
# 测试代码
# ==========================================
if __name__ == "__main__":
    print("="*60)
    print("[Test] ContextManager")
    print("="*60)

    # 创建上下文管理器
    manager = ContextManager(max_turns=5, tail_turns=2, max_result_length=100)

    # 模拟对话历史
    messages = [
        {"role": "system", "content": "You are an SRE expert."},
        {"role": "user", "content": "CPU is high"},
        {"role": "assistant", "content": "Let me check..."},
        {"role": "tool", "call_id": "1", "content": json.dumps({
            "exit_code": 0,
            "stdout": "x" * 3000,  # 超长输出
            "stderr": ""
        })},
        {"role": "user", "content": "What's next?"},
        {"role": "assistant", "content": "Check memory..."},
        {"role": "tool", "call_id": "2", "content": json.dumps({
            "exit_code": 0,
            "stdout": "Memory usage: 80%",
            "stderr": ""
        })},
    ]

    # 应用压缩
    compressed = manager.compress(messages)

    # 打印统计
    manager.print_stats()

    # 验证结果
    print(f"\n[Result] 压缩后消息数: {len(compressed)}")
    print(f"[Result] L2 警告数: {len(manager.get_truncation_warnings())}")
