# Public Memory Datasets

外部公开数据集只用于查阅、抽样、改写和设计测试思路，原始数据不进入本仓库的普通回归测试。仓库内稳定回归仍以 `tests/fixtures/golden_cases/` 为准；如果要利用公开数据集，应生成本项目自己的合成 fixture。

## 本地位置

当前外部数据集根目录：

```text
E:\Xu\data\memory_benchmarks
```

当前已下载：

| 本地目录 | 来源 | 用途 |
| --- | --- | --- |
| `longmemeval` | Hugging Face `MemoryAsModality/LongMemEval` | 长期聊天记忆 QA，适合参考多会话问答、时间线、信息更新和拒答样式 |
| `locomo_dialogues` | Hugging Face `Aman279/Locomo` | LoCoMo 长对话，适合参考跨 session 日常对话和事件沉淀 |
| `locomo_benchmark_queries` | Hugging Face `Nithish2410/benchmark-locomo` | LoCoMo 风格 query/target 行，适合参考召回问题写法 |
| `naturalconv_zh` | Hugging Face `xywang1/NaturalConv` | 中文多轮话题驱动对话，适合参考自然口语、话题转移和含糊偏好表达 |
| `personal_dialog_zh` | Hugging Face `silver/personal_dialog` | 中文多轮对话和说话人画像，适合参考兴趣、地区、身份、persona 和社交闲聊表达 |
| `RealMemBench` | GitHub `AvatarMemory/RealMemBench` | 项目型长期记忆 benchmark，适合参考项目目标、persona、长期任务和动态记忆 |

下载结果记录在：

```text
E:\Xu\data\memory_benchmarks\manifest.json
```

RealMemBench 的 GitHub 仓库包含一个 Windows 非法文件名 `.env.example `。下载脚本使用 GitHub zip 包解压，并跳过这个文件；manifest 会记录 `skipped_windows_invalid_paths`。

当前派生盘点报告：

```text
E:\Xu\data\memory_benchmarks\derived\reference_corpus_inventory.json
E:\Xu\data\memory_benchmarks\derived\reference_corpus_inventory.md
```

盘点结果摘要：

```text
LongMemEval: 500 QA rows
LoCoMo: 35 dialogue rows
RealMemBench: 10 个 256k dialogue 文件
NaturalConv: 19,919 dialogues / 400,562 utterances
PersonalDialog: 5,438,165 train rows / 535.933 MB compressed
```

## 如何重新下载

```powershell
python tools\download_public_memory_datasets.py --output-root E:\Xu\data\memory_benchmarks
```

如果需要覆盖已有目录：

```powershell
python tools\download_public_memory_datasets.py --output-root E:\Xu\data\memory_benchmarks --force
```

脚本依赖：

- `huggingface_hub`
- `requests`
- `git` 只用于后续可能增加的 Git repo 下载；当前 RealMemBench 使用 zip 包方式下载

生成本地盘点报告：

```powershell
python tools\summarize_public_memory_datasets.py --root E:\Xu\data\memory_benchmarks
```

## 如何用于本项目

不要直接复制公开数据集到黄金测试集。推荐流程：

1. 从公开数据集中抽取场景类型，例如“用户偏好变化”“跨 session 事件追问”“项目目标更新”“无答案拒答”。
2. 改写成我们自己的合成样本，避免引入外部数据许可和格式不稳定问题。
3. 映射到本项目固定结构，例如：
   - `write_policy.jsonl`: 该不该写入、写成什么类型。
   - `semantic_retrieval_v2.jsonl`: query 能不能召回正确记忆。
   - `retrieval_context.jsonl`: 多条记忆如何进入上下文。
   - `consolidation.jsonl`: 新旧事实如何合并、冲突或更新。
4. 生成后跑：

```powershell
python tests\fixtures\golden_cases\audit_golden_cases.py --strict
python tests\fixtures\golden_cases\audit_golden_cases.py --show-template-groups 5
python -m pytest tests\test_golden_write_policy.py tests\test_remote_adapters.py -q
```

## 已落地的合成 fixture

当前已经新增：

```text
tests/fixtures/golden_cases/generate_semantic_retrieval_public.py
tests/fixtures/golden_cases/semantic_retrieval_public.jsonl
```

这组样本不是复制公开数据集原文，而是仿照公开 benchmark 的任务形态重新写成 300 条本项目可控样本：

- LongMemEval-like：单轮用户事实、单轮助手建议、长期偏好、多 session 变化、时间线推理、知识更新和无答案拒答。
- LoCoMo-like：日常事件、人物关系、稳定偏好等长对话沉淀信息。
- RealMemBench-like：项目目标、项目进展、项目决策、约束规则和项目无答案拒答。

固定结构：

```text
300 cases
15 categories
3 benchmark_family: longmemeval / locomo / realmem
40 no-match cases
40 update/stale cases
每条 case 临时种入 3 条 memory，search.limit = 1
```

重新生成和评测：

```powershell
python tests\fixtures\golden_cases\generate_semantic_retrieval_public.py
python tests\fixtures\golden_cases\audit_golden_cases.py --strict
memoryctl --db data\memory.sqlite remote evaluate-retrieval --fixture tests\fixtures\golden_cases\semantic_retrieval_public.jsonl --json
memoryctl --db data\memory.sqlite remote evaluate-retrieval --fixture tests\fixtures\golden_cases\semantic_retrieval_public.jsonl --embedding-cache data\eval_embedding_cache.jsonl --report-path data\retrieval_report_public.json --case-concurrency 4 --judge-group-size 4 --judge-concurrency 2 --json
```

真实远程跑 public-inspired 样本时建议固定使用 `--embedding-cache`，避免重复请求同一批 embedding；`--report-path` 用来保留完整结果，后续调整阈值、模型或样本生成脚本时可以直接对比报告；`--case-concurrency` 可把 embedding 预取和 case 评估并发化，建议先从 3 或 4 开始。case 阶段只做本地召回和 guard；DeepSeek recall judge 后置调度，可以单独调并发和打包大小：`--judge-group-size 1 --judge-concurrency 4` 并发发送多个单条请求；`--judge-group-size 2|4 --judge-concurrency 2` 对比更少请求数下的速度和准确率。

## 优先仿照方向

- LongMemEval / LoCoMo：补充长期聊天记忆的“问法变化”“时间顺序”“用户偏好变化”“不知道时拒答”。
- RealMemBench：补充项目型记忆的“长期目标”“任务进展”“项目规则”“动态事实更新”“跨 session 工作流”。
- NaturalConv：补充中文日常多轮对话中的自然话题切换、含糊反馈、追问和非记忆闲聊。
- PersonalDialog：补充中文 persona/兴趣/地区/身份表达，并专门制造“看起来像偏好但不应写入”的社交噪声。
- BEIR / MTEB 暂时不下载全量。它们更适合做 embedding 检索通用评测，不是完整记忆系统测试。
