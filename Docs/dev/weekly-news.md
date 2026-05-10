# 阿森纳周报模块 — 技术文档

## 1. 背景

阿森纳周报（arteta_weekly）是机器人的核心功能模块之一。该模块每周一自动爬取多家体育媒体的阿森纳相关新闻，调用 DeepSeek 大语言模型生成阿尔特塔（Arteta）更衣室讲话风格的周报，将周报写入知识库供后续检索使用，并渲染为图片发布到所有 QQ 群。

功能入口位于 `plugins/arteta_weekly.py`，约 440 行。通过 NoneBot 的 `on_command` 和 `APScheduler` 实现手动触发与定时任务。

---

## 2. 爬虫架构

模块从三个新闻源并发抓取，去重合并后选取 Top 8 作为 LLM 输入材料。

### 2.1 fetch_bbc_news()

- 目标 URL: `https://www.bbc.com/sport/football/teams/arsenal`
- 方法: 正则提取 `<a>` 标签中的 href 和文本，匹配 BBC 域内链接和 `/sport/football/...` 相对路径
- 去重逻辑: 内部 `seen` 集合，标题长度 > 15 字符且不重复才加入
- 超时设置: 15 秒
- 异常处理: 捕获通用 Exception，打日志后返回空列表，不会阻断流程
- 注意: BBC 经常返回非 200 状态码或触发 ConnectTimeout，属于已知问题

### 2.2 fetch_sky_news()

- 目标 URL: `https://www.skysports.com/arsenal`
- 方法: 先提取 `<h3>` 块，再从块内匹配 `<a>` 标签，提取 `/football/news/...` 链接
- 当前状态: 工作正常，是最稳定的新闻源

### 2.3 fetch_guardian_news()

- 目标 URL: `https://www.theguardian.com/football/arsenal`
- 方法: 正则匹配 `/football/[0-9]+/...` 路径模式的链接
- 角色: BBC 的备份源。当 BBC 失效时，Guardian 能补充大量新闻
- 当前状态: 工作正常

### 2.4 fetch_article_content(url)

- 功能: 打开单篇新闻正文页，提取 `<p>` 标签纯文本
- 上限: 每篇文章最多提取 500 字符（超过即截断）
- 过滤: 丢弃长度 <= 30 字符的段落（通常是导航文案或杂项）
- 用途: 为 LLM 提供每篇新闻的摘要内容，帮助生成带细节的点评

### 2.5 fetch_arsenal_news() — 主入口

- 调用 `asyncio.gather` 并发执行三个源的抓取
- `return_exceptions=True`，任一源异常不会影响其他源
- 去重: 按标题前 20 字符作为 key 去重
- 排序: 按标题长度降序（长标题通常信息更丰富）
- 截取: 最终取前 8 条

---

## 3. LLM 生成

### generate_weekly_report(articles)

- 模型: `deepseek-v4-flash`
- API: `https://api.deepseek.com/v1/chat/completions`
- 参数: temperature 0.7, max_tokens 2500
- 重试: 最多 2 次，首次失败后 sleep 3 秒再试
- 系统提示词 (`WEEKLY_PROMPT`):
  - 要求以阿尔特塔（阿森纳主教练）的口吻撰写更衣室周报
  - 阿森纳相关新闻用 `[red]` 标记，其他用 `[blue]` 标记
  - 每条新闻不少于 50 字点评，语气激情、直接
  - 至少 3 段，首行为 "本周要点" 标题

### _clean_color_tags(text)

- 后处理函数，用于修复 LLM 输出中颜色标签跨行或不闭合的问题
- 逐行检查: 如果一行内包含 `[red]`/`[/red]` 或 `[blue]`/`[/blue]`，必须成对且开标签在闭标签之前，否则整行去除所有颜色标签
- 这个函数的存在是因为 LLM 有时会生成跨行的 `[red]...[/red]` 或漏写闭标签，导致后续图片渲染出错

---

## 4. 知识库注入

### save_to_knowledge_base(report)

- 写入路径: `knowledge_base/weekly-news.md`
- 内容格式:
  ```
  # 阿森纳周报 (2026年第19周)
  > 生成时间：2026-05-11 09:00
  ## 本周新闻
  [LLM 生成的报告正文]
  ```
- ISO 周数由 `date.today().isocalendar()[1]` 计算
- 自动创建 `knowledge_base/` 目录（如果不存在）

### 缓存失效

写入完成后立即调用 `plugins.arteta_knowledge.clear_cache()`，使知识库查询模块的缓存失效，确保后续查询能读到最新的周报内容。

---

## 5. 发布流程

### publish_to_groups(report, group_ids=None)

发布流程分为三步:

1. **构建消息文本**: 拼接带颜色标签的头信息 + 报告正文
2. **确定目标群**:
   - `group_ids` 不为 None: 只发送到指定群列表（手动触发场景）
   - `group_ids` 为 None: 遍历所有 bot 实例，调用 `get_group_list` 获取全部群（定时任务场景）
3. **渲染与发送**:
   - 调用 `text_to_tactical_board(final_text)` 渲染为图片（来自 `plugins/arteta_render`）
   - 遍历所有目标群，调用 `send_group_msg` 发送图片
   - **降级方案**: 如果图片渲染失败（如颜色标签解析异常），自动降级为纯文本发送，去除 `[red]`、`[blue]`、`*` 等标记，截取前 2000 字符

---

## 6. 定时任务

### weekly_news_job()

- 调度器: NoneBot 插件 `nonebot_plugin_apscheduler`
- 表达式: `cron, day_of_week="mon", hour=9, minute=0`
- 宽容时间: `misfire_grace_time=300` 秒（任务延迟 5 分钟内仍执行）
- 开关: 由配置项 `weekly_news_enabled` 控制（默认 true）
- 流程:
  1. 调用 `_generate_and_save()` — 抓取新闻 -> 生成周报 -> 写入知识库 -> 清除缓存
  2. 如果生成成功，调用 `publish_to_groups(report)` 发送到所有群

### _generate_and_save()

内部辅助函数，封装了"获取新闻 → 生成周报 → 保存知识库 → 清除缓存"的完整链路。任一环节失败（无新闻、LLM 返回空）则返回 None，调用方据此决定是否继续发送。

---

## 7. 手动触发

### 命令: `/周报` / `/weekly` / `/weeklynews`

- 注册方式: `on_command("周报", aliases={"weekly", "weeklynews"})`
- 权限: 仅管理员可用（QQ: 2648955710）
- 非管理员回复: "只有教练组可以手动发布周报！"

手动触发流程:

1. 回复 "开始爬取新闻生成周报，请稍候..."
2. 调用 `_generate_and_save()` 完整链路
3. 调用 `publish_to_groups(report, group_ids=[event.group_id])` — 仅发送到**当前群**（区别于定时任务的全局发送）
4. 成功回复 "周报已生成！"，失败回复 "周报生成失败，请检查日志。"

---

## 8. 爬坑记录

以下是在开发、测试和运维过程中遇到并修复的问题:

### 8.1 str | None 语法（Python 3.8 兼容）

- 问题: `Optional[str]` 被写成 `str | None`，该语法在 Python 3.10+ 才支持，而生产环境可能运行在 Python 3.8
- 修复: 统一替换为 `from typing import Optional` + `Optional[str]`

### 8.2 知识库缓存未失效

- 问题: `save_to_knowledge_base()` 写入新周报后，知识库查询模块仍然返回旧内容。原因是知识库有内存缓存，但未在写入后清除
- 修复: 在 `save_to_knowledge_base()` 之后调用 `clear_cache()`

### 8.3 BBC ConnectTimeout + 空错误信息

- 问题: BBC 经常触发 `httpx.ConnectTimeout`，且异常信息的 `str(e)` 为空字符串，排查困难
- 修复: 日志改为 `f"{type(e).__name__}: {e}"` 至少输出异常类型；同时加入 Guardian 源作为 BBC 的补偿

### 8.4 group_list 变量名遗漏

- 问题: 代码中 `group_list` 被重命名为 `targets`，但 `try` 块内仍有一处引用旧的变量名，导致定时任务发送时报 `NameError`
- 修复: 统一使用 `targets`，删除 `group_list` 引用

### 8.5 颜色标签在纯文本降级

- 问题: 图片渲染失败降级为纯文本时，`[red]`、`[blue]`、`[/red]`、`[/blue]` 原样保留在消息中，显示为裸标签
- 修复: 在 fallback 分支中用 `str.replace()` 去除所有颜色标签和 `*` 标记

### 8.6 跨行 / 未闭合的颜色标签导致 PIL 渲染崩溃

- 问题: LLM 可能输出跨行的 `[red]...\n...[/red]` 或漏写 `[/red]`，导致 `text_to_tactical_board()` 在 PIL 解析时报错
- 修复: 新增 `_clean_color_tags()` 函数，逐行检查颜色标签是否在同一行内正确匹配，否则去除该行的全部颜色标签
