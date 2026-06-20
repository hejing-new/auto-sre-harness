"""
命令安全拦截器 (Command Security Interceptor) - V3

基于词法分析的智能拦截器，支持 Human-in-the-Loop 审批机制。

核心特性：
1. 使用 shlex.split 进行标准 Token 拆解
2. 精确匹配危险标志（如 "-9"）
3. 重定向防御（检测 > /etc 等）
4. 语法错误处理（捕获 ValueError）
5. **Human-in-the-Loop 审批**：危险命令发送钉钉卡片，等待人工审批

审批流程：
- 命中危险命令 → 生成 task_id → 发送钉钉卡片 → 阻塞等待审批
- 60 秒内未审批 → 自动拒绝
- 审批通过 → 放行；审批拒绝 → 拦截
"""

import re
import shlex
import uuid
import time
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Tuple, List, Optional, Dict

# 导入钉钉机器人
try:
    from utils.dingtalk_bot import get_dingtalk_bot, is_dingtalk_enabled
except ImportError:
    get_dingtalk_bot = None
    is_dingtalk_enabled = lambda: False


class CommandRisk(Enum):
    """命令风险等级"""
    SAFE = "safe"           # 安全，直接放行
    DANGEROUS = "dangerous" # 危险，拦截拒绝
    UNKNOWN = "unknown"     # 未知，默认拦截
    SYNTAX_ERROR = "syntax_error"  # 语法错误
    PENDING_APPROVAL = "pending_approval"  # 等待审批


@dataclass
class InterceptResult:
    """拦截结果"""
    allowed: bool
    risk_level: CommandRisk
    reason: str
    original_command: str
    task_id: Optional[str] = None  # 审批任务 ID


class CommandInterceptor:
    """
    基于词法分析的命令拦截器，支持 Human-in-the-Loop 审批。
    """

    # ==========================================
    # 审批状态存储（类级别）
    # ==========================================
    # 格式: {task_id: {"status": "approved"|"rejected"|"timeout", "timestamp": ...}}
    APPROVAL_STATUS: Dict[str, Dict] = {}
    APPROVAL_LOCK = threading.Lock()

    # 审批超时时间（秒）
    APPROVAL_TIMEOUT = 60

    # 钉钉回调基础 URL
    DINGTALK_CALLBACK_BASE = "http://127.0.0.1:8000"

    # ==========================================
    # 主命令黑名单（直接拦截）
    # ==========================================
    BLOCKED_COMMANDS = {
        # 删除操作
        "rm", "rmdir", "unlink", "shred",

        # 进程杀死
        "kill", "killall", "pkill",

        # 权限提升
        "sudo", "su", "chown", "chmod", "chgrp",

        # 系统控制
        "reboot", "shutdown", "poweroff", "halt", "init",
        "systemctl", "service",

        # 包管理修改
        "apt", "apt-get", "yum", "dnf", "pip", "npm", "gem",

        # 代码执行
        "python", "python3", "node", "ruby", "perl",
        "bash", "sh", "zsh", "dash",

        # 网络工具（可能被滥用）
        "nmap", "netcat", "nc", "wireshark", "tcpdump",

        # 用户管理
        "useradd", "userdel", "usermod", "passwd", "visudo",

        # 防火墙/网络配置
        "iptables", "ufw", "firewalld", "nftables",

        # 磁盘操作
        "fdisk", "mkfs", "mkswap", "dd",

        # 压缩/解压（可能覆盖）
        "tar", "gzip", "bzip2", "unzip", "rar", "7z",
    }

    # ==========================================
    # 需要审批的命令（不直接拦截，发送审批请求）
    # ==========================================
    # 这些命令如果命中危险参数，会触发审批流程
    APPROVAL_REQUIRED_COMMANDS = {
        "systemctl", "service",  # 服务管理
        "docker", "docker-compose",  # Docker 操作
    }

    # ==========================================
    # 危险参数（精确匹配才拦截）
    # ==========================================
    DANGEROUS_FLAGS = {
        # rm 危险参数
        "--no-preserve-root",
        "-rf", "-fr",

        # kill 危险参数
        "-9", "-SIGKILL", "-KILL",

        # 强制覆盖参数
        "--force", "-f",
        "--yes", "-y",
    }

    # ==========================================
    # 系统关键目录（重定向到这里会被拦截）
    # ==========================================
    CRITICAL_DIRECTORIES = {
        "/etc",      # 系统配置
        "/boot",     # 启动文件
        "/sys",      # 系统信息
        "/proc",     # 进程信息
        "/dev",      # 设备文件
        "/usr",      # 系统程序
        "/lib", "/lib64",  # 系统库
        "/var",      # 变量数据（包括日志）
        "/root",     # root 家目录
    }

    # 重定向操作符
    REDIRECT_OPERATORS = {">", ">>", "2>", "2>&1", "&>", "1>"}

    # ==========================================
    # 安全命令白名单（允许执行）
    # ==========================================
    SAFE_COMMANDS = {
        # 系统信息查看
        "top", "htop", "uptime", "w", "who", "whoami", "hostname",
        "uname", "hostnamectl", "lscpu", "lsblk", "df", "du", "free",

        # 进程查看
        "ps", "pstree", "pgrep", "pidof",

        # 网络查看
        "netstat", "ss", "ip", "ifconfig", "ping",
        "telnet", "traceroute", "dig", "nslookup",

        # 文件查看（只读）
        "ls", "ll", "la", "cat", "head", "tail", "less", "more",
        "find", "locate", "which", "whereis", "file", "stat",

        # 日志查看
        "journalctl", "dmesg",

        # 包管理查看
        "dpkg", "apt list", "rpm", "pip list",

        # Docker 查看
        "docker", "docker-compose",

        # 文本处理（只读场景）
        "grep", "awk", "sed", "wc", "sort", "uniq", "diff", "cmp",

        # 环境变量查看
        "env", "printenv", "echo", "export",

        # 帮助信息
        "man", "help", "type",
    }

    def __init__(self, strict_mode: bool = True, enable_approval: bool = True):
        """
        初始化拦截器

        Args:
            strict_mode: 是否为严格模式（默认True，未知命令一律拦截）
            enable_approval: 是否启用审批机制（默认True）
        """
        self.strict_mode = strict_mode
        self.enable_approval = enable_approval and is_dingtalk_enabled()

        print(f"[Interceptor V3] 初始化完成")
        print(f"   - 黑名单命令数: {len(self.BLOCKED_COMMANDS)}")
        print(f"   - 危险参数数: {len(self.DANGEROUS_FLAGS)}")
        print(f"   - 安全命令数: {len(self.SAFE_COMMANDS)}")
        print(f"   - 严格模式: {'启用' if strict_mode else '禁用'}")
        print(f"   - 审批机制: {'启用' if self.enable_approval else '禁用'}")

    def intercept(self, command: str) -> InterceptResult:
        """
        拦截检查命令

        Args:
            command: 要检查的命令

        Returns:
            InterceptResult: 拦截结果
        """
        command = command.strip()

        # 1. 空命令检查
        if not command:
            return InterceptResult(
                allowed=False,
                risk_level=CommandRisk.UNKNOWN,
                reason="空命令",
                original_command=command
            )

        # 2. 使用 shlex 进行词法分析
        try:
            tokens = shlex.split(command)
        except ValueError as e:
            # 引号不闭合等语法错误
            return InterceptResult(
                allowed=False,
                risk_level=CommandRisk.SYNTAX_ERROR,
                reason=f"命令行语法解析失败，请规范使用引号。错误: {str(e)}",
                original_command=command
            )

        if not tokens:
            return InterceptResult(
                allowed=False,
                risk_level=CommandRisk.UNKNOWN,
                reason="空命令",
                original_command=command
            )

        # 3. 提取主命令
        base_cmd = tokens[0].lower()

        # 4. 检查主命令是否在黑名单中
        if base_cmd in self.BLOCKED_COMMANDS:
            # 检查是否启用审批机制
            if self.enable_approval and base_cmd in self.APPROVAL_REQUIRED_COMMANDS:
                # 需要审批的命令
                return self._request_approval(command, base_cmd, tokens)
            else:
                # 直接拦截
                return InterceptResult(
                    allowed=False,
                    risk_level=CommandRisk.DANGEROUS,
                    reason=f"主命令 '{base_cmd}' 在禁用黑名单中",
                    original_command=command
                )

        # 5. 检查危险参数（精确匹配）
        for token in tokens[1:]:
            if token in self.DANGEROUS_FLAGS:
                # 检查是否需要审批
                if self.enable_approval:
                    return self._request_approval(
                        command, base_cmd, tokens,
                        f"检测到危险参数: {token}"
                    )
                else:
                    return InterceptResult(
                        allowed=False,
                        risk_level=CommandRisk.DANGEROUS,
                        reason=f"检测到危险参数: {token}",
                        original_command=command
                    )

        # 6. 检查重定向操作
        redirect_result = self._check_redirect_safety(tokens, command)
        if redirect_result:
            if self.enable_approval:
                return self._request_approval(
                    command, base_cmd, tokens,
                    redirect_result.reason
                )
            else:
                return redirect_result

        # 7. 检查白名单
        if self._is_in_whitelist(base_cmd, tokens):
            return InterceptResult(
                allowed=True,
                risk_level=CommandRisk.SAFE,
                reason="命令在白名单中，安全操作",
                original_command=command
            )

        # 8. 严格模式：未知命令拦截
        if self.strict_mode:
            return InterceptResult(
                allowed=False,
                risk_level=CommandRisk.UNKNOWN,
                reason=f"未知命令 '{base_cmd}'，严格模式下默认拦截",
                original_command=command
            )

        # 非严格模式：放行
        return InterceptResult(
            allowed=True,
            risk_level=CommandRisk.SAFE,
            reason="非严格模式下放行",
            original_command=command
        )

    def _request_approval(
        self,
        command: str,
        base_cmd: str,
        tokens: List[str],
        reason: str = "命中危险规则"
    ) -> InterceptResult:
        """
        请求人工审批

        Args:
            command: 完整命令
            base_cmd: 主命令
            tokens: Token 列表
            reason: 拦截原因

        Returns:
            InterceptResult: 审批结果
        """
        # 生成任务 ID
        task_id = str(uuid.uuid4())

        print(f"[审批] 发送审批请求: task_id={task_id}")
        print(f"[审批] 命令: {command}")
        print(f"[审批] 原因: {reason}")

        # 初始化审批状态
        with self.APPROVAL_LOCK:
            self.APPROVAL_STATUS[task_id] = {
                "status": "pending",
                "timestamp": time.time()
            }

        # 发送钉钉卡片
        dingtalk_bot = get_dingtalk_bot()
        if dingtalk_bot:
            try:
                dingtalk_bot.send_approval_card(
                    task_id=task_id,
                    command=command,
                    reason=reason,
                    callback_base_url=self.DINGTALK_CALLBACK_BASE
                )
                print(f"[审批] 钉钉卡片已发送")
            except Exception as e:
                print(f"[审批] 钉钉卡片发送失败: {e}")
        else:
            print(f"[审批] 钉钉未启用，使用本地审批")

        # 阻塞等待审批结果
        start_time = time.time()
        while time.time() - start_time < self.APPROVAL_TIMEOUT:
            with self.APPROVAL_LOCK:
                status_info = self.APPROVAL_STATUS.get(task_id, {})
                status = status_info.get("status", "pending")

            if status == "approved":
                print(f"[审批] 审批通过: task_id={task_id}")
                return InterceptResult(
                    allowed=True,
                    risk_level=CommandRisk.SAFE,
                    reason=f"人工审批通过 (task_id={task_id})",
                    original_command=command,
                    task_id=task_id
                )
            elif status == "rejected":
                print(f"[审批] 审批拒绝: task_id={task_id}")
                return InterceptResult(
                    allowed=False,
                    risk_level=CommandRisk.DANGEROUS,
                    reason=f"人工审批拒绝 (task_id={task_id})",
                    original_command=command,
                    task_id=task_id
                )

            time.sleep(1)

        # 超时，自动拒绝
        print(f"[审批] 审批超时，自动拒绝: task_id={task_id}")
        with self.APPROVAL_LOCK:
            self.APPROVAL_STATUS[task_id]["status"] = "timeout"

        return InterceptResult(
            allowed=False,
            risk_level=CommandRisk.DANGEROUS,
            reason=f"审批超时（{self.APPROVAL_TIMEOUT}秒），自动拒绝 (task_id={task_id})",
            original_command=command,
            task_id=task_id
        )

    def _check_redirect_safety(
        self,
        tokens: List[str],
        original_command: str
    ) -> Optional[InterceptResult]:
        """
        检查重定向操作的安全性

        Args:
            tokens: Token 列表
            original_command: 原始命令

        Returns:
            Optional[InterceptResult]: 如果检测到危险重定向，返回拦截结果
        """
        for i, token in enumerate(tokens):
            # 检查是否是重定向操作符
            if token in self.REDIRECT_OPERATORS:
                # 检查重定向目标
                if i + 1 < len(tokens):
                    target = tokens[i + 1]

                    # 检查目标是否是系统关键目录
                    for critical_dir in self.CRITICAL_DIRECTORIES:
                        if target.startswith(critical_dir):
                            return InterceptResult(
                                allowed=False,
                                risk_level=CommandRisk.DANGEROUS,
                                reason=f"危险重定向: {token} {target} (系统关键目录 {critical_dir})",
                                original_command=original_command
                            )

        return None

    def _is_in_whitelist(self, base_cmd: str, tokens: List[str]) -> bool:
        """
        检查命令是否在白名单中

        Args:
            base_cmd: 主命令
            tokens: Token 列表

        Returns:
            bool: 是否在白名单中
        """
        # 直接匹配主命令
        if base_cmd in self.SAFE_COMMANDS:
            return True

        # 前缀匹配（处理带子命令的情况，如 "docker ps", "apt list"）
        command_prefix = " ".join(tokens[:2]).lower() if len(tokens) >= 2 else base_cmd
        if command_prefix in self.SAFE_COMMANDS:
            return True

        # 检查完整命令前缀
        for safe_cmd in self.SAFE_COMMANDS:
            if " ".join(tokens).lower().startswith(safe_cmd + " "):
                return True

        return False

    @classmethod
    def set_approval_status(cls, task_id: str, action: str):
        """
        设置审批状态（供外部回调调用）

        Args:
            task_id: 任务 ID
            action: 审批动作 ("approve" 或 "reject")
        """
        with cls.APPROVAL_LOCK:
            if task_id in cls.APPROVAL_STATUS:
                cls.APPROVAL_STATUS[task_id]["status"] = action
                cls.APPROVAL_STATUS[task_id]["timestamp"] = time.time()
                print(f"[审批] 状态更新: task_id={task_id}, action={action}")

    @classmethod
    def get_approval_status(cls, task_id: str) -> Optional[str]:
        """
        获取审批状态

        Args:
            task_id: 任务 ID

        Returns:
            Optional[str]: 审批状态
        """
        with cls.APPROVAL_LOCK:
            status_info = cls.APPROVAL_STATUS.get(task_id, {})
            return status_info.get("status")


# ==========================================
# 测试代码
# ==========================================
if __name__ == "__main__":
    interceptor = CommandInterceptor(strict_mode=True, enable_approval=False)

    # 测试命令组
    test_commands = [
        # 安全命令（应该放行）
        ("ls -la /var/log", True),
        ("ps aux", True),
        ("top -bn1", True),

        # 危险命令（应该拦截）
        ("rm -rf /tmp/test", False),
        ("kill -9 1234", False),
        ("sudo reboot", False),

        # 语法错误
        ('echo "hello', False),
    ]

    print("\n" + "="*60)
    print("[Test] 命令拦截器测试")
    print("="*60)

    for cmd, expected in test_commands:
        result = interceptor.intercept(cmd)
        status = "PASS" if result.allowed == expected else "FAIL"
        icon = "[PASS]" if status == "PASS" else "[FAIL]"

        print(f"\n{icon} | 命令: {cmd}")
        print(f"   期望: {'放行' if expected else '拦截'}")
        print(f"   实际: {'放行' if result.allowed else '拦截'}")
        print(f"   风险: {result.risk_level.value}")
        print(f"   原因: {result.reason}")
