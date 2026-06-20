import docker
import traceback
from abc import ABC, abstractmethod

# 1. 定义执行器接口 (方便以后扩展 MockExecutor 或 LocalExecutor)
class CommandExecutor(ABC):
    @abstractmethod
    def execute(self, command: str) -> dict:
        """
        执行一条 Bash 命令，并返回包含状态码和输出结果的字典
        """
        pass

# 2. 实现 Docker 沙盒执行器
class DockerExecutor(CommandExecutor):
    def __init__(self, container_name: str = "auto-sre-sandbox"):
        try:
            # 连接本机的 Docker 进程
            self.client = docker.from_env()
            # 获取我们的靶机容器
            self.container = self.client.containers.get(container_name)
            print(f"[OK] 成功连接到沙盒靶机: {container_name}")
        except docker.errors.NotFound:
            print(f"[Error] 找不到容器 {container_name}，请确保 docker-compose up -d 已运行！")
            raise
        except Exception as e:
            print(f"[Error] Docker 连接失败，请检查 Docker Desktop 是否启动。")
            raise

    def execute(self, command: str) -> dict:
        """
        在 Docker 容器内部执行命令，这是我们 Agent 的物理手脚
        """
        try:
            print(f"[Executor] 准备执行命令: {command}")
            # exec_run 相当于在终端输入 docker exec
            result = self.container.exec_run(
                cmd=["/bin/bash", "-c", command],
                workdir="/root",
                demux=True # 分离标准输出(stdout)和标准错误(stderr)
            )
            
            # 解析执行结果
            exit_code = result.exit_code
            stdout = result.output[0].decode('utf-8') if result.output[0] else ""
            stderr = result.output[1].decode('utf-8') if result.output[1] else ""
            
            return {
                "exit_code": exit_code,
                "stdout": stdout.strip(),
                "stderr": stderr.strip()
            }
            
        except Exception as e:
            # 这里的 Error Recovery 很重要，执行器挂了不能导致主程序崩溃
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": f"底座执行器发生异常: {traceback.format_exc()}"
            }

# ==========================================
# 3. 本地测试：让我们假装自己是 Agent 来调用它
# ==========================================
if __name__ == "__main__":
    # 实例化我们的沙盒执行器
    executor = DockerExecutor()
    
    # 测试 1: 正常命令 (Agent 想看看当前系统架构)
    print("\n--- 测试 1: 正常命令 ---")
    res1 = executor.execute("uname -a")
    print(f"Exit Code: {res1['exit_code']}")
    print(f"Stdout: {res1['stdout']}")
    
    # 测试 2: 错误命令 (Agent 敲错了命令，我们需要把错误捕捉并准备还给 Agent)
    print("\n--- 测试 2: 错误命令 ---")
    res2 = executor.execute("ls /non_existent_folder")
    print(f"Exit Code: {res2['exit_code']}")
    print(f"Stderr: {res2['stderr']}")
    
    # 测试 3: 破坏性命令 (在这个沙盒里，随便删，不影响你的实体电脑)
    print("\n--- 测试 3: 沙盒隔离测试 ---")
    res3 = executor.execute("mkdir danger_zone && rm -rf danger_zone && echo 'Folder created and deleted safely inside sandbox!'")
    print(f"Stdout: {res3['stdout']}")
