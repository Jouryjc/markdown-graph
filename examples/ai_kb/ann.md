---
tags: [向量, 基础设施]
---

# 近似最近邻（ANN）

近似最近邻（Approximate Nearest Neighbor，ANN）算法是 [[vector-db]] 的核心，
用于在海量高维向量中快速找到与查询向量最相近的 K 个结果。

## 精确 vs 近似

精确最近邻（KNN）需要遍历全量向量，时间复杂度 O(N×D)，百万级数据不可接受。
ANN 通过构建预计算索引，在牺牲极少召回率的前提下，将查询速度提升数百倍。

## 主流算法

### HNSW（分层可导航小世界图）
最流行的 ANN 算法，基于图结构，支持动态插入，召回率与延迟均衡。
[[lancedb]] 默认使用 IVF_PQ 或 HNSW 作为向量索引。

### IVF（倒排文件索引）
先聚类（K-Means），查询时只搜索最近的若干簇。适合超大规模静态数据集。
与 PQ（乘积量化）结合（IVF_PQ）可大幅压缩内存占用。

### ScaNN、FAISS
Google 和 Meta 开源的高性能 ANN 库，适合自建向量检索基础设施。

## 参数调优

ANN 的核心参数是召回率（Recall）与延迟的权衡：
- 增大 `ef_search`（HNSW）或 `nprobe`（IVF）提升召回，但增加延迟
- 通过 [[evaluation]] 测试不同参数下的 Recall@K，找到业务可接受的平衡点

## 与上层系统的关系

[[embedding]] 产生的向量写入 [[vector-db]] 时触发索引构建；
[[semantic-search]] 查询时调用 ANN 算法；[[rag]] 和 [[knowledge-graph]] 均依赖 ANN 的检索效率。
