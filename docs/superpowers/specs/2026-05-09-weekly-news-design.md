# 阿森纳周报功能设计

## 概述

机器人每周一自动爬取阿森纳 + 英超新闻，生成阿尔特塔风格周报，同时注入知识库和发布到群。

## 架构

### 新增文件
- `plugins/arteta_weekly.py` — 周报功能独立插件

### 核心流程

```
每周一 09:00 (APScheduler cron 触发)
  ↓
fetch_arsenal_news() — 抓取 BBC + Sky Sports 新闻列表
  ↓
去重合并 → Top 5 条
  ↓
fetch_article_content() — 打开正文页获取内容
  ↓
generate_weekly_report() — DeepSeek 生成阿尔特塔风格周报
  ↓
同时做两件事：
  ├── save_to_knowledge_base() → knowledge_base/weekly-news.md
  └── publish_to_groups() → 渲染图片 → 发到所有群
```

### 不修改的文件
- `plugins/arteta_knowledge.py` — 无需修改，`rglob("*.md")` 自动加载新文件
- `plugins/arteta_chat.py` — 无需修改

## 模块详情

### 1. 新闻抓取 (`fetch_arsenal_news`)

**数据源：**

| 来源 | URL | 提取方式 |
|------|-----|---------|
| BBC Sport Arsenal | `bbc.com/sport/football/teams/arsenal` | `httpx` + 正则提取文章标题和链接 |
| Sky Sports Arsenal | `skysports.com/arsenal` | `httpx` + 正则从 `<h3>` 提取新闻标题 |

**流程：**
1. 异步并发请求两个源（`asyncio.gather`）
2. 从 HTML 提取文章标题 + URL
3. 过滤阿森纳/英超相关新闻
4. 去重合并（标题相似度判断）
5. 按相关度排序，取 Top 5

**错误处理：**
- 单个源失败：记录警告，继续使用另一个源
- 两个源都失败：记录错误，跳过本次周报
- 提取结果为空：跳过

**请求配置：**
```python
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml",
}
timeout = 15.0
```

### 2. 正文抓取 (`fetch_article_content`)

对 Top 5 新闻分别请求正文页，提取 `<p>` 标签中的文本内容。
- 每篇最多取 500 字
- 如果正文抓取失败，使用标题 + 简短摘要

### 3. LLM 周报生成 (`generate_weekly_report`)

**调用 DeepSeek API：**
- 模型：`deepseek-v4-flash`（与现有 Daily Summary 一致）
- 单次调用，`max_tokens=1500`
- API Key 复用 `DEEPSEEK_API_KEY` 配置

**Prompt：**
```
你是阿尔特塔，阿森纳主教练。请根据以下本周足球新闻，
生成一份给球员看的更衣室周报。

要求：
1. 每条新闻用 [red]（阿森纳相关）或 [blue]（其他）标记
2. 语气激情、直接、像在更衣室里讲话
3. 对阿森纳表现给出你的真实评价
4. 对争冠对手的动向也要有所点评
5. 首行用 "本周要点" 作为标题
6. 每条新闻一行，简洁有力

本周新闻：
{articles}
```

**输出格式示例：**
```
本周要点

[red]阿森纳 3-0 西汉姆：Saka 梅开二度，统治级表现！球队在正确的轨道上！[/red]

[blue]曼城 1-1 埃弗顿：争冠对手掉链子了，这就是我们等待的机会！[/blue]

[red]欧冠半决赛抽签出炉：面对马竞，我们需要拿出最好的状态！[/red]
```

### 4. 知识库注入 (`save_to_knowledge_base`)

将 LLM 生成的周报（纯 markdown）写入 `knowledge_base/weekly-news.md`。

**格式：**
```markdown
# 阿森纳周报 (2026年第19周)

> 生成时间：2026-05-11 09:00

## 本周新闻
{LLM 生成内容}
```

**覆盖策略：** 直接覆盖旧文件，保留最新一份周报。历史周报可通过总结旧期的方式归档，不在本设计范围内。

**加载：** `arteta_knowledge.py` 的 `_load_all_files()` 自动发现并缓存新文件，机器人查询时自动命中。

### 5. 发布 (`publish_to_groups`)

1. 取 LLM 生成的周报内容
2. 添加头部：
   ```
   [red]阿尔特塔的更衣室周报[/red]
   [blue]2026年5月11日 星期一[/blue]
   ```
3. 调用 `text_to_tactical_board()` 渲染为图片
4. 调用 `bot.call_api("send_group_msg", ...)` 发送到所有群

### 6. 定时任务

使用 `nonebot_plugin_apscheduler`（已在 `arteta_daily.py` 中使用）：

```python
from nonebot_plugin_apscheduler import scheduler

@scheduler.scheduled_job(
    "cron",
    day_of_week="mon",
    hour=9,
    minute=0,
    id="weekly_news",
    misfire_grace_time=300,
)
async def weekly_news_job():
    ...
```

- 每周一 09:00 执行
- `misfire_grace_time=300` 防止错过触发
- 与 `daily_summary`（每天 22:30）互补

## 错误处理策略

| 场景 | 行为 |
|------|------|
| 新闻源全部不可用 | 记录日志，跳过本次周报 |
| 部分新闻源不可用 | 使用可用源的数据继续 |
| LLM API 调用失败 | 重试 1 次，间隔 3 秒，仍失败则跳过 |
| 知识库文件写入失败 | 记录日志，不影响群发 |
| 群发失败 | 单个群失败不影响其他群 |

## 配置

复用现有配置（无需新增环境变量）：
- `DEEPSEEK_API_KEY` — LLM 调用
- 新闻源 URL 硬编码在代码中

## 日志

所有操作统一以 `[WeeklyNews]` 前缀记录日志，便于追踪：
- `[WeeklyNews] 开始周报生成`
- `[WeeklyNews] BBC 源抓取到 5 条新闻`
- `[WeeklyNews] Sky 源抓取到 3 条新闻`
- `[WeeklyNews] 合并后 6 条，选取 Top 5`
- `[WeeklyNews] LLM 周报生成成功 (384 tokens)`
- `[WeeklyNews] 已更新知识库 knowledge_base/weekly-news.md`
- `[WeeklyNews] 已发送群 {group_id}`

## 文件结构

```
plugins/arteta_weekly.py    # 新增：周报插件
knowledge_base/weekly-news.md  # 新增：周报知识库文件（运行时生成）
```

## 部署

1. 上传 `plugins/arteta_weekly.py` 到服务器 `/opt/arteta_bot/plugins/`
2. `supervisorctl restart arteta_bot`
3. 验证：检查日志中 `Succeeded to load plugin "arteta_weekly"`
4. 首次手动触发测试：可通过临时添加手动命令触发
