# 每日群聊总结 —— 阿尔特塔的更衣室日报

## 1. 背景

- 记录所有群聊消息到本地数据库，每天 22:30 自动生成一份"阿尔特塔风格"的群聊日报。
- 通过 `SUMMARY_ENABLED` 配置开关（默认开启）控制是否启用自动总结。
- 使用 DeepSeek API 生成总结文本，再通过 `text_to_tactical_board()` 渲染为战术板风格图片发送到各群。

## 2. 数据库

- **库文件**: `arsenal_data.db`（项目根目录）
- **表**: `daily_messages`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | 自增主键 |
| `user_id` | TEXT NOT NULL | 用户 QQ 号 |
| `group_id` | TEXT NOT NULL | 群号 |
| `nickname` | TEXT DEFAULT '' | 群昵称 / 名片 |
| `message` | TEXT NOT NULL | 消息纯文本 |
| `timestamp` | INTEGER NOT NULL | Unix 时间戳 |

- 索引：`idx_daily_ts` on `(group_id, timestamp)` — 加速按群和时间范围查询。
- 数据库在模块加载时由 `init_db()` 自动创建。

## 3. 消息记录

- **位置**: `plugins/arteta_daily.py` — `record_all`
- **类型**: `on_message(priority=1, block=False)`
- **优先级 1** 确保在所有命令处理器（priority=3~11, block=True）之前运行。
- `block=False` 不阻断事件传递，消息会继续被其他处理器消费。
- 记录时机：消息纯文本非空时，异步写入 `daily_messages` 表。
- 写入键：`user_id`, `group_id`, `nickname`, `message`, `timestamp`。

## 4. 定时任务

- **调度器**: nonebot-plugin-apscheduler
- **触发器**: `cron`, hour=22, minute=30
- **任务 ID**: `daily_summary`
- **misfire_grace_time**: 300 秒

### 执行流程 `daily_summary_job()`

1. 检查 `SUMMARY_ENABLED`，若禁用则跳过。
2. 获取所有 bot 实例，无实例则跳过。
3. 计算当日 00:00 ~ 23:59 的时间戳范围。
4. 查询当日有消息的所有 `group_id`（DISTINCT）。
5. 无任何消息则跳过。
6. 对每个 bot 实例、每个群：
   a. 查询该群当日的全部消息（按时间升序）。
   b. 若消息非空，调用 `generate_summary(messages)` 生成总结。
   c. 组装带 `[red]` / `[blue]` 标记的最终文本。
   d. 调用 `text_to_tactical_board()` 渲染为图片发送；若图片渲染失败则回退为纯文本发送。
7. 所有群发送完成后执行数据清理（见第 6 节）。

## 5. 手动触发

- **指令**: `/今日总结` 或 `/日报` 或 `/daily`
- **处理器**: `handle_manual_summary()` — `on_command("今日总结", aliases={"日报", "daily"}, priority=5, block=True)`
- **权限**: 仅管理员（`ADMIN_QQ = "2648955710"`）可用。
- **非管理员回复**: "只有教练组可以手动发布总结！"
- **流程**:
  1. 校验用户 QQ 是否为管理员。
  2. 查询**当前群**当日的消息记录。
  3. 无消息则回复 "今天群里还没人说话呢，让球员们热起来！"
  4. 调用 DeepSeek 生成总结。
  5. API 失败则回复 "总结生成失败（API 可能暂时离线）"。
  6. 优先渲染图片发送，失败回退纯文本。
- **与定时任务的区别**: 只向触发指令的群发送，而非所有群。

## 6. 数据流

```
群消息 → on_message(priority=1) → INSERT daily_messages
  ↓
每天 22:30 (定时任务) 或 /今日总结 (手动)
  ↓
SELECT messages WHERE group_id=? AND timestamp IN today
  ↓
generate_summary()
  ├─ 拼接聊天日志 {chat_log}
  ├─ 统计：总消息数、发言人数、TOP5 活跃用户
  └─ 调用 DeepSeek API (deepseek-v4-flash, temp=0.7, max_tokens=1000)
  ↓
组装 final_text（标题 + 日期 + 总结内容）
  ↓
text_to_tactical_board() → PNG 图片
  ↓
send_group_msg(image) → 发送到群
  ↓（渲染失败回退）
send_group_msg(text) → 纯文本发送
```

### generate_summary() 细节

- 聊天日志截断：只取最后 4000 字符（`chat_log[-4000:]`）避免超 token。
- DeepSeek API 重试：最多 2 次，间隔 2 秒。
- 超时设置：`httpx.AsyncClient(timeout=60.0)`。
- 返回 `str` 或 `None`。

## 7. 自动清理

- **时机**: 每天 22:30，在 `daily_summary_job()` 末尾（非独立定时任务）。
- **范围**: `DELETE FROM daily_messages WHERE timestamp < (today_start - 7 * 86400)`
- **逻辑**: 删除 7 天前（以当日 00:00 为基准）的所有消息记录。
- **注意**: 清理与总结在同一函数内顺序执行，先发送完所有群的总结，再执行清理。

## 8. LLM Prompt

- **角色设定**: 你是阿尔特塔，阿森纳主教练。晚上在更衣室对球员做今天训练和聊天的总结。
- **输入**: 当日聊天记录（时间排序）、统计数据。
- **要求**:
  1. 点名最活跃的几名球员，点评热情和表现。
  2. 提到当天主要话题、热点。
  3. 语气激情、直接、有感染力，像在更衣室里讲话。
  4. 控制在 300-500 字。
  5. 使用 `[red]...[/red]` 标记阿森纳相关内容，`[blue]...[/blue]` 标记其他内容。
  6. 最后用一句激励的话收尾。
  7. 不要列数据清单，用自然的段落表达。
- **模型**: `deepseek-v4-flash`, temperature=0.7, max_tokens=1000。

## 9. 关键配置

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `deepseek_api_key` | str | "" | DeepSeek API 密钥 |
| `daily_summary_enabled` | str | "true" | 是否启用定时总结 |

## 10. 相关文件

| 文件 | 说明 |
|---|---|
| `plugins/arteta_daily.py` | 主逻辑：消息记录、总结生成、定时任务、手动指令 |
| `plugins/arteta_render.py` | 图片渲染：`text_to_tactical_board()` |

## 11. 注意事项

- 图片渲染依赖 `arteta_render.py` 中的 `text_to_tactical_board()`，若该函数异常会自动降级为纯文本发送。
- 聊天记录截断为最后 4000 字符，若某群当天消息量极大可能会丢失早前上下文。
- 数据清理与总结在同一定时任务中执行，若总结发送失败（如所有 bot 离线），清理仍会执行（无事务回滚）。
- DeepSeek API 调用无内置 rate-limit 保护，高频手动触发可能触发 API 限流。
