---
tags: [Agent, 基础设施]
---

# 工具调用（Tool Use）

Tool Use 是让 [[llm]] 调用外部函数、API 和服务的能力，是构建 [[agent]] 的关键机制。
通过 Tool Use，模型从「生成文本」扩展为「执行操作」，实现真正意义上的 AI 自动化。

## 工作原理

LLM 收到工具定义（JSON Schema 描述的函数签名），在需要时生成结构化的工具调用请求；
宿主程序执行工具并将结果返回给 LLM；LLM 根据结果继续推理或生成最终答案。

[[claude]] 的 Tool Use API 支持并行工具调用（Parallel Tool Calls），
可在一次推理中同时触发多个工具，显著提升 [[agent]] 的执行效率。

## 常见工具类型

- **知识检索**：[[rag]] 查询、[[semantic-search]]、[[knowledge-graph]] 图遍历
- **代码执行**：Python sandbox，让 LLM 直接验证计算结果
- **外部 API**：天气、日历、数据库查询
- **文件操作**：读写文档，配合 [[chunking]] 处理长文本

## 设计原则

好的工具定义需要清晰的描述和参数文档，[[prompt-engineering]] 中的工具描述质量
直接影响 LLM 的工具选择准确性。[[evaluation]] 需覆盖工具调用的准确率和错误处理。

## 安全考量

Tool Use 扩大了模型的行动边界，[[guardrails]] 需要在工具层面加入权限控制和输入校验，
防止提示注入攻击通过工具造成实际危害。
