"""
Pytest 配置文件

运行命令：
    pytest tests/ -v                    # 运行所有测试
    pytest tests/test_interceptor.py -v # 运行拦截器测试
    pytest tests/test_docker_executor.py -v -m "not docker"  # 跳过 Docker 测试
    pytest tests/test_agent_engine.py -v  # 运行引擎 Mock 测试
"""

import sys
from pathlib import Path

# 添加 src 目录到 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def pytest_configure(config):
    """Pytest 配置"""
    config.addinivalue_line(
        "markers", "docker: 需要 Docker 容器的集成测试"
    )
