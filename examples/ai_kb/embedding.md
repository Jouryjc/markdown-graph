---
tags: [检索, 向量]
---

# 向量嵌入（Embedding）

Embedding 把文本映射成稠密向量，使语义相近的文本在向量空间中距离更近，
是 [[rag]] 与 [[semantic-search]] 的基础。

## 模型选择

中文场景常用 bge、multilingual-e5 等模型。向量维度与模型绑定，需与 [[vector-db]] 的表结构一致。
本库使用的 [[lancedb]] 支持动态维度配置，方便切换不同 Embedding 模型。

## 与检索的关系

Embedding 的质量直接决定 [[rag]] 的召回上限；下游再叠加 [[reranking]] 进一步排序。
对于多模态场景，[[multimodal]] Embedding 能把图片、音频与文本映射到统一的向量空间，
实现跨模态检索。

## 最佳实践

- 批量编码时关注吞吐量，选择支持 GPU 批推理的模型
- 与 [[ann]] 算法结合时，注意向量归一化对余弦距离的影响
- 定期通过 [[evaluation]] 评估 Embedding 质量，及时发现分布漂移
