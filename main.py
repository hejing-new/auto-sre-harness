#!/usr/bin/env python3
"""
Auto-SRE Harness - 主入口

这是 Auto-SRE 守护进程的主入口文件，负责：
1. 解析命令行参数
2. 初始化所有组件（执行器、LLM、拦截器）
3. 启动 Agent Loop
4. 输出结果

使用方式:
    # Mock 模式（测试）
    python main.py --mode mock

    # 真实 LLM 模式
    python main.py --mode llm --alert "CPU 使用率 95%"

    # 自定义告警
    python main.py --alert "Nginx 返回 502 错误"
"""

import sys
import os
import argparse
from pathlib import Path

# 添加 src 目录到 Python 路径
src_path = Path(__file__).resolve().parent / "src"
sys.path.insert(0, str(src_path))

from executor import DockerExecutor
from utils.mock_llm import MockLLMClient
from utils.llm_client import LLMClient, SRE_SYSTEM_PROMPT, AVAILABLE_TOOLS
from security.interceptor import CommandInterceptor
from agent.engine import AgentEngine


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="Auto-SRE Harness - 自动化 SRE 诊断系统"
    )

    parser.add_argument(
        "--mode",
        choices=["mock", "llm"],
        default="mock",
        help="运行模式: mock (测试) 或 llm (真实 LLM)"
    )

    parser.add_argument(
        "--alert",
        type=str,
        default="服务器 CPU 使用率 95%，持续 5 分钟",
        help="初始告警信息"
    )

    parser.add_argument(
        "--max-iterations",
        type=int,
        default=10,
        help="最大迭代次数 (默认: 10)"
    )

    parser.add_argument(
        "--container",
        type=str,
        default="auto-sre-sandbox",
        help="Docker 容器名称 (默认: auto-sre-sandbox)"
    )

    parser.add_argument(
        "--strict",
        action="store_true",
        default=True,
        help="启用严格模式（拦截未知命令）"
    )

    return parser.parse_args()


def init_components(args):
    """
    初始化所有组件

    Returns:
        tuple: (executor, llm, interceptor)
    """
    print("[Main] 初始化组件...")

    # 1. 创建 Docker 执行器
    print("\n[1/3] 创建 Docker 执行器...")
    try:
        executor = DockerExecutor(container_name=args.container)
    except Exception as e:
        print(f"[Error] Docker 连接失败: {e}")
        print("[Tip] 请确保已运行: docker-compose up -d")
        sys.exit(1)

    # 2. 创建 LLM 客户端
    print("\n[2/3] 创建 LLM 客户端...")
    if args.mode == "llm":
        try:
            llm = LLMClient()
        except ValueError as e:
            print(f"[Error] LLM 初始化失败: {e}")
            print("[Tip] 请设置环境变量:")
            print("  $env:LLM_API_KEY='your-api-key'")
            print("  $env:LLM_MODEL='gpt-4'")
            print("  $env:LLM_BASE_URL='https://api.openai.com/v1'")
            sys.exit(1)
    else:
        llm = MockLLMClient(scenario="cpu_high")
        print("[Mode] 使用 Mock LLM 模式（测试用）")

    # 3. 创建命令拦截器
    print("\n[3/3] 创建命令拦截器...")
    interceptor = CommandInterceptor(strict_mode=args.strict)

    return executor, llm, interceptor


def main():
    """主函数"""
    print("="*70)
    print("[Auto-SRE Harness] 启动")
    print("="*70)

    # 解析参数
    args = parse_args()
    print(f"\n[Config] 运行模式: {args.mode}")
    print(f"[Config] 最大迭代次数: {args.max_iterations}")
    print(f"[Config] 严格模式: {'启用' if args.strict else '禁用'}")
    print(f"[Config] 告警信息: {args.alert}")

    # 初始化组件
    executor, llm, interceptor = init_components(args)

    # 创建 Agent 引擎
    print("\n[Main] 创建 Agent 引擎...")
    engine = AgentEngine(
        executor=executor,
        llm_client=llm,
        interceptor=interceptor,
        max_iterations=args.max_iterations
    )

    # 运行 Agent Loop
    print("\n[Main] 启动 Agent Loop...")
    result = engine.run(args.alert)

    # 输出结果
    print("\n" + "="*70)
    print("[Result] 诊断结果")
    print("="*70)
    print(f"\n状态: {'[SUCCESS] 成功' if result.success else '[FAILED] 失败'}")
    print(f"总步骤: {result.total_steps}")
    print(f"执行命令: {result.commands_executed}")
    print(f"拦截命令: {result.commands_blocked}")

    if result.final_analysis:
        print(f"\n[RCA Report]")
        print(result.final_analysis)

    print("="*70)

    # 返回退出码
    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())
