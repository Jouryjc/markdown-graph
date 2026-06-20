---
tags: [生成, 模型]
---

# Claude 模型系列

Claude 是 Anthropic 研发的大语言模型系列，以宪法 AI（Constitutional AI）方法训练，
在安全性、帮助性与无害性三者之间取得平衡。作为先进 [[llm]] 的代表，Claude 广泛用于
[[rag]] 系统的生成端和 [[agent]] 的推理核心。

## 主要版本

- **Claude 3.5 Sonnet**：速度与智能的平衡点，适合大多数生产场景
- **Claude 3 Opus**：最强推理能力，适合复杂 [[planning]] 任务
- **Claude 3 Haiku**：轻量快速，适合高并发、低延迟场景

## 核心能力

Claude 拥有高达 200K token 的上下文窗口，非常适合处理长文档 [[rag]] 场景，无需过度
依赖 [[chunking]] 来压缩上下文。[[tool-use]] 能力让 Claude 能够调用外部 API、数据库查询等工具。

## 安全与护栏

Anthropic 的宪法 AI 方法内置了 [[guardrails]]，Claude 会拒绝执行有害指令。
在企业部署中，可结合自定义 [[prompt-engineering]] 的系统提示进一步限制行为边界。

## 与本项目的关系

本项目支持将 Claude 作为语义抽取的 [[llm]] provider，用于从 Markdown 文档中提取
实体和关系，建立 [[knowledge-graph]]。[[evaluation]] 测试显示 Claude 在中文实体识别上
表现优异。
