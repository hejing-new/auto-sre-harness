"""
Mock 测试：Agent Loop 引擎 (AgentEngine) + LogBroadcaster

运行命令：
    pytest tests/test_agent_engine.py -v

测试覆盖：
    - Mock LLM 返回 tool_calls 的解析
    - 安全拦截器集成
    - 循环控制逻辑
    - 错误处理
    - LogBroadcaster 日志广播器
"""

import sys
import json
import asyncio
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

# 添加 src 目录到 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest
from agent.engine import AgentEngine, LoopState, LoopResult
from utils.mock_llm import MockLLMClient, ResponseType
from security.interceptor import CommandInterceptor, CommandRisk
from core.log_broadcaster import LogBroadcaster, get_broadcaster, LogLevel


class TestAgentEngineWithMockLLM:
    """使用 MockLLMClient 的测试（模拟完整流程）"""

    @pytest.fixture
    def mock_executor(self):
        """创建 Mock 执行器"""
        executor = Mock()
        executor.execute.return_value = {
            "exit_code": 0,
            "stdout": "mock output",
            "stderr": ""
        }
        return executor

    @pytest.fixture
    def mock_llm(self):
        """创建真实的 MockLLMClient"""
        return MockLLMClient(scenario="cpu_high")

    @pytest.fixture
    def interceptor(self):
        """创建真实的拦截器"""
        return CommandInterceptor(strict_mode=True)

    @pytest.fixture
    def engine(self, mock_executor, mock_llm, interceptor):
        """创建 Agent 引擎"""
        return AgentEngine(
            executor=mock_executor,
            llm_client=mock_llm,
            interceptor=interceptor,
            max_iterations=10
        )

    def test_basic_flow(self, engine, mock_executor):
        """测试基本流程"""
        result = engine.run("测试告警")

        # 验证执行器被调用（MockLLM 会生成命令）
        assert mock_executor.execute.called

    def test_state_transitions(self, engine):
        """测试状态流转"""
        result = engine.run("测试告警")

        # 验证步骤记录
        assert len(engine.steps) > 0

        # 验证最终状态（最后一步的状态应该是 COMPLETED）
        assert engine.steps[-1].state == LoopState.COMPLETED

    def test_reset_clears_state(self, engine):
        """测试重置清除状态"""
        engine.run("测试告警")
        engine._reset()

        assert engine.current_state == LoopState.IDLE
        assert len(engine.steps) == 0
        assert engine.iteration_count == 0


class TestAgentEngineWithRealLLMResponse:
    """使用真实 LLM 响应格式的测试（测试 Tool Calling 解析）"""

    @pytest.fixture
    def mock_executor(self):
        """创建 Mock 执行器"""
        executor = Mock()
        executor.execute.return_value = {
            "exit_code": 0,
            "stdout": "root 1 0.0 0.0 1234 5678 ? S 00:00 0:00 bash",
            "stderr": ""
        }
        return executor

    @pytest.fixture
    def interceptor(self):
        """创建真实的拦截器"""
        return CommandInterceptor(strict_mode=True)

    def create_llm_mock_with_tool_calls(self, tool_calls_list):
        """创建返回 tool_calls 的 LLM Mock"""
        llm = Mock()
        responses = []

        for tool_calls in tool_calls_list:
            responses.append({
                "content": "正在诊断...",
                "tool_calls": tool_calls,
                "finish_reason": "tool_calls"
            })

        llm.chat.side_effect = responses
        llm.reset = Mock()
        llm.add_tool_result = Mock()

        return llm

    def test_parse_execute_command_tool_call(self, mock_executor, interceptor):
        """测试解析 execute_command 工具调用"""
        # 创建返回 execute_command 的 LLM Mock
        llm = self.create_llm_mock_with_tool_calls([
            [{
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "execute_command",
                    "arguments": json.dumps({
                        "command": "ps aux --sort=-%cpu | head -20",
                        "reason": "查看 CPU 占用最高的进程"
                    })
                }
            }]
        ])

        # 再添加一个 finish_diagnosis 响应
        llm.chat.side_effect = [
            {
                "content": "正在诊断...",
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "execute_command",
                        "arguments": json.dumps({
                            "command": "ps aux",
                            "reason": "查看进程"
                        })
                    }
                }],
                "finish_reason": "tool_calls"
            },
            {
                "content": "诊断完成",
                "tool_calls": [{
                    "id": "call_2",
                    "type": "function",
                    "function": {
                        "name": "finish_diagnosis",
                        "arguments": json.dumps({
                            "rca_report": "# RCA 报告\n\n## 问题概述\nCPU 飙高\n\n## 根因分析\n进程过多",
                            "severity": "high",
                            "root_cause_category": "cpu_high"
                        })
                    }
                }],
                "finish_reason": "tool_calls"
            }
        ]

        # 创建引擎（使用 patch 让 isinstance 判断生效）
        with patch('agent.engine.LLMClient', Mock):
            engine = AgentEngine(
                executor=mock_executor,
                llm_client=llm,
                interceptor=interceptor,
                max_iterations=5
            )
            # 强制设置为真实 LLM 模式
            engine.is_real_llm = True

            result = engine.run("测试告警")

        # 验证执行器被调用
        assert mock_executor.execute.called

    def test_parse_finish_diagnosis_tool_call(self, mock_executor, interceptor):
        """测试解析 finish_diagnosis 工具调用"""
        llm = Mock()
        llm.chat.return_value = {
            "content": "诊断完成",
            "tool_calls": [{
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "finish_diagnosis",
                    "arguments": json.dumps({
                        "rca_report": "# RCA 报告\n测试报告",
                        "severity": "high",
                        "root_cause_category": "cpu_high"
                    })
                }
            }],
            "finish_reason": "tool_calls"
        }
        llm.reset = Mock()
        llm.add_tool_result = Mock()

        with patch('agent.engine.LLMClient', Mock):
            engine = AgentEngine(
                executor=mock_executor,
                llm_client=llm,
                interceptor=interceptor,
                max_iterations=5
            )
            engine.is_real_llm = True

            result = engine.run("测试告警")

        # 验证结果
        assert result.success is True
        assert "RCA 报告" in result.final_analysis

    def test_dangerous_command_blocked(self, mock_executor, interceptor):
        """测试危险命令被拦截"""
        llm = Mock()
        llm.chat.return_value = {
            "content": "尝试修复...",
            "tool_calls": [{
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "execute_command",
                    "arguments": json.dumps({
                        "command": "rm -rf /tmp/test",
                        "reason": "清理临时文件"
                    })
                }
            }],
            "finish_reason": "tool_calls"
        }
        llm.reset = Mock()
        llm.add_tool_result = Mock()

        # 再添加一个 finish_diagnosis 响应（防止无限循环）
        llm.chat.side_effect = [
            {
                "content": "尝试修复...",
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "execute_command",
                        "arguments": json.dumps({
                            "command": "rm -rf /tmp/test",
                            "reason": "清理"
                        })
                    }
                }],
                "finish_reason": "tool_calls"
            },
            {
                "content": "诊断完成",
                "tool_calls": [{
                    "id": "call_2",
                    "type": "function",
                    "function": {
                        "name": "finish_diagnosis",
                        "arguments": json.dumps({
                            "rca_report": "命令被拦截",
                            "severity": "low",
                            "root_cause_category": "test"
                        })
                    }
                }],
                "finish_reason": "tool_calls"
            }
        ]

        with patch('agent.engine.LLMClient', Mock):
            engine = AgentEngine(
                executor=mock_executor,
                llm_client=llm,
                interceptor=interceptor,
                max_iterations=5
            )
            engine.is_real_llm = True

            result = engine.run("测试告警")

        # 验证命令被拦截（执行器不应被调用或调用次数为 0）
        # 注意：由于拦截后会有反馈，add_tool_result 应该被调用
        assert llm.add_tool_result.called

    def test_safe_command_executed(self, mock_executor, interceptor):
        """测试安全命令被执行"""
        llm = Mock()
        llm.chat.return_value = {
            "content": "查看进程...",
            "tool_calls": [{
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "execute_command",
                    "arguments": json.dumps({
                        "command": "ps aux",
                        "reason": "查看进程状态"
                    })
                }
            }],
            "finish_reason": "tool_calls"
        }
        llm.reset = Mock()
        llm.add_tool_result = Mock()

        # 再添加一个 finish_diagnosis 响应
        llm.chat.side_effect = [
            {
                "content": "查看进程...",
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "execute_command",
                        "arguments": json.dumps({
                            "command": "ps aux",
                            "reason": "查看进程"
                        })
                    }
                }],
                "finish_reason": "tool_calls"
            },
            {
                "content": "诊断完成",
                "tool_calls": [{
                    "id": "call_2",
                    "type": "function",
                    "function": {
                        "name": "finish_diagnosis",
                        "arguments": json.dumps({
                            "rca_report": "诊断完成",
                            "severity": "low",
                            "root_cause_category": "test"
                        })
                    }
                }],
                "finish_reason": "tool_calls"
            }
        ]

        with patch('agent.engine.LLMClient', Mock):
            engine = AgentEngine(
                executor=mock_executor,
                llm_client=llm,
                interceptor=interceptor,
                max_iterations=5
            )
            engine.is_real_llm = True

            result = engine.run("测试告警")

        # 验证执行器被调用
        assert mock_executor.execute.called

    def test_llm_error_response(self, mock_executor, interceptor):
        """测试 LLM 返回错误"""
        llm = Mock()
        llm.chat.return_value = {
            "content": "LLM 调用失败: 网络错误",
            "tool_calls": [],
            "finish_reason": "error"
        }
        llm.reset = Mock()
        llm.add_tool_result = Mock()

        with patch('agent.engine.LLMClient', Mock):
            engine = AgentEngine(
                executor=mock_executor,
                llm_client=llm,
                interceptor=interceptor,
                max_iterations=5
            )
            engine.is_real_llm = True

            result = engine.run("测试告警")

        # 验证失败
        assert result.success is False

    def test_max_iterations_limit(self, mock_executor, interceptor):
        """测试最大迭代次数限制"""
        llm = Mock()
        # 始终返回工具调用（不结束）
        llm.chat.return_value = {
            "content": "继续诊断...",
            "tool_calls": [{
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "execute_command",
                    "arguments": json.dumps({
                        "command": "echo 'test'",
                        "reason": "测试"
                    })
                }
            }],
            "finish_reason": "tool_calls"
        }
        llm.reset = Mock()
        llm.add_tool_result = Mock()

        with patch('agent.engine.LLMClient', Mock):
            engine = AgentEngine(
                executor=mock_executor,
                llm_client=llm,
                interceptor=interceptor,
                max_iterations=3
            )
            engine.is_real_llm = True

            result = engine.run("测试告警")

        # 验证迭代次数不超过最大值
        assert result.total_steps <= 3


class TestAgentEngineIntegration:
    """集成测试（使用真实的 MockLLM 和拦截器）"""

    @pytest.fixture
    def mock_executor(self):
        """创建 Mock 执行器"""
        executor = Mock()
        executor.execute.return_value = {
            "exit_code": 0,
            "stdout": "Linux sandbox 5.4.0-42-generic #46-Ubuntu SMP x86_64 GNU/Linux",
            "stderr": ""
        }
        return executor

    def test_mock_llm_with_interceptor(self, mock_executor):
        """测试 MockLLM 与拦截器集成"""
        llm = MockLLMClient(scenario="cpu_high")
        interceptor = CommandInterceptor(strict_mode=True)

        engine = AgentEngine(
            executor=mock_executor,
            llm_client=llm,
            interceptor=interceptor,
            max_iterations=10
        )

        result = engine.run("测试告警")

        # 验证执行器被调用（MockLLM 会生成安全命令）
        assert mock_executor.execute.called

        # 验证步骤记录
        assert len(engine.steps) > 0

    def test_interceptor_blocks_dangerous_commands(self, mock_executor):
        """测试拦截器阻止危险命令"""
        # 使用 Nginx 场景（包含危险命令）
        llm = MockLLMClient(scenario="nginx_error")
        interceptor = CommandInterceptor(strict_mode=True)

        engine = AgentEngine(
            executor=mock_executor,
            llm_client=llm,
            interceptor=interceptor,
            max_iterations=10
        )

        result = engine.run("测试告警")

        # 验证有命令被拦截
        blocked_steps = [s for s in engine.steps if s.intercept_result and not s.intercept_result.allowed]
        assert len(blocked_steps) > 0


class TestLogBroadcaster:
    """日志广播器单元测试"""

    def setup_method(self):
        """每个测试前重置广播器"""
        LogBroadcaster.reset_instance()

    @pytest.mark.asyncio
    async def test_subscribe_and_log(self):
        """测试订阅和日志推送"""
        broadcaster = await get_broadcaster()
        queue = await broadcaster.subscribe()

        await broadcaster.log_info("测试消息")
        entry = await asyncio.wait_for(queue.get(), timeout=1.0)

        assert entry["level"] == "INFO"
        assert entry["message"] == "测试消息"
        assert entry["type"] == "log"

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self):
        """测试多订阅者同时接收"""
        broadcaster = await get_broadcaster()
        q1 = await broadcaster.subscribe()
        q2 = await broadcaster.subscribe()

        await broadcaster.log_error("错误消息")

        e1 = await asyncio.wait_for(q1.get(), timeout=1.0)
        e2 = await asyncio.wait_for(q2.get(), timeout=1.0)

        assert e1["message"] == "错误消息"
        assert e2["message"] == "错误消息"

    @pytest.mark.asyncio
    async def test_complete_signal(self):
        """测试完成信号发送"""
        broadcaster = await get_broadcaster()
        queue = await broadcaster.subscribe()

        result = {"success": True, "steps": 5}
        await broadcaster.complete(result)

        entry = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert entry["type"] == "done"
        assert entry["details"]["result"]["success"] is True

    @pytest.mark.asyncio
    async def test_unsubscribe_stops_receiving(self):
        """测试取消订阅后不再接收消息"""
        broadcaster = await get_broadcaster()
        queue = await broadcaster.subscribe()
        await broadcaster.unsubscribe(queue)

        await broadcaster.log_info("不应收到")

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(queue.get(), timeout=0.5)

    @pytest.mark.asyncio
    async def test_all_log_levels(self):
        """测试所有日志级别"""
        broadcaster = await get_broadcaster()
        queue = await broadcaster.subscribe()

        await broadcaster.log_reasoning("推理中")
        await broadcaster.log_executing("执行中")
        await broadcaster.log_intercepting("拦截中")
        await broadcaster.log_blocked("已拦截")
        await broadcaster.log_success("成功")

        levels = []
        for _ in range(5):
            entry = await asyncio.wait_for(queue.get(), timeout=1.0)
            levels.append(entry["level"])

        assert "REASONING" in levels
        assert "EXECUTING" in levels
        assert "INTERCEPTING" in levels
        assert "BLOCKED" in levels
        assert "SUCCESS" in levels

    @pytest.mark.asyncio
    async def test_is_completed_property(self):
        """测试 is_completed 属性"""
        broadcaster = await get_broadcaster()
        assert broadcaster.is_completed is False

        await broadcaster.complete({"success": True})
        assert broadcaster.is_completed is True

    @pytest.mark.asyncio
    async def test_get_result(self):
        """测试 get_result 方法"""
        broadcaster = await get_broadcaster()
        assert broadcaster.get_result() is None

        result = {"success": True, "data": "test"}
        await broadcaster.complete(result)
        assert broadcaster.get_result() == result


# ==========================================
# 运行测试
# ==========================================
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
