# markdown-graph 真实 provider Demo

用本地 fastembed（无需 key）做向量、本地 LLM（默认 Ollama，无需 key）做实体抽取，
在 `examples/ai_kb/` 的中文 AI 工程知识库上构建图谱，并量化对比纯向量 vs 图+向量双引擎检索。
整条链路完全本地、零外部凭证；也可选用 Anthropic Claude 做实体层。

## 准备（本地，零外部 key）

1. 安装本地依赖：
   ```bash
   pip install fastembed openai
   ```
2. 启动本地 LLM（Ollama）并拉中文模型：
   ```bash
   ollama serve &            # 启动 Ollama（若未运行）
   ollama pull qwen2.5:3b    # 拉中文模型（约 2GB，仅首次）
   ```

## 运行

```bash
PYTHONPATH=src python examples/run_demo.py
```

默认用本地 Ollama 做实体抽取（`MDGRAPH_LLM=local`），无需任何外部凭证。
首次运行会联网下载 fastembed embedding 模型（约一两百 MB，之后离线），并逐 chunk 调用本地 LLM 抽取实体。
输出包含：构建报告与 stats、4 个查询的纯向量 vs 双引擎对比（标注图扩展新增的命中）、
命中结果的子图规模、被最多 chunk 提及的跨文档实体。

可经环境变量覆盖本地端点/模型：`MDGRAPH_LLM_BASE_URL`（默认 `http://localhost:11434/v1`）、
`MDGRAPH_LLM_MODEL`（默认 `qwen2.5:3b`）、`MDGRAPH_LLM_API_KEY`（默认 `ollama`）。
任何 OpenAI 兼容端点（LM Studio、vLLM、llama.cpp server）都可用，改 `MDGRAPH_LLM_BASE_URL` 即可。

## 可选：用 Anthropic Claude 做实体层

设 `MDGRAPH_LLM=claude`，并在项目根 `.env`（已被 .gitignore 忽略，不会提交）填凭证：

```
ANTHROPIC_AUTH_TOKEN=<你的中转 token>
ANTHROPIC_BASE_URL=<你的中转 base url>
# ANTHROPIC_MODEL 留空即用 claude-sonnet-4-6
```

官方直连则改填 `ANTHROPIC_API_KEY`、上面两项留空。然后：

```bash
MDGRAPH_LLM=claude PYTHONPATH=src python examples/run_demo.py
```
