---
tags: [评估, 检索]
---

# 评估体系（Evaluation）

评估是 AI 系统从实验到生产的关键门槛。对 [[rag]] 系统而言，需要分层评估检索质量和生成质量；
对 [[agent]] 系统则需评估多步任务的整体成功率。

## RAG 评估框架

### 检索层指标
- **召回率（Recall@K）**：正确文档是否出现在 top-K 结果中
- **MRR（Mean Reciprocal Rank）**：正确答案的平均排名倒数
- **NDCG**：归一化折损累积增益，考虑排名权重

这些指标直接反映 [[embedding]] 质量和 [[reranking]] 效果。

### 生成层指标
- **忠实度（Faithfulness）**：答案是否与检索上下文一致，检验幻觉率
- **答案相关性（Answer Relevance）**：答案是否真正回答了问题
- **上下文精确率（Context Precision）**：召回内容中有多少真正被使用

### 端到端工具

RAGAS 是最流行的 RAG 评估框架，利用 [[llm]] 作为评判者自动评分。
[[claude]] 因其强大的理解能力，常被用作评估 judge。

## Agent 评估

[[agent]] 评估更复杂，需要跟踪每一步的 [[tool-use]] 是否正确，以及最终任务是否达成。
[[knowledge-graph]] 可以帮助追踪 Agent 的推理路径，便于回溯分析失败案例。

## 持续评估

生产环境需要建立自动化评估流水线，通过 [[semantic-search]] 检测数据分布变化，
及时发现性能退化并触发 [[fine-tuning]] 或 [[prompt-engineering]] 优化。
