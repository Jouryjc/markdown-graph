---
tags: [检索, 向量]
---

# 重排序（Reranking）

Reranking 是 [[rag]] 管道中的精排步骤：先用 [[embedding]] 向量做粗召回（top-k），
再用计算量更大、精度更高的交叉编码器（Cross-Encoder）对候选结果重新打分排序。

## 为什么需要重排序

向量召回是双塔模型，Query 与 Document 独立编码，缺少交互。交叉编码器将 Query 与
每个候选文档拼接后联合打分，能捕捉更细粒度的相关性信号，显著提升精排质量。
这与 [[knowledge-graph]] 图扩展形成互补——图扩展拓宽召回边界，重排序提升排序精度。

## 常用模型

- bge-reranker：中文效果优秀，与 bge-embedding 配套使用
- Cohere Rerank API：商业服务，开箱即用
- [[llm]] 作为重排器：提示 LLM 对文档相关性打分，成本高但效果好

## 在 RAG 管道中的位置

```
用户 Query → [[embedding]] 向量检索 → 粗召回(top-50)
  → Reranking → 精排(top-5) → [[llm]] 生成答案
```

通过 [[evaluation]] 可以量化重排序带来的 MRR、NDCG 提升。
[[semantic-search]] 系统也常在最终呈现前引入轻量重排序以改善用户体验。
