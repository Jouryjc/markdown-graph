---
tags: [基础设施, 向量]
---

# LanceDB

LanceDB 是基于 Lance 列式存储格式构建的嵌入式向量数据库，无需独立服务进程即可运行，
特别适合本地开发、边缘部署和数据密集型 Python 应用。本项目的 [[vector-db]] 后端即采用 LanceDB。

## 核心特性

- **零依赖嵌入式运行**：与 SQLite 类似，直接在 Python 进程内运行，无需 Docker 或远程服务
- **Lance 列式格式**：针对随机访问和向量搜索优化，读取效率远超 Parquet
- **多模态支持**：原生支持存储向量、文本、图像字节、结构化列，方便 [[multimodal]] 场景
- **版本化存储**：支持数据版本管理，方便回滚

## 与本项目的集成

本项目用 LanceDB 存储由 [[embedding]] 模型生成的文档块向量。索引时，
[[chunking]] 切分的文本块经 [[embedding]] 编码后批量写入 LanceDB 表；
查询时，[[semantic-search]] 通过 LanceDB 的 ANN 接口实现 [[ann]] 向量检索。

## 索引支持

LanceDB 支持 IVF_PQ 和 HNSW 索引，默认对小数据集做全量扫描，数据量超阈值后自动建议建索引。
与 [[rag]] 结合时，通常在万级以上向量时才需要显式建索引。

## 存储布局

```
.mdgraph/
  vectors/      ← LanceDB 数据目录
    chunks.lance
  graph.db      ← SQLite 图结构
```

[[evaluation]] 测试可以通过临时 LanceDB 目录（tmp_path）隔离，避免测试污染生产数据。
