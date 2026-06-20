---
tags: [生成, 模型]
---

# 大语言模型（LLM）

大语言模型（LLM）是基于 Transformer 架构、在海量文本上预训练的语言模型。
它是 [[rag]] 系统的生成核心，也是 [[agent]] 的推理引擎。

## 主流模型

- **[[claude]]**：Anthropic 研发，以安全性、长上下文和代码能力著称
- GPT-4o：OpenAI 旗舰模型，多模态能力强
- Gemini：Google 多模态原生模型
- 开源：Llama 3、Qwen 等，支持本地部署

## 与 RAG 的结合

LLM 本身的参数知识有截止时间，通过 [[rag]] 注入外部知识可以弥补这一缺陷。
好的 [[prompt-engineering]] 能引导 LLM 更好地利用 [[rag]] 召回的上下文。
[[guardrails]] 保证 LLM 输出符合安全和业务规范。

## 能力扩展

通过 [[tool-use]] 让 LLM 调用外部工具，突破纯文本生成的边界。
[[fine-tuning]] 可以让通用 LLM 适应特定领域的专业知识和输出格式。
[[multimodal]] LLM 能理解和生成图像、音频等多种模态内容。

## 评估与监控

需要通过 [[evaluation]] 系统持续监控 LLM 在生产环境中的表现，
包括幻觉率、答案准确性和响应延迟等关键指标。
