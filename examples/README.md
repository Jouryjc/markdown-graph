# markdown-graph 真实 provider Demo

用本地 fastembed（无需 key）做向量、Anthropic Claude（经中转端点）做实体抽取，
在 `examples/ai_kb/` 的中文 AI 工程知识库上构建图谱，并量化对比纯向量 vs 图+向量双引擎检索。

## 准备

1. 安装本地 embedding 依赖：
   ```bash
   pip install fastembed
   ```
2. 在项目根 `.env` 填写凭证（已被 .gitignore 忽略，不会提交）：
   ```
   ANTHROPIC_AUTH_TOKEN=<你的中转 token>
   ANTHROPIC_BASE_URL=<你的中转 base url>
   # ANTHROPIC_MODEL 留空即用 claude-sonnet-4-6
   ```
   若用官方直连：改填 `ANTHROPIC_API_KEY`，上面两项留空。

## 运行

```bash
PYTHONPATH=src python examples/run_demo.py
```

首次运行会联网下载 embedding 模型（约一两百 MB，之后离线），并逐 chunk 调用 Claude 抽取实体。
输出包含：构建报告与 stats、4 个查询的纯向量 vs 双引擎对比（标注图扩展新增的命中）、
命中结果的子图规模、被最多 chunk 提及的跨文档实体。
