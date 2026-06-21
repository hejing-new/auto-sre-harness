"""
钉钉机器人交互模块

功能：
- 发送钉钉 ActionCard（交互式卡片）
- 支持审批按钮回调

配置：
- Dingding_Secret: 钉钉机器人签名密钥（从 .env 文件加载）
"""

import json
import os
import requests
import hashlib
import hmac
import base64
import urllib.parse
import time
from typing import Optional, Dict, Any
from dataclasses import dataclass
from pathlib import Path

# 尝试加载 .env 文件
try:
    from dotenv import load_dotenv
    # 尝试从项目根目录加载 .env
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass  # dotenv 未安装时忽略


@dataclass
class DingTalkConfig:
    """钉钉机器人配置"""
    webhook_url: str
    secret: Optional[str] = None  # 可选的签名密钥


class DingTalkBot:
    """
    钉钉机器人

    支持发送 ActionCard 交互式卡片，包含审批按钮。
    """

    def __init__(self, webhook_url: str, secret: Optional[str] = None):
        """
        初始化钉钉机器人

        Args:
            webhook_url: 钉钉 Webhook URL
            secret: 可选的签名密钥
        """
        self.webhook_url = webhook_url
        self.secret = secret

    def _generate_sign(self, timestamp: str) -> str:
        """
        生成钉钉签名

        Args:
            timestamp: 时间戳（毫秒）

        Returns:
            str: 签名
        """
        if not self.secret:
            return ""

        string_to_sign = f"{timestamp}\n{self.secret}"
        hmac_code = hmac.new(
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256
        ).digest()
        sign = base64.b64encode(hmac_code).decode("utf-8")
        return sign

    def send_action_card(
        self,
        title: str,
        content: str,
        actions: list,
        task_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        发送钉钉 ActionCard 卡片

        Args:
            title: 卡片标题
            content: 卡片内容（支持 Markdown）
            actions: 按钮列表 [{"title": "按钮文本", "url": "回调 URL"}]
            task_id: 任务 ID（用于日志）

        Returns:
            Dict: 钉钉 API 响应
        """
        payload = {
            "msgtype": "actionCard",
            "actionCard": {
                "title": title,
                "content": content,
                "actions": actions
            }
        }

        return self._send_request(payload, task_id)

    def send_approval_card(
        self,
        task_id: str,
        command: str,
        reason: str,
        callback_base_url: str = "http://127.0.0.1:8000"
    ) -> Dict[str, Any]:
        """
        发送审批卡片

        Args:
            task_id: 任务 ID
            command: 待审批的命令
            reason: 拦截原因
            callback_base_url: 回调基础 URL

        Returns:
            Dict: 钉钉 API 响应
        """
        title = "⚠️ Auto-SRE 命令审批请求"

        content = f"""### 危险命令需要人工审批

**任务 ID**: `{task_id}`

**命令**:
```
{command}
```

**拦截原因**: {reason}

**超时时间**: 60 秒

---
请在下方按钮中选择您的操作："""

        approve_url = f"{callback_base_url}/api/dingtalk/callback?task_id={task_id}&action=approve"
        reject_url = f"{callback_base_url}/api/dingtalk/callback?task_id={task_id}&action=reject"

        actions = [
            {
                "title": "✅ 授权执行 (Approve)",
                "url": approve_url
            },
            {
                "title": "❌ 拒绝 (Reject)",
                "url": reject_url
            }
        ]

        return self.send_action_card(title, content, actions, task_id)

    def send_text(self, text: str) -> Dict[str, Any]:
        """
        发送纯文本消息

        Args:
            text: 文本内容

        Returns:
            Dict: 钉钉 API 响应
        """
        payload = {
            "msgtype": "text",
            "text": {
                "content": text
            }
        }

        return self._send_request(payload)

    def _build_signed_url(self) -> str:
        """
        构建带签名的 Webhook URL

        Returns:
            str: 拼接 timestamp 和 sign 后的完整 URL
        """
        if not self.secret:
            return self.webhook_url

        timestamp = str(round(time.time() * 1000))
        sign = self._generate_sign(timestamp)
        return f"{self.webhook_url}&timestamp={timestamp}&sign={sign}"

    def _send_request(
        self,
        payload: Dict[str, Any],
        task_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        发送请求到钉钉 Webhook（签名拼接到 URL）

        Args:
            payload: 请求体
            task_id: 任务 ID（用于日志）

        Returns:
            Dict: 钉钉 API 响应
        """
        # 构建带签名的 URL
        url = self._build_signed_url()

        try:
            print(f"[DingTalk] 发送消息: {task_id or 'text'}")

            response = requests.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10
            )

            result = response.json()
            print(f"[DingTalk] 响应: {result}")

            return result

        except Exception as e:
            error_msg = f"钉钉消息发送失败: {str(e)}"
            print(f"[DingTalk] 错误: {error_msg}")
            return {"errcode": -1, "errmsg": error_msg}


# ==========================================
# 全局钉钉机器人实例（可选）
# ==========================================

_dingtalk_bot: Optional[DingTalkBot] = None


def init_dingtalk_bot(webhook_url: str, secret: Optional[str] = None):
    """
    初始化全局钉钉机器人实例

    Args:
        webhook_url: 钉钉 Webhook URL
        secret: 可选的签名密钥（如果未提供，从环境变量 Dingding_Secret 加载）
    """
    global _dingtalk_bot

    # 如果未提供 secret，从环境变量加载
    if secret is None:
        secret = os.getenv("Dingding_Secret")
        if secret:
            print("[DingTalk] 从环境变量加载 Dingding_Secret")
        else:
            print("[DingTalk] 未配置签名密钥（Dingding_Secret），将不生成签名")

    _dingtalk_bot = DingTalkBot(webhook_url, secret)

    print(f"[DingTalk] 全局实例初始化完成")
    print(f"   - Webhook: {webhook_url[:50]}...")
    print(f"   - 签名: {'已配置' if secret else '未配置'}")


def get_dingtalk_bot() -> Optional[DingTalkBot]:
    """
    获取全局钉钉机器人实例

    Returns:
        Optional[DingTalkBot]: 钉钉机器人实例
    """
    return _dingtalk_bot


def is_dingtalk_enabled() -> bool:
    """
    检查钉钉是否已启用

    Returns:
        bool: 是否启用
    """
    return _dingtalk_bot is not None


# ==========================================
# 测试代码
# ==========================================
if __name__ == "__main__":
    print("="*60)
    print("[Test] DingTalk Bot")
    print("="*60)

    # 测试配置（请替换为真实的 Webhook URL）
    WEBHOOK_URL = "https://oapi.dingtalk.com/robot/send?access_token=your-token"

    # 初始化
    init_dingtalk_bot(WEBHOOK_URL)

    # 测试发送审批卡片
    result = _dingtalk_bot.send_approval_card(
        task_id="test-task-001",
        command="rm -rf /tmp/test",
        reason="匹配到危险模式: rm"
    )

    print(f"\n[Result] 发送结果: {result}")
