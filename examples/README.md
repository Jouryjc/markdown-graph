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

## 本地 LLM 实体层（推荐，零外部 key）

默认用本地 Ollama 做实体抽取，无需任何外部凭证：

```bash
pip install fastembed openai          # 本地依赖
ollama serve &                        # 启动 Ollama（若未运行）
ollama pull qwen2.5:3b                # 拉中文模型（约 2GB，仅首次）
MDGRAPH_LLM=local PYTHONPATH=src python examples/run_demo.py
```

可经环境变量覆盖：`MDGRAPH_LLM_BASE_URL`（默认 `http://localhost:11434/v1`）、
`MDGRAPH_LLM_MODEL`（默认 `qwen2.5:3b`）、`MDGRAPH_LLM_API_KEY`（默认 `ollama`）。
任何 OpenAI 兼容端点（LM Studio、vLLM、llama.cpp server）都可用，改 `MDGRAPH_LLM_BASE_URL` 即可。

用 Anthropic Claude（需凭证）则设 `MDGRAPH_LLM=claude` 并在 `.env` 填 Anthropic 凭证。

## 运行

```bash
PYTHONPATH=src python examples/run_demo.py
```

首次运行会联网下载 embedding 模型（约一两百 MB，之后离线），并逐 chunk 调用 Claude 抽取实体。
输出包含：构建报告与 stats、4 个查询的纯向量 vs 双引擎对比（标注图扩展新增的命中）、
命中结果的子图规模、被最多 chunk 提及的跨文档实体。
