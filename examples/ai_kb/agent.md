---
tags: [Agent, 生成]
---

# 智能体（Agent）

Agent 是能够自主感知环境、制定计划、调用工具并执行多步任务的 AI 系统。
与单次 [[rag]] 问答不同，Agent 可以迭代地检索、推理、行动，解决复杂问题。

## Agent 的核心组成

1. **推理引擎**：通常是强大的 [[llm]]（如 [[claude]]），负责理解任务与制定决策
2. **[[planning]]**：将复杂任务分解为可执行子步骤，如 ReAct、Tree of Thoughts
3. **[[tool-use]]**：调用外部工具（搜索、代码执行、API），突破纯文本推理限制
4. **记忆**：短期（上下文窗口）+ 长期（[[vector-db]] / [[knowledge-graph]]）

## Agent 与 RAG 的结合

Agent 可以把 [[rag]] 作为工具：当推理需要外部知识时，调用 RAG 检索接口，
将结果纳入下一步推理。[[semantic-search]] 和 [[knowledge-graph]] 查询都可以封装为 Agent 工具。

## 多步规划示例

用户提问"帮我分析这份合同的主要风险" → Agent 分解任务：
1. 用 [[chunking]] + [[embedding]] 处理合同文档
2. 多次检索不同条款
3. 调用法律知识库做 [[semantic-search]]
4. 综合输出结构化分析

## 评估与安全

[[evaluation]] 需要针对 Agent 的多步行为设计专项指标（任务成功率、步骤效率）。
[[guardrails]] 在 Agent 中尤为重要，防止工具滥用和有害行为链。
