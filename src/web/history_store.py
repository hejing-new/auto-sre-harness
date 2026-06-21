"""
诊断历史记录存储模块

使用内存列表存储诊断历史，支持：
- 保存诊断结果
- 查询历史列表（按时间倒序）
- 查询单次诊断详情
"""

import threading
from datetime import datetime
from typing import Optional, List, Dict, Any


class HistoryStore:
    """线程安全的历史记录存储"""

    def __init__(self, max_records: int = 100):
        self._records: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self._max_records = max_records

    def add_record(self, record: Dict[str, Any]) -> str:
        """
        添加一条历史记录

        Args:
            record: 诊断结果记录

        Returns:
            task_id: 任务ID
        """
        # 生成 task_id
        fmt = "%Y%m%d_%H%M%S"
        task_id = f"task_{datetime.now().strftime(fmt)}_{len(self._records):04d}"

        entry = {
            "task_id": task_id,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "alert": record.get("alert", ""),
            "container": record.get("container", "auto-sre-sandbox"),
            "status": "success" if record.get("success") else "failed",
            "total_steps": record.get("total_steps", 0),
            "commands_executed": record.get("commands_executed", 0),
            "commands_blocked": record.get("commands_blocked", 0),
            "final_analysis": record.get("final_analysis", ""),
            "error": record.get("error", ""),
            "compression_stats": record.get("compression_stats", {}),
        }

        with self._lock:
            self._records.insert(0, entry)  # 新记录在前
            # 超出限制时删除旧记录
            if len(self._records) > self._max_records:
                self._records = self._records[:self._max_records]

        return task_id

    def get_list(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """
        获取历史记录列表（按时间倒序）

        Args:
            limit: 返回数量
            offset: 偏移量

        Returns:
            历史记录列表
        """
        with self._lock:
            return self._records[offset:offset + limit]

    def get_detail(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        获取单次诊断详情

        Args:
            task_id: 任务ID

        Returns:
            诊断详情，如果不存在返回 None
        """
        with self._lock:
            for record in self._records:
                if record["task_id"] == task_id:
                    return record
        return None

    def count(self) -> int:
        """获取记录总数"""
        with self._lock:
            return len(self._records)


# 全局单例
history_store = HistoryStore(max_records=100)
