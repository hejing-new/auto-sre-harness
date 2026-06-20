"""
集成测试：Docker 执行器 (DockerExecutor)

运行命令：
    pytest tests/test_docker_executor.py -v

前置条件：
    - Docker 已启动
    - 已运行 docker-compose up -d 启动沙盒容器

测试覆盖：
    - 容器连通性
    - 命令执行正确性
    - 错误处理
"""

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from executor import DockerExecutor


class TestDockerExecutor:
    """Docker 执行器测试类"""

    @pytest.fixture(scope="module")
    def executor(self):
        """创建 Docker 执行器实例（模块级共享）"""
        try:
            return DockerExecutor(container_name="auto-sre-sandbox")
        except Exception as e:
            pytest.skip(f"无法连接到 Docker 容器: {e}")

    # ==========================================
    # 连通性测试
    # ==========================================
    class TestConnectivity:
        """连通性测试组"""

        def test_container_connected(self, executor):
            """测试容器连接成功"""
            assert executor.container is not None
            assert executor.client is not None

    # ==========================================
    # 命令执行测试
    # ==========================================
    class TestCommandExecution:
        """命令执行测试组"""

        def test_echo_hello(self, executor):
            """测试简单的 echo 命令"""
            result = executor.execute('echo "hello"')

            assert result["exit_code"] == 0
            assert "hello" in result["stdout"]
            assert result["stderr"] == ""

        def test_echo_with_unicode(self, executor):
            """测试包含 Unicode 的命令"""
            result = executor.execute('echo "Hello, 世界!"')

            assert result["exit_code"] == 0
            assert "Hello" in result["stdout"]

        def test_pwd_command(self, executor):
            """测试 pwd 命令"""
            result = executor.execute("pwd")

            assert result["exit_code"] == 0
            assert "/root" in result["stdout"]

        def test_ls_command(self, executor):
            """测试 ls 命令"""
            result = executor.execute("ls -la /root")

            assert result["exit_code"] == 0
            assert result["stdout"] != ""

        def test_uname_command(self, executor):
            """测试 uname 命令"""
            result = executor.execute("uname -a")

            assert result["exit_code"] == 0
            assert "Linux" in result["stdout"]

    # ==========================================
    # 错误处理测试
    # ==========================================
    class TestErrorHandling:
        """错误处理测试组"""

        def test_invalid_command(self, executor):
            """测试无效命令"""
            result = executor.execute("nonexistent_command_xyz")

            assert result["exit_code"] != 0
            assert result["stderr"] != ""

        def test_command_with_error(self, executor):
            """测试会报错的命令"""
            result = executor.execute("ls /nonexistent_directory")

            assert result["exit_code"] != 0
            assert "No such file or directory" in result["stderr"]

        def test_false_command(self, executor):
            """测试 false 命令（返回非零退出码）"""
            result = executor.execute("false")

            assert result["exit_code"] != 0

    # ==========================================
    # 复杂命令测试
    # ==========================================
    class TestComplexCommands:
        """复杂命令测试组"""

        def test_pipe_command(self, executor):
            """测试管道命令"""
            result = executor.execute("echo 'hello world' | wc -w")

            assert result["exit_code"] == 0
            assert "2" in result["stdout"]

        def test_multiple_commands(self, executor):
            """测试多条命令组合"""
            result = executor.execute("echo 'first' && echo 'second'")

            assert result["exit_code"] == 0
            assert "first" in result["stdout"]
            assert "second" in result["stdout"]

        def test_command_with_timeout(self, executor):
            """测试长时间运行的命令（应该能正常返回）"""
            result = executor.execute("sleep 1 && echo 'done'")

            assert result["exit_code"] == 0
            assert "done" in result["stdout"]

    # ==========================================
    # 沙盒隔离测试
    # ==========================================
    class TestSandboxIsolation:
        """沙盒隔离测试组"""

        def test_file_creation_in_sandbox(self, executor):
            """测试在沙盒中创建文件（不影响宿主机）"""
            result = executor.execute("echo 'test' > /tmp/test_file.txt && cat /tmp/test_file.txt")

            assert result["exit_code"] == 0
            assert "test" in result["stdout"]

        def test_cleanup_in_sandbox(self, executor):
            """测试在沙盒中删除文件"""
            # 创建文件
            executor.execute("echo 'test' > /tmp/test_delete.txt")

            # 删除文件
            result = executor.execute("rm /tmp/test_delete.txt && echo 'deleted'")

            assert result["exit_code"] == 0
            assert "deleted" in result["stdout"]

        def test_process_isolation(self, executor):
            """测试进程隔离"""
            result = executor.execute("ps aux | head -5")

            assert result["exit_code"] == 0
            assert "root" in result["stdout"]


# ==========================================
# 运行测试
# ==========================================
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
