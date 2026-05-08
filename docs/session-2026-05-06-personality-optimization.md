# Session: 2026-05-06 人格优化（Function Calling + 知识库 + Prompt 重构）

## 目标
解决机器人三个问题：过度强调比赛、端水含糊、反复讲老故事。

## 方案
三大子系统同步推进：

### 子系统 A：Function Calling
将被动数据注入改为 LLM 主动按需获取，减少无关的比赛信息，增加实时数据精准度。

### 子系统 B：本地知识库
收集阿尔特塔相关英文资料（纪录片、战术、发布会），LLM 按需查询。

### 子系统 C：Prompt 重写
去除固定故事和 6 级表格，增加观点鲜明指令，允许灵活表达。

## 已完成的修改

### 新增文件

| 文件 | 行数 | 作用 |
|------|------|------|
| `plugins/arteta_tools.py` | ~300 | Function Calling 工具模块，5 个 DeepSeek tool 定义 + 执行循环 |
| `plugins/arteta_knowledge.py` | ~110 | 本地知识库引擎，关键词检索 + 评分匹配 |
| `knowledge_base/glossary.md` | 27 行 | 战术术语表（7 个核心概念） |
| `knowledge_base/documentary/01-locker-room-speeches.md` | 25 行 | 更衣室经典演讲（灯泡、大脑心脏、标准训话） |
| `knowledge_base/tactics/01-inverted-fullback.md` | 102 行 | 内收型边后卫（已 web-access 丰富） |
| `knowledge_base/tactics/02-high-press.md` | 143 行 | 高位逼抢系统（web-access 收集） |
| `knowledge_base/tactics/03-attacking-patterns.md` | 251 行 | 进攻模式（2-3-5、肋部进攻等） |
| `knowledge_base/press/01-classic-quotes.md` | 18 行 | 经典发布会语录 |
| `knowledge_base/philosophy/01-trust-the-process.md` | 15 行 | 阿尔特塔足球哲学 |
| `docs/superpowers/specs/2026-05-06-arteta-personality-optimization-design.md` | — | 设计文档 |
| `docs/superpowers/plans/2026-05-06-arteta-personality-optimization.md` | — | 实施计划 |

### 修改文件：`plugins/arteta_chat.py`

1. **新增 import**：从 `arteta_tools` 导入 `register_config` 和 `run_tool_loop`
2. **配置注入**：`init_db_safely()` 后调用 `register_tools_config()`
3. **process_chat() 改造**：
   - 移除 `fetch_global_intel()` 被动数据注入
   - 移除 `intel_section` 构建（赛果/积分/赛程不再硬塞进 prompt）
   - 移除 6 级回复纪律表格（传奇队长/核心首发/一线队/青训生/预备队/看台内鬼）
   - 替换为简化 `base_prompt` + `run_tool_loop(messages)` 函数调用循环
   - 渲染逻辑保持不变（html_to_image / text_to_tactical_board）
4. **ARTETA_PROMPT 完全重写**：
   - 移除了三个固定故事（灯泡/大脑心脏/标准训话 → 移入知识库）
   - 移除了"绝对排版纪律"（严禁列表/严禁小标题等）
   - 增加了"观点鲜明"指令
   - 增加了"不要反复讲同一个故事"约束
   - 增加了 get_football_knowledge 工具引用指引
   - 保留正面回答、引用消息分析、信任度标注、数学公式/代码渲染等核心纪律

### 5 个 Tool 定义（注册给 DeepSeek）

| Tool 名称 | 功能 | 数据源 |
|-----------|------|--------|
| `get_arsenal_result` | 获取阿森纳最近 3 场赛果 | football-data.org API |
| `get_pl_table` | 获取英超积分榜（前 4 + 我厂 + 降级区） | football-data.org API |
| `get_arsenal_injuries` | 查询伤病信息 | DuckDuckGo（英文搜索） |
| `search_news(q)` | 搜索足球新闻/转会传闻 | DuckDuckGo（英文搜索词） |
| `get_football_knowledge(topic)` | 查询本地战术知识库 | 本地 .md 文件关键词检索 |

### 待完成的

- [ ] **Task 5**：web-access 收集纪录片资料（后台 agent 运行中）
- [ ] **Task 5**：web-access 收集发布会语录和哲学内容（后台 agent 运行中）
- [ ] **Task 6**：部署到服务器（SCP + supervisorctl restart）

## 关键技术决策

1. **使用 DeepSeek 原生 Function Calling**：`tool_choice: "auto"`，LLM 自主决定是否调用工具
2. **最多 5 轮 tool call 循环**：防止无限循环
3. **知识库关键词匹配（非向量检索）**：文件量小 + 中文关键词准确度高，向量检索属于过度工程
4. **搜索词要求英文**：工具描述的 `description` 字段写明"搜索词请用英文"让 LLM 自行翻译
5. **`tactical_cache` 从 arteta_tools.py 清理**：死代码，已移除
6. **`fetch_global_intel()` 保留**：仍被 `handle_refresh` 命令使用，只从 `process_chat()` 中移除调用
