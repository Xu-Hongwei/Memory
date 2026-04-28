from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "semantic_retrieval_cn.jsonl"
REPO_SCOPE = "repo:C:/workspace/demo"


POSITIVE_TOPICS: list[dict[str, Any]] = [
    {
        "key": "cn_release",
        "category": "cn_work_release",
        "memory_type": "workflow",
        "scope": REPO_SCOPE,
        "tags": ["release", "ci"],
        "cases": [
            ("上线前我应该先确认哪些检查？", "发布前的固定流程是先跑 ruff，再跑 pytest，最后做一次关键路径冒烟验证。", "发布前检查"),
            ("准备发版时别漏什么？", "发版前要确认测试通过、变更说明更新，并保留可回滚的版本标记。", "发版门禁"),
            ("部署到线上之前的安全动作是什么？", "线上部署前先核对环境变量、数据库迁移状态和回滚步骤。", "线上部署预检"),
            ("推生产前要做什么预检？", "生产预检包括依赖锁定、配置核对、健康检查和最小流量验证。", "生产预检"),
            ("要切正式版本时有哪些门禁？", "正式版本门禁是代码检查、自动化测试、构建产物校验和发布记录同步。", "正式版本门禁"),
            ("上线窗口开始前先看什么？", "上线窗口开始前先确认负责人在线、监控面板打开、告警通道可用。", "上线窗口准备"),
            ("热修复发布前要注意什么？", "热修复发布前只带最小改动，先复现问题，再验证修复用例。", "热修复发布"),
            ("发包前最后一遍检查是什么？", "发包前最后检查版本号、依赖文件、迁移脚本和 README 示例命令。", "发包检查"),
            ("灰度发布需要记住哪条流程？", "灰度发布先小比例放量，观察错误率和延迟，再逐步扩大流量。", "灰度发布"),
            ("发布失败时我应该按什么顺序处理？", "发布失败时先停止放量，再回滚到上一稳定版本，最后整理排错记录。", "发布失败处理"),
        ],
    },
    {
        "key": "cn_debug",
        "category": "cn_work_debug",
        "memory_type": "troubleshooting",
        "scope": REPO_SCOPE,
        "tags": ["debug", "troubleshooting"],
        "cases": [
            ("接口突然 500 了，排查顺序是什么？", "接口报 500 时先看最新日志和请求参数，再复现最小失败用例。", "接口 500 排查"),
            ("测试偶发失败要先看哪里？", "偶发测试失败优先固定随机种子，记录失败输入，再确认是否有时间依赖。", "偶发测试排查"),
            ("本地可以远程不行时怎么查？", "本地正常而远程失败时，先比对环境变量、依赖版本和启动命令。", "远程失败排查"),
            ("用户说功能没生效，我先验证什么？", "功能看似没生效时，先确认请求是否打到当前进程，再看返回数据。", "功能未生效排查"),
            ("性能变慢了，怎么定位？", "性能变慢时先测真实用户路径，再拆分数据库、远程调用和渲染耗时。", "性能排查"),
            ("数据库写入失败先查什么？", "数据库写入失败先看约束错误和事务边界，再检查迁移是否执行。", "数据库写入排查"),
            ("命令运行失败但报错很长怎么办？", "命令报错很长时先截取第一处异常和最终退出码，再复现最短命令。", "命令报错排查"),
            ("远程模型结果不稳定怎么分析？", "远程模型不稳定时先固定输入样本和模型参数，再比较同一批次输出。", "远程模型排查"),
            ("召回结果有噪声时先看什么？", "召回噪声变多时先看 top1 相似度、候选间距和被误召回的记忆类型。", "召回噪声排查"),
            ("修完 bug 后怎么确认不是碰巧好了？", "修复后要用原始失败样本回放，并补一个能复现旧问题的回归测试。", "修复验证"),
        ],
    },
    {
        "key": "cn_docs",
        "category": "cn_work_docs",
        "memory_type": "workflow",
        "scope": REPO_SCOPE,
        "tags": ["docs"],
        "cases": [
            ("代码行为改了，文档要怎么跟？", "代码行为变化后要同步 README、规则说明和验证命令，避免文档漂移。", "文档同步"),
            ("新增命令后说明写在哪里？", "新增 CLI 命令后要在 README 和测试数据说明里补用法示例。", "命令文档"),
            ("规则判断改了，哪份文档最该更新？", "规则判断变化时优先更新 RULE_JUDGMENT.md，再补充项目总览里的摘要。", "规则文档"),
            ("测试集调整以后要写什么说明？", "测试集调整后要说明生成方式、适用范围、重复样本和不适用场景。", "测试集说明"),
            ("远程模型链路变化后文档怎么写？", "远程链路变化后要写清楚 embedding、LLM、fallback 和评估入口。", "远程链路文档"),
            ("API 请求结构变了要同步哪里？", "API 请求结构变化后要同步接口示例、schema 字段和兼容性说明。", "API 文档"),
            ("项目说明里哪些内容不能只凭记忆写？", "项目说明要以当前代码为准，不能只根据旧聊天结论改文档。", "代码对齐文档"),
            ("发现说明和实现不一致时先做什么？", "文档和实现不一致时先列漂移点，再做小范围修正文案。", "文档漂移处理"),
            ("黄金集新增后 README 要补什么？", "黄金集新增后 README 要补规模、生成脚本、测试命令和指标解释。", "黄金集文档"),
            ("写规则说明时应该避免什么？", "规则说明要避免把启发式写成绝对事实，并标出仍需远程模型判断的部分。", "规则说明边界"),
        ],
    },
    {
        "key": "cn_encoding",
        "category": "cn_work_encoding",
        "memory_type": "troubleshooting",
        "scope": "global",
        "tags": ["windows", "encoding"],
        "cases": [
            ("PowerShell 中文乱码先检查什么？", "PowerShell 中文乱码时先检查代码页、输入输出编码和文件实际编码。", "PowerShell 中文乱码"),
            ("JSONL 里中文看起来坏了怎么办？", "JSONL 中文预览乱码时，以 Python 按 UTF-8 读取的结果为准。", "JSONL UTF-8 读取"),
            ("写中文 fixture 时怎么避免编码问题？", "写中文 fixture 时使用 UTF-8，并用 json.dumps 的 ensure_ascii=False 输出。", "中文 fixture 编码"),
            ("控制台显示错字是不是文件坏了？", "控制台乱码不等于文件损坏，要先做 UTF-8 读写回环验证。", "乱码误判"),
            ("Windows 下中文测试失败要排查哪里？", "Windows 中文测试失败时先确认测试读取编码，再看断言里的实际字符串。", "Windows 中文测试"),
            ("README 显示乱码该怎么定位？", "README 显示乱码时先确认编辑器编码，再区分终端渲染问题和文件内容问题。", "README 编码排查"),
            ("跨平台输出中文要注意什么？", "跨平台输出中文时优先显式指定 encoding=\"utf-8\"。", "跨平台中文输出"),
            ("命令行里中文参数异常怎么办？", "命令行中文参数异常时先检查 shell 编码，再用最小命令复现。", "中文参数排查"),
            ("生成脚本写中文要怎么保存？", "包含中文的生成脚本应保存为 UTF-8，并避免依赖终端默认编码。", "中文脚本编码"),
            ("看到一串奇怪符号时怎么判断？", "看到奇怪符号时先用二进制或 Python 读取确认原始字节，再判断是否真乱码。", "乱码确认"),
        ],
    },
    {
        "key": "cn_environment",
        "category": "cn_work_environment",
        "memory_type": "environment_fact",
        "scope": REPO_SCOPE,
        "tags": ["environment"],
        "cases": [
            ("当前项目的数据目录在哪里？", "项目运行时默认把本地 SQLite 数据放在 data 目录下。", "本地数据目录"),
            ("远程配置应该从哪里读？", "远程访问地址和密钥从环境变量读取，不写进 fixture 或文档示例。", "远程配置来源"),
            ("测试命令默认在哪个目录跑？", "项目测试命令默认在仓库根目录执行。", "测试工作目录"),
            ("fixture 文件应该放在哪里？", "黄金测试 fixture 统一放在 tests/fixtures/golden_cases 目录。", "fixture 目录"),
            ("下载的公开参考数据放哪里？", "公开参考数据下载后放在 E:/Xu/data/memory_benchmarks 便于查阅。", "公开数据目录"),
            ("本地数据库文件叫什么？", "本地示例数据库通常使用 data/memory.sqlite。", "示例数据库"),
            ("远程模型名应该怎么管理？", "当前远程 LLM 和 embedding 模型名写入配置默认值，地址和密钥仍来自环境变量。", "远程模型配置"),
            ("脚本生成的数据能不能手工改？", "黄金集应优先改生成脚本再重建 JSONL，避免脚本和数据漂移。", "fixture 生成规则"),
            ("测试用例里的真实密钥怎么处理？", "测试用例不保存真实密钥，只保留脱敏占位或策略描述。", "测试密钥处理"),
            ("项目说明里的路径要怎么写？", "项目说明里的路径要使用当前仓库的真实结构，避免沿用旧路径。", "路径说明"),
        ],
    },
    {
        "key": "cn_git",
        "category": "cn_work_git",
        "memory_type": "workflow",
        "scope": REPO_SCOPE,
        "tags": ["git"],
        "cases": [
            ("改代码前要不要看工作区？", "改代码前先看 git status，确认哪些文件已有用户或历史改动。", "工作区检查"),
            ("看到别人的改动要怎么处理？", "工作区已有无关改动时不要回滚，只在自己的范围内继续。", "已有改动处理"),
            ("提交前怎么避免带入无关文件？", "提交前要按文件核对 diff，只暂存本次任务相关内容。", "提交前核对"),
            ("需要改同一个文件时怎么办？", "同一文件已有改动时先读懂上下文，再把新修改贴合进去。", "同文件协作"),
            ("生成文件很多时怎么检查？", "生成文件很多时先确认生成脚本和输出规模，再用测试验证结构。", "生成文件检查"),
            ("不确定改动来源时默认怎么做？", "不确定改动来源时默认认为是用户已有改动，不主动撤销。", "改动来源判断"),
            ("分支命名有什么约定？", "需要新建分支时默认使用 codex/ 前缀。", "分支命名"),
            ("哪些 git 命令要特别谨慎？", "破坏性 git 命令需要明确请求，不把 reset hard 当成普通修复手段。", "破坏性 git 命令"),
            ("同步文档时如何控制改动范围？", "同步文档时先做漂移审计，再精确修正文案。", "文档改动范围"),
            ("修测试时要不要顺手重构？", "修测试时只改导致失败的逻辑，不顺手做无关重构。", "测试修复范围"),
        ],
    },
    {
        "key": "cn_write_policy",
        "category": "cn_memory_write_policy",
        "memory_type": "tool_rule",
        "scope": "global",
        "tags": ["memory", "write-policy"],
        "cases": [
            ("什么内容值得写成长期记忆？", "长期记忆只写稳定、可复用、非敏感且已经明确的事实或偏好。", "长期记忆写入条件"),
            ("一次性请求要不要进记忆？", "一次性请求和临时状态不写入长期记忆，避免污染。", "一次性请求不写入"),
            ("猜测性的结论可以保存吗？", "未验证猜测默认不写入记忆，最多保留在当前会话上下文。", "猜测不写入"),
            ("用户偏好应该写到哪类记忆？", "稳定协作偏好更适合自带记忆，项目事实更适合 Memory MCP。", "记忆分层"),
            ("排错经验什么时候能沉淀？", "排错经验只有真实发生、解决方式已验证且可复用时才沉淀。", "排错经验写入"),
            ("记忆候选里出现密钥怎么办？", "候选内容出现密钥或 token 时默认不保存原值。", "密钥不写入"),
            ("项目规则能不能写入 MCP？", "项目规则如果长期有用且明确真实，可以写入 Memory MCP。", "项目规则写入"),
            ("记忆越多越好吗？", "记忆系统宁可少记，也不要把低价值信息写进去。", "少记原则"),
            ("写入前要不要查重？", "写入 MCP 前要先搜索相似案例，优先复用或更新已有记录。", "写前查重"),
            ("不确定该不该记时怎么处理？", "不确定是否该写入时默认不写，等证据更充分再处理。", "不确定不写"),
        ],
    },
    {
        "key": "cn_recall_policy",
        "category": "cn_memory_recall_policy",
        "memory_type": "workflow",
        "scope": "global",
        "tags": ["memory", "retrieval"],
        "cases": [
            ("一句话查询时应该怎么召回？", "召回应先按范围过滤，再结合语义相似度和记忆类型排序。", "召回流程"),
            ("召回结果不确定时怎么处理？", "候选相似度太接近时应标记 ambiguous，而不是强行返回。", "召回歧义处理"),
            ("为什么要有 no-match 测试？", "no-match 测试用于验证没有相关记忆时系统能保持沉默。", "no-match 作用"),
            ("召回时只看关键词够不够？", "召回不能只看关键词，还要支持改写、同义表达和上下文意图。", "语义召回必要性"),
            ("低置信记忆召回后要提示什么？", "低置信记忆进入上下文时需要带上置信度和未验证提醒。", "低置信召回提醒"),
            ("过期记忆还能不能用？", "stale 或 archived 记忆默认不进入主动召回结果。", "过期记忆过滤"),
            ("上下文预算不够时怎么裁剪？", "上下文预算不足时优先保留高置信、近任务和短内容记忆。", "上下文预算裁剪"),
            ("召回测试应该看哪些指标？", "召回评估重点看 FN、unexpected、ambiguous 和 top1 命中。", "召回指标"),
            ("远程 LLM 适合放在哪一步？", "远程 LLM 更适合处理候选歧义和边界判断，不必每次都调用。", "选择性 LLM 判断"),
            ("embedding 在召回里负责什么？", "embedding 负责把改写后的语义问题映射到相关记忆候选。", "embedding 作用"),
        ],
    },
    {
        "key": "cn_privacy",
        "category": "cn_privacy_boundary",
        "memory_type": "tool_rule",
        "scope": "global",
        "tags": ["privacy", "security"],
        "cases": [
            ("用户发了身份证号要不要记下来？", "涉及身份证号时只记录处理原则，不保存证件号码原值。", "身份证处理"),
            ("聊天里出现 API token 怎么办？", "出现 API token 时默认脱敏，不把 token 原文写入长期记忆。", "token 处理"),
            ("能不能记住别人的手机号？", "手机号属于个人信息，除非有明确业务必要且已脱敏，否则不写入记忆。", "手机号处理"),
            ("护照号这类信息怎么处理？", "护照号只应触发隐私边界提醒，不应作为可召回事实保存。", "护照号处理"),
            ("用户让我记密码可以吗？", "密码不应进入记忆系统，应该提醒用户使用安全的密码管理方式。", "密码处理"),
            ("日志里有密钥要不要放进测试集？", "测试集不能包含真实密钥，只能使用脱敏占位或安全策略描述。", "测试密钥边界"),
            ("地址信息能不能长期保存？", "详细住址属于敏感个人信息，默认不保存为长期记忆。", "住址处理"),
            ("隐私信息可以做语义召回吗？", "隐私信息召回应返回安全处理规则，而不是返回原始私密值。", "隐私召回边界"),
            ("截图里有账号信息怎么办？", "截图含账号信息时应先脱敏，再决定是否需要记录非敏感事实。", "截图隐私处理"),
            ("敏感内容和项目规则冲突时优先谁？", "敏感内容处理优先于召回便利性，不为了命中率保存原值。", "敏感优先级"),
        ],
    },
    {
        "key": "cn_food",
        "category": "cn_daily_food",
        "memory_type": "user_preference",
        "scope": "global",
        "tags": ["daily", "food"],
        "cases": [
            ("给用户点午饭时要避开什么？", "用户午饭偏好清淡，点餐时尽量避开香菜。", "午饭忌口"),
            ("晚上加班买吃的有什么偏好？", "用户加班时更喜欢热汤面或粥，不太想吃油炸外卖。", "加班餐偏好"),
            ("点咖啡时糖度怎么选？", "用户点咖啡通常选择少糖或无糖。", "咖啡糖度"),
            ("聚餐选餐厅有什么要记住？", "用户聚餐更愿意选安静、能正常聊天的餐厅。", "聚餐餐厅偏好"),
            ("下午茶买什么更合适？", "用户下午茶更偏好水果和无糖茶，不太想要奶油蛋糕。", "下午茶偏好"),
            ("早餐有什么稳定偏好？", "用户早餐通常接受豆浆、鸡蛋和全麦面包。", "早餐偏好"),
            ("点外卖时辣度怎么处理？", "用户一般接受微辣，不喜欢特别重口的辣度。", "辣度偏好"),
            ("喝饮料时要注意什么？", "用户更常选无糖茶或气泡水，少选含糖饮料。", "饮料偏好"),
            ("出差路上买吃的怎么选？", "用户出差路上更喜欢容易携带、味道不重的食物。", "出差食物偏好"),
            ("晚饭太晚时推荐什么？", "晚饭太晚时用户更偏向清淡小份，不想吃太撑。", "晚餐份量偏好"),
        ],
    },
    {
        "key": "cn_schedule",
        "category": "cn_daily_schedule",
        "memory_type": "user_preference",
        "scope": "global",
        "tags": ["daily", "schedule"],
        "cases": [
            ("用户通常什么时候适合处理难题？", "用户上午更适合处理需要深度思考的任务。", "上午深度工作"),
            ("安排会议时要避开什么时间？", "用户不喜欢把会议排在午饭刚结束的时间段。", "会议时间偏好"),
            ("提醒用户复盘最好放什么时候？", "用户更适合在每天收工前做简短复盘。", "复盘时间"),
            ("周一开工先做什么更顺？", "用户周一上午通常先整理待办，再进入具体实现。", "周一开工节奏"),
            ("需要长时间写代码时怎么安排？", "用户写代码时偏好两小时专注块，中间留短休息。", "编码专注块"),
            ("晚上适合安排复杂决策吗？", "用户晚上更适合整理和验证，不适合做太多新决策。", "晚间工作偏好"),
            ("什么时候提醒用户检查测试？", "用户完成一段实现后适合立刻跑一次相关测试。", "测试提醒时机"),
            ("临近截止时间怎么组织任务？", "临近截止时间时用户更需要按风险排序，而不是平均分配时间。", "截止前排序"),
            ("长任务中途需要什么提醒？", "长任务中途用户需要阶段性状态更新，避免忘记当前进展。", "长任务更新偏好"),
            ("周末任务怎么安排更合适？", "用户周末更适合安排轻量维护和资料整理，不适合堆满硬任务。", "周末节奏"),
        ],
    },
    {
        "key": "cn_answer_style",
        "category": "cn_daily_answer_style",
        "memory_type": "user_preference",
        "scope": "global",
        "tags": ["communication"],
        "cases": [
            ("回答记忆系统问题时默认用什么语言？", "讨论记忆系统和项目实现时，默认使用中文回答。", "中文回答偏好"),
            ("解释不确定结论时要怎么说？", "回答时要区分已确认事实、推断和仍需验证的内容。", "事实推断分层"),
            ("用户问实现路线时喜欢什么风格？", "用户喜欢先给可执行路线，再说明取舍和后续演进。", "实现路线表达"),
            ("讲测试结果时应该怎么呈现？", "讲测试结果时要给出数据和命令，不只说感觉变好了。", "测试结果表达"),
            ("解释复杂机制时要不要举例？", "解释复杂机制时用户更容易接受具体例子和对比。", "举例偏好"),
            ("文档说明应该偏长还是偏短？", "框架文档可以详细，但结论要放在前面，方便快速判断。", "文档详略偏好"),
            ("遇到用户觉得乱时怎么回复？", "用户觉得乱时先帮他盘点现状，再给下一步最小动作。", "混乱时回复方式"),
            ("建议下一步时要注意什么？", "建议下一步时要说明它解决哪个具体短板。", "下一步说明"),
            ("代码改动完成后怎么汇报？", "完成改动后要说明改了什么、验证了什么、还剩什么风险。", "改动汇报"),
            ("讨论远程模型时要强调什么？", "讨论远程模型时要分清本地规则、embedding 和 LLM 各自负责的部分。", "远程模型解释"),
        ],
    },
    {
        "key": "cn_shopping",
        "category": "cn_daily_shopping",
        "memory_type": "user_preference",
        "scope": "global",
        "tags": ["daily", "shopping"],
        "cases": [
            ("帮用户选设备时优先什么？", "用户买设备时更看重稳定和耐用，不太追求花哨功能。", "设备购买偏好"),
            ("挑键盘时要记住什么？", "用户更喜欢安静手感的键盘，避免太吵的轴体。", "键盘偏好"),
            ("买显示器时关注哪些点？", "用户买显示器时更关注护眼、色彩稳定和接口数量。", "显示器偏好"),
            ("选背包有什么偏好？", "用户选背包时更喜欢分区清楚、重量轻、外观低调。", "背包偏好"),
            ("推荐软件工具时怎么选？", "用户更偏好可长期维护、数据可导出的工具。", "工具购买偏好"),
            ("买书时应该怎么推荐？", "用户买技术书更看重系统性和可实践案例。", "技术书偏好"),
            ("选择耳机时注意什么？", "用户选耳机更看重佩戴舒适和通话稳定。", "耳机偏好"),
            ("买办公椅时有什么标准？", "用户买办公椅优先考虑腰部支撑和长时间舒适度。", "办公椅偏好"),
            ("选择云服务时偏向什么？", "用户选择云服务时更在意价格透明和迁移成本。", "云服务偏好"),
            ("买收纳用品怎么选？", "用户买收纳用品更喜欢模块化、可重复使用的款式。", "收纳偏好"),
        ],
    },
]


NO_MATCH_TOPICS: list[dict[str, Any]] = [
    {
        "key": "cn_no_match_daily",
        "category": "cn_no_match_daily",
        "queries": [
            "我上次说想买哪款投影仪？",
            "用户最喜欢哪家理发店？",
            "我之前提到过生日想去哪家店吗？",
            "用户家里客厅窗帘是什么颜色？",
            "上次旅行订的是哪班高铁？",
            "我有没有说过常用的洗衣液牌子？",
            "用户小时候最喜欢的动画片是什么？",
            "我上次说要送朋友什么礼物？",
            "用户常去的健身房是哪一家？",
            "我之前有没有说过鞋码？",
        ],
    },
    {
        "key": "cn_no_match_work",
        "category": "cn_no_match_work",
        "queries": [
            "这个项目现在用哪家支付网关？",
            "后台管理员名称是什么？",
            "当前仓库的正式访问域名是哪一个？",
            "项目的 Kubernetes namespace 叫什么？",
            "CI 里用的是哪台自托管 runner？",
            "现在错误监控接的是哪个平台？",
            "生产缓存集群的地址是什么？",
            "项目有没有固定的客服工单系统？",
            "当前服务的 SLA 数字是多少？",
            "仓库默认发布到哪个云区域？",
        ],
    },
]


def memory(
    *,
    alias: str,
    content: str,
    memory_type: str,
    scope: str,
    subject: str,
    tags: list[str],
) -> dict[str, Any]:
    return {
        "alias": alias,
        "content": content,
        "memory_type": memory_type,
        "scope": scope,
        "subject": subject,
        "confidence": "confirmed",
        "source_event_ids": [f"evt_{alias}"],
        "tags": tags,
        "status": "active",
    }


def positive_memory_pool() -> list[dict[str, Any]]:
    pool: list[dict[str, Any]] = []
    for topic in POSITIVE_TOPICS:
        for index, (_query, content, subject) in enumerate(topic["cases"]):
            pool.append(
                {
                    "source_key": topic["key"],
                    "source_index": index,
                    "content": content,
                    "memory_type": topic["memory_type"],
                    "scope": topic["scope"],
                    "subject": subject,
                    "tags": list(topic["tags"]),
                }
            )
    return pool


def distractors(
    *,
    pool: list[dict[str, Any]],
    target_key: str,
    offset: int,
    count: int,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    cursor = offset % len(pool)
    seen_contents: set[str] = set()
    while len(selected) < count:
        item = pool[cursor % len(pool)]
        cursor += 7
        if item["source_key"] == target_key or item["content"] in seen_contents:
            continue
        selected.append(item)
        seen_contents.add(item["content"])
    return selected


def positive_cases() -> list[dict[str, Any]]:
    pool = positive_memory_pool()
    cases: list[dict[str, Any]] = []
    global_index = 0
    for topic in POSITIVE_TOPICS:
        for index, (query, content, subject) in enumerate(topic["cases"]):
            target_alias = f"{topic['key']}_{index:03d}_target"
            selected_distractors = distractors(
                pool=pool,
                target_key=topic["key"],
                offset=global_index * 11 + 3,
                count=2,
            )
            distractor_memories = [
                memory(
                    alias=f"{topic['key']}_{index:03d}_distractor_{letter}",
                    content=item["content"],
                    memory_type=item["memory_type"],
                    scope=item["scope"],
                    subject=item["subject"],
                    tags=item["tags"],
                )
                for letter, item in zip(("a", "b"), selected_distractors)
            ]
            cases.append(
                {
                    "category": topic["category"],
                    "mode": "retrieval",
                    "name": f"{topic['key']}_{index:03d}",
                    "search": {
                        "query": query,
                        "scopes": [REPO_SCOPE, "global"],
                        "limit": 1,
                    },
                    "expected": {
                        "ordered_prefix": [target_alias],
                        "absent_aliases": [
                            item["alias"] for item in distractor_memories
                        ],
                    },
                    "memories": [
                        memory(
                            alias=target_alias,
                            content=content,
                            memory_type=topic["memory_type"],
                            scope=topic["scope"],
                            subject=subject,
                            tags=list(topic["tags"]),
                        ),
                        *distractor_memories,
                    ],
                }
            )
            global_index += 1
    return cases


def no_match_cases() -> list[dict[str, Any]]:
    pool = positive_memory_pool()
    cases: list[dict[str, Any]] = []
    global_index = 0
    for topic in NO_MATCH_TOPICS:
        for index, query in enumerate(topic["queries"]):
            selected_distractors = distractors(
                pool=pool,
                target_key="",
                offset=global_index * 13 + 5,
                count=3,
            )
            memories = [
                memory(
                    alias=f"{topic['key']}_{index:03d}_distractor_{letter}",
                    content=item["content"],
                    memory_type=item["memory_type"],
                    scope=item["scope"],
                    subject=item["subject"],
                    tags=item["tags"],
                )
                for letter, item in zip(("a", "b", "c"), selected_distractors)
            ]
            cases.append(
                {
                    "category": topic["category"],
                    "mode": "retrieval",
                    "name": f"{topic['key']}_{index:03d}",
                    "search": {
                        "query": query,
                        "scopes": [REPO_SCOPE, "global"],
                        "limit": 1,
                    },
                    "expected": {
                        "exact_aliases": [],
                        "absent_aliases": [item["alias"] for item in memories],
                    },
                    "memories": memories,
                }
            )
            global_index += 1
    return cases


def main() -> None:
    cases = [*positive_cases(), *no_match_cases()]
    OUTPUT.write_text(
        "\n".join(json.dumps(case, ensure_ascii=False) for case in cases) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(cases)} cases to {OUTPUT}")


if __name__ == "__main__":
    main()
