---
tags: [检索, 生成, 基础设施]
---

# AI 工程知识库导航

本知识库涵盖现代 AI 工程的核心概念，从基础的 [[embedding]] 向量表示到完整的 [[rag]] 检索增强生成系统，再到 [[agent]] 智能体与 [[planning]] 规划能力，以及 [[evaluation]] 评估体系。

## 检索与向量技术

- [[embedding]]：将文本映射为稠密向量，是一切语义检索的基础
- [[vector-db]]：存储和检索向量的专用数据库
- [[semantic-search]]：基于语义理解的搜索，区别于关键词匹配
- [[ann]]：近似最近邻算法，实现高效向量检索
- [[chunking]]：文档切分策略，直接影响检索粒度与质量
- [[reranking]]：召回后的精排，提升最终结果相关性

## 生成与模型

- [[llm]]：大语言模型，RAG 的生成核心
- [[claude]]：Anthropic 研发的 Claude 系列模型
- [[prompt-engineering]]：提示词工程，引导模型输出
- [[fine-tuning]]：微调技术，让通用模型适应特定领域

## 系统与架构

- [[rag]]：检索增强生成，将外部知识与模型结合
- [[knowledge-graph]]：知识图谱，结构化表达实体关系
- [[lancedb]]：本库使用的向量数据库后端
- [[agent]]：智能体，自主规划执行多步任务
- [[tool-use]]：工具调用能力，连接 Agent 与外部世界
- [[planning]]：规划能力，让 Agent 分解复杂任务
- [[multimodal]]：多模态，超越纯文本的 AI 能力
- [[guardrails]]：安全护栏，控制模型行为边界
- [[evaluation]]：评估体系，衡量 AI 系统效果
