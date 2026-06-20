# Auto-SRE Harness 🚀

基于 AI Agent 的自动化 SRE 系统，自动诊断和修复服务器问题。

## 🎯 MVP 目标

跑通核心 Agent Loop 与沙盒拦截机制。

## 📁 项目结构

```
auto-sre-harness/
├── docker-compose.yml          # Docker 编排配置
├── executor.py                 # Docker 执行器（已有）
├── src/
│   ├── security/
│   │   └── interceptor.py      # 命令拦截器 ✨
│   ├── utils/
│   │   └── mock_llm.py         # Mock LLM 客户端 ✨
│   └── agent/
│       └── engine.py           # Agent Loop 引擎 ✨
└── README.md
```

## 🚀 快速开始

### 1. 启动沙盒容器

```bash
docker-compose up -d
```

### 2. 安装依赖

```bash
pip install docker
```

### 3. 运行演示

```bash
cd /d/workspace/auto-sre-harness
python src/agent/engine.py
```

## 🧪 测试场景

| 场景 | 描述 | 预期结果 |
|------|------|---------|
| CPU 飙高 | 模拟 CPU 过高告警 | 执行安全诊断命令，完成分析 |
| Nginx 错误 | Nginx 502 错误日志激增 | 部分命令被拦截，触发安全机制 |

## 🔧 核心组件

### 1. 命令拦截器 (`interceptor.py`)

- **白名单模式**: 只允许安全的读操作（ls, ps, top 等）
- **黑名单检测**: 拦截危险操作（rm, kill, sudo 等）
- **严格模式**: 未知命令默认拦截

### 2. Mock LLM 客户端 (`mock_llm.py`)

- 预设多轮对话，模拟真实 LLM 响应
- 包含安全命令和危险命令场景
- 支持多种测试场景配置

### 3. Agent Loop 引擎 (`engine.py`)

- 核心循环：LLM 思考 → 命令拦截 → 执行 → 反馈
- 状态流转可视化
- 最大迭代次数限制
- 详细执行摘要

## 📊 工作流程

```
告警输入 → LLM 思考 → 生成命令
              ↓
        安全拦截器检查
              ↓
    ┌─── 放行 → 执行命令 → 结果反馈 ───┐
    │                                  │
    └─── 拦截 → 反馈给 LLM ────────────┘
              ↓
         生成 RCA 报告
```

## 🔜 后续计划

- [ ] 接入真实 LLM API（Claude/GPT）
- [ ] 实现系统监控模块
- [ ] 实现 Cron 调度器
- [ ] 实现钉钉/飞书通知
- [ ] 支持自定义告警规则
- [ ] Web 管理界面

---

Built with ❤️ by Auto-SRE Team
