"""
日志广播器 (Log Broadcaster)

基于 asyncio.Queue 的日志分发机制，支持多消费者实时接收 Agent 日志。

功能：
- 提供一个全局可访问的日志队列
- 支持多个消费者同时订阅
- 支持日志级别分类
- 支持流结束信号
"""

import asyncio
import json
from typing import Optional, Dict, Any, AsyncGenerator
from datetime import datetime
from enum import Enum


class LogLevel(Enum):
    """日志级别"""
    INFO = "INFO"
    REASONING = "REASONING"
    INTERCEPTING = "INTERCEPTING"
    EXECUTING = "EXECUTING"
    BLOCKED = "BLOCKED"
    ERROR = "ERROR"
    SUCCESS = "SUCCESS"
    DONE = "DONE"


class LogBroadcaster:
    """
    日志广播器

    使用 asyncio.Queue 实现日志的多播分发。
    """

    _instance: Optional["LogBroadcaster"] = None
    _lock = asyncio.Lock()

    def __init__(self):
        self._queues: list[asyncio.Queue] = []
        self._is_running = False
        self._is_completed = False
        self._result: Optional[Dict[str, Any]] = None

    @classmethod
    async def get_instance(cls) -> "LogBroadcaster":
        """获取单例实例"""
        if cls._instance is None:
            async with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls):
        """重置单例（用于新的诊断会话）"""
        cls._instance = None

    async def subscribe(self) -> asyncio.Queue:
        """
        订阅日志流

        Returns:
            asyncio.Queue: 日志队列
        """
        queue = asyncio.Queue()
        self._queues.append(queue)

        # 如果已经完成，发送结束信号
        if self._is_completed:
            await queue.put(None)

        return queue

    async def unsubscribe(self, queue: asyncio.Queue):
        """
        取消订阅

        Args:
            queue: 要移除的队列
        """
        if queue in self._queues:
            self._queues.remove(queue)

    async def log(
        self,
        level: LogLevel,
        message: str,
        details: Optional[Dict[str, Any]] = None
    ):
        """
        发送日志到所有订阅者

        Args:
            level: 日志级别
            message: 日志消息
            details: 详细信息
        """
        if self._is_completed:
            return

        entry = {
            "timestamp": datetime.now().strftime("%H:%M:%S.%f")[:-3],
            "level": level.value,
            "message": message,
            "details": details,
            "type": "log"
        }

        # 发送到所有订阅者
        for queue in self._queues:
            await queue.put(entry)

    async def log_info(self, message: str):
        """发送 INFO 级别日志"""
        await self.log(LogLevel.INFO, message)

    async def log_reasoning(self, message: str):
        """发送 REASONING 级别日志"""
        await self.log(LogLevel.REASONING, message)

    async def log_intercepting(self, message: str):
        """发送 INTERCEPTING 级别日志"""
        await self.log(LogLevel.INTERCEPTING, message)

    async def log_executing(self, message: str):
        """发送 EXECUTING 级别日志"""
        await self.log(LogLevel.EXECUTING, message)

    async def log_blocked(self, message: str):
        """发送 BLOCKED 级别日志"""
        await self.log(LogLevel.BLOCKED, message)

    async def log_error(self, message: str):
        """发送 ERROR 级别日志"""
        await self.log(LogLevel.ERROR, message)

    async def log_success(self, message: str):
        """发送 SUCCESS 级别日志"""
        await self.log(LogLevel.SUCCESS, message)

    # ========== 同步方法（用于线程回调） ==========

    def log_sync(
        self,
        level: LogLevel,
        message: str,
        details: Optional[Dict[str, Any]] = None
    ):
        """
        同步发送日志到所有订阅者（用于线程回调）

        Args:
            level: 日志级别
            message: 日志消息
            details: 详细信息
        """
        if self._is_completed:
            return

        entry = {
            "timestamp": datetime.now().strftime("%H:%M:%S.%f")[:-3],
            "level": level.value,
            "message": message,
            "details": details,
            "type": "log"
        }

        # 使用 call_soon_threadsafe 将 entry 放入队列（线程安全）
        try:
            loop = asyncio.get_event_loop()
            for queue in self._queues:
                loop.call_soon_threadsafe(queue.put_nowait, entry)
        except RuntimeError:
            # 如果没有事件循环，直接放入队列
            for queue in self._queues:
                queue.put_nowait(entry)

    def log_info_sync(self, message: str):
        """同步发送 INFO 级别日志"""
        self.log_sync(LogLevel.INFO, message)

    def log_reasoning_sync(self, message: str):
        """同步发送 REASONING 级别日志"""
        self.log_sync(LogLevel.REASONING, message)

    def log_intercepting_sync(self, message: str):
        """同步发送 INTERCEPTING 级别日志"""
        self.log_sync(LogLevel.INTERCEPTING, message)

    def log_executing_sync(self, message: str):
        """同步发送 EXECUTING 级别日志"""
        self.log_sync(LogLevel.EXECUTING, message)

    def log_blocked_sync(self, message: str):
        """同步发送 BLOCKED 级别日志"""
        self.log_sync(LogLevel.BLOCKED, message)

    def log_error_sync(self, message: str):
        """同步发送 ERROR 级别日志"""
        self.log_sync(LogLevel.ERROR, message)

    def log_success_sync(self, message: str):
        """同步发送 SUCCESS 级别日志"""
        self.log_sync(LogLevel.SUCCESS, message)

    async def complete(self, result: Dict[str, Any]):
        """
        标记诊断完成

        Args:
            result: 诊断结果
        """
        self._is_completed = True
        self._result = result

        # 发送完成信号到所有订阅者
        for queue in self._queues:
            await queue.put({
                "timestamp": datetime.now().strftime("%H:%M:%S.%f")[:-3],
                "level": LogLevel.DONE.value,
                "message": "诊断流程结束",
                "details": {"result": result},
                "type": "done"
            })

    def get_result(self) -> Optional[Dict[str, Any]]:
        """获取诊断结果"""
        return self._result

    @property
    def is_completed(self) -> bool:
        """是否已完成"""
        return self._is_completed


async def get_broadcaster() -> LogBroadcaster:
    """获取日志广播器实例的便捷函数"""
    return await LogBroadcaster.get_instance()
