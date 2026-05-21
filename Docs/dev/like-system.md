# QQ 名片赞系统（Like System）

## 背景

`/赞我`（别名 `/点赞我`、`/like_me`）指令用于向 QQ 用户发送名片赞（profile like）。基于 NapCat 实现的 OneBot V11 `send_like` API，每日限量，并配有阿尔特塔风格的随机语录。

## 定义

- **指令**: `like_cmd` — `on_command("赞我", aliases={"点赞我", "like_me"}, priority=5, block=True)`
- **模块**: `plugins/arteta_like.py`
- **数据表**: `daily_likes(user_id, like_date, count)` — 以 `(user_id, like_date)` 为联合主键

## 每日限额

| 用户类型 | 每日上限 | 常量 |
|----------|----------|------|
| 普通用户 | 10 | `MAX_NORMAL = 10` |
| VIP 用户 | 50 | `MAX_VIP = 50` |

当用户当日已用次数达到上限时，随机返回一条 teasing 语录（共 6 条），并附带当前用量 `（current/max_likes）`。

## VIP 检测

VIP 检测分两步：

1. **NapCat 扩展字段**: 调用 `get_group_member_info`，检查返回的 `is_vip` 字段是否为 `True`，或 `vip_level > 0`。
2. **群管理特权**: 若 NapCat 未返回 VIP 标志，但用户角色为 `owner`（群主）或 `admin`（管理员），自动赋予 VIP 待遇。

若 API 调用失败（如网络异常），`is_vip` 保持 `False`，以普通用户限额执行。

## 数据库

`daily_likes` 表结构：

```sql
CREATE TABLE IF NOT EXISTS daily_likes (
    user_id TEXT NOT NULL,
    like_date TEXT NOT NULL,
    count INTEGER DEFAULT 0,
    PRIMARY KEY (user_id, like_date)
)
```

- `_get_count(user_id)` — 查询当日已用次数
- `_add_count(user_id, n)` — 使用 `INSERT ... ON CONFLICT DO UPDATE` 原子增加计数

表在模块加载时（`_init_table()`）自动创建。

## 点赞 API 调用

### 调用流程

`handle_like_me` 使用两级调用策略：

1. **专用方法**（一级）：检测适配器是否具有 `bot.send_like` 方法，若有则逐次调用（每次 1 赞），循环 `remaining` 次。
2. **通用 API**（二级）：若适配器无专用方法，调用 `bot.call_api("send_like", user_id=..., times=remaining)` 一次性发送全部剩余次数。NapCat 和 go-cqhttp 均支持此扩展 API。

`times` 参数由 OneBot 协议服务端处理，一次性扣除相应次数，避免多次 HTTP 请求的开销。

### 回退与容错

若 `call_api("send_like", times=remaining)` 抛出异常，分两种情况处理：

- **协议不支持**：异常信息匹配 `not implemented` / `unsupported action` / 错误码 `10002` 时，发送明确错误提示消息，然后通过 `FinishedException` 终止指令。错误消息内容：

  > 【阿尔特塔】当前 QQ 协议不支持点赞功能（send_like），请联系管理员检查 NapCat 版本。

- **临时网络故障**：若此时 `remaining == max_likes`（即第一次调用就失败了，此前尚未成功任何赞），回退为逐次调用 `send_like(times=1)`，在循环中捕获异常并 `break`，尽可能送达部分点赞。

  ```python
  if remaining == max_likes:
      liked = 0
      for i in range(remaining):
          try:
              await bot.call_api("send_like", user_id=int(user_id), times=1)
              liked += 1
          except Exception:
              break
  ```

  若首次调用成功但返回值异常（`resp` 为 `dict` 时），从 `resp.get("liked", remaining)` 读取实际点赞数。

### 计数写入

无论通过何种方式成功点赞，当 `liked > 0` 时调用 `_add_count(user_id, liked)` 将实际送达次数写入数据库。该函数使用 `INSERT ... ON CONFLICT DO UPDATE` 原子操作：

```sql
INSERT INTO daily_likes (user_id, like_date, count) VALUES (?, ?, ?)
ON CONFLICT(user_id, like_date) DO UPDATE SET count = count + ?
```

## 回复机制

### 点赞成功

从 13 条阿尔特塔式鼓励语录中随机选取一条发送，格式：

```
【阿尔特塔】{语录}（会员×50）（已点赞 {n} 次）
```

- VIP 用户追加 `（会员×50）` 后缀
- 当 `liked > 1` 时追加 `（已点赞 {n} 次）`

示例语录：

> 这跑位，值一个赞！去跑几个折返跑庆祝一下。
> 这就是阿森纳的标准——永不满足，永远要更多。
> 真正的枪手从不满足——你今天做得不错，但明天要更好。

### 额度耗尽

当 `current >= max_likes` 时，从 6 条 teasing 语录中随机选取，附使用比例：

```
【阿尔特塔】{语录}（{current}/{max_likes}）
```

回答后通过 `FinishedException` 终止指令，避免继续执行点赞逻辑。

### 执行流控制

模块使用 `from nonebot.exception import FinishedException` 控制指令生命周期。在额度耗尽和 API 不可用两个分支中，显式 `raise FinishedException()`（或调用 `await rank_cmd.finish()`）中断处理器后续代码执行。正常点赞流程则走到函数末尾自然结束。

## 错误处理

- **API 不可用**：匹配特定错误关键词后给出明确指引，要求管理员检查 NapCat 版本
- **网络临时故障**：回退逐次点赞，最大化送达率；失败时静默中断，不报错给用户
- **`get_group_member_info` 失败**：`is_vip` 保持 `False`，不影响基本点赞功能
