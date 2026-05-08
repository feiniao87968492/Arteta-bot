# 阿尔特塔机器人人格优化方案

## 问题诊断

1. **过度强调比赛比分**：`fetch_global_intel()` 每次回复都注入赛果 → 无论聊什么都带比分
2. **"端水"倾向**：prompt 强调"积极心态""正面回答"，缺乏观点鲜明的指令
3. **重复老故事**：灯泡演讲/大脑心脏演讲等写死在 prompt → 反复出现

## 解决方案：三大子系统

### 子系统 A：Function Calling

将被动数据注入改为主动调用。DeepSeek 支持 tool use，注册 5 个工具函数：

| 函数 | 触发场景 | 数据源 |
|------|---------|--------|
| `get_arsenal_result()` | 问赛果/比分/赢没赢 | football-data.org（已有） |
| `get_pl_table()` | 问排名/积分榜 | football-data.org（已有） |
| `get_arsenal_injuries()` | 问伤病/谁伤了 | DuckDuckGo 搜索（英文） |
| `search_news(q)` | 问转会/传闻/新闻 | DuckDuckGo 搜索（英文） |
| `query_knowledge(topic)` | 需要战术/故事/理念时 | 本地知识库文件 |

调用流程：
```
用户消息 → 简化 Base Prompt（无比赛/故事硬注入）
        → 调 DeepSeek（含 tools 定义）
        → LLM 决定是否调用 tool
        → tool 返回结果给 LLM
        → LLM 整合生成最终回复
```

### 子系统 B：本地知识库

目录结构：
```
knowledge_base/
├── documentary/
│   ├── 01-locker-room-speeches.md
│   └── 02-backstage-stories.md
├── tactics/
│   ├── 01-inverted-fullback.md
│   ├── 02-2-3-5-attack.md
│   └── 03-high-press.md
├── press/
│   ├── 01-classic-quotes.md
│   └── 02-post-match.md
├── philosophy/
│   └── 01-trust-the-process.md
└── glossary.md
```

检索：关键词文件名/章节匹配，返回匹配文件内容摘要。LLM 通过 `query_knowledge(topic)` 按需查询。

### 子系统 C：Prompt 重构

- 移出三个固定故事到知识库
- 移出比赛数据（Function Calling 按需取）
- 取消 6 级硬编码回复纪律表
- 强化"观点鲜明"指令
- 放松排版纪律（允许分段表达态度）
- 取消`严禁列表`等过度死板的格式约束

## 实现优先级

1. **重写 prompt + 添加 function calling**（改动最深，核心收益最大）
2. **搭建知识库 + 收集资料**（耗时在收集，结构简单）
3. **修改 process_chat() 集成**（串联子系统 A+B+C）
