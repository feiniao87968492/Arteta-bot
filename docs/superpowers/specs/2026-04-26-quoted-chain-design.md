# 引用消息链提取功能设计

## 概述

为 arteta_bot 增加递归引用消息链提取功能。当用户在群聊中回复（引用）某条消息并使用 `A` 命令或 `@bot` 触发对话时，将完整引用链（最多 3 层）提取并作为背景信息传递给大模型，替代当前仅提取单层纯文本的简单实现。

## 背景

当前实现（`plugins/arteta_chat.py` 第 401-424 行）:
- 只处理第一层引用
- 只提取纯文本，跳过图片等
- 不支持嵌套引用（被引用的消息本身也是引用）
- 格式单一，无法体现消息层级关系

## 方案

### 递归提取函数 `fetch_quoted_chain`

新增一个异步递归函数，接受 `(bot, message_id, depth=0)` 参数：

```
fetch_quoted_chain(bot, message_id, depth=0)
  ├── bot.get_msg(message_id) 获取单条消息
  ├── 提取发送者: card/昵称 + QQ号
  ├── 提取纯文本: 遍历 message 段，只取 type=="text" 的 data.text
  ├── 检测嵌套引用: 检查该消息是否有 type=="reply" 段
  │   ├── 有且 depth < 2 → 递归 fetch_quoted_chain(reply_id, depth+1)
  │   └── 否则 → 终止（最多 3 层：depth 0, 1, 2）
  └── 返回结构化的引用链文本（由旧到新，渐进缩进）
```

### 数据流

```
用户发送: [reply to msg_3] A 分析一下这段

process_chat() 入口
  └── 检测到 reply 段，message_id = msg_3
      └── fetch_quoted_chain(msg_3, depth=0)
          ├── bot.get_msg(msg_3) → sender=userC, text="的确如此", reply_id=msg_2
          │   └── fetch_quoted_chain(msg_2, depth=1)
          │       ├── bot.get_msg(msg_2) → sender=userB, text="同意", reply_id=msg_1
          │       │   └── fetch_quoted_chain(msg_1, depth=2)
          │       │       ├── bot.get_msg(msg_1) → sender=userA, text="我觉得这个方案不错", reply_id=null
          │       │       └── 无引用，终止
          │       └── 返回 "原始消息 - userA(11111)：我觉得这个方案不错"
          └── 返回 "原始消息 - userA(11111)：我觉得这个方案不错\n  ↳ userB(22222) 回复：同意"
      └── 返回 "原始消息 - userA(11111)：我觉得这个方案不错\n  ↳ userB(22222) 回复：同意\n    ↳ userC(33333) 回复：的确如此"

最终放入 final_prompt:
【引用消息链（由旧到新）】：
原始消息 - userA(11111)：我觉得这个方案不错
  ↳ userB(22222) 回复：同意
    ↳ userC(33333) 回复：的确如此
```

### 出错处理

- 如果 `bot.get_msg()` 抛出异常（消息不存在/无权限/跨群）：该层用 `[消息获取失败]` 占位，不影响上层
- 如果消息只有图片/非文本内容：文本部分为空字符串，标注 `[仅含非文本内容]`
- 如果某层引用已删除或不可访问：标注 `[已被撤回或删除]`

### 涉及修改的文件

| 文件 | 改动 |
|------|------|
| `plugins/arteta_chat.py` | 替换现有 401-424 行的引用处理逻辑为新递归实现 |
| 无需新增文件 | |

### 代码位置定位

- 移除现有代码（行 401-424）：从 `quoted_text = ""` 到 `break`
- 在新位置定义 `fetch_quoted_chain` 函数
- 在 `process_chat` 中原位置调用该函数替换旧逻辑

### 不变的部分

- 引用内容仍放在 `final_prompt` 的背景信息段（方案B）
- 图片等非文本内容仍然跳过
- 对话记忆（`user_memories`）、检索信息等现有逻辑不变
