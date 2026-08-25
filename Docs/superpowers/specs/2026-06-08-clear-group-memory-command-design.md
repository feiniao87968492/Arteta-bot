# Clear Group Memory Command Design

## Goal
为当前群聊增加一个管理员可用的 `clear` 指令，用于立即清除该群在 ChromaDB `group_memories` collection 中的长期对话记忆，避免影响其他群和其他数据表。

## Scope
本次只处理“当前群的长期语义记忆清除”。不修改 SQLite 中的 `players`、`messages`、`nicknames`、`member_relations` 等结构化数据，也不清理 `football_news` collection。

## User-Facing Behavior
- 主命令：`clear`
- 别名：`清除记忆`、`清空记忆`
- 仅管理员可用。
- 仅允许在群聊中使用；私聊调用时直接提示“该命令仅限群聊使用”。
- 命令执行后直接删除，不做二次确认。
- 成功时返回删除数量，例如：`已清除本群 23 条长期对话记忆。`
- 当本群没有可删记忆时，返回：`本群当前没有可清除的长期对话记忆。`
- 普通成员调用时，返回明确的无权限提示。

## Architecture
### 1. MemoryStore 增加群级删除能力
在 `plugins/arteta_memory.py` 的 `MemoryStore` 中新增一个按 `group_id` 删除的方法，例如 `clear_group_memories(group_id: str) -> int`。

行为要求：
- 在 `_ready` 为 `False` 时安全返回 `0`，不抛异常。
- 先按 `where={"group_id": str(group_id)}` 查询该群已有文档 ID。
- 若没有命中，返回 `0`。
- 若命中，则按 IDs 批量删除并返回删除数量。
- 出错时记录 warning 日志并返回 `0`，保持机器人主流程稳健。

这样做的好处是删除边界集中在记忆层，聊天命令层只负责权限和调用，不直接接触 ChromaDB API 细节。

### 2. 聊天层新增管理员命令
在 `plugins/arteta_chat.py` 的命令定义区新增一个清理命令 matcher，风格与现有 `刷新情报`、`好感度` 等命令保持一致。

命令处理逻辑：
1. 判断是否为 `GroupMessageEvent`；不是则直接结束并提示仅限群聊。
2. 判断调用者是否为管理员（沿用现有管理员判断方式）。
3. 调用 `memory_store.clear_group_memories(group_id)`。
4. 根据返回数量组织成功提示。

不需要把该命令拆到新插件文件；它和当前聊天记忆最强相关，放在 `arteta_chat.py` 可复用现有群聊上下文与管理员约束。

## Data Boundaries
清除对象仅限：
- ChromaDB collection：`group_memories`
- metadata 条件：`group_id == 当前群号`

明确不触碰：
- SQLite 数据库中的发言记录和画像
- `football_news` collection
- 其他群的任何 memory document

## Error Handling
- ChromaDB 未初始化：按“0 条已清除”处理，同时日志记录 warning，避免命令崩溃。
- 查询/删除异常：日志记录 warning，向用户返回温和失败提示，例如“清除记忆失败，请稍后再试”。
- 非管理员：立即拒绝，不暴露内部状态。
- 私聊调用：立即拒绝，不执行任何删除。

## Testing Strategy
### 单元测试：MemoryStore
在 `tests/test_arteta_memory.py` 增加对新删除方法的覆盖：
- 同时写入两个群的数据，只删除目标群，验证另一群仍可检索。
- 空群删除返回 0。
- `_ready=False` 时返回 0。

### 命令层测试
在聊天相关测试中新增或扩展用例，覆盖：
- 管理员在群聊执行 `clear`，调用成功并返回删除数量。
- 普通成员执行 `clear` 被拒绝。
- 私聊执行 `clear` 被拒绝。

如果现有测试装配 chat 命令较重，可以先用最小范围验证命令 handler 的控制流与 `memory_store.clear_group_memories()` 调用关系。

## Documentation
更新以下文档：
- `Docs/dev/chromadb-memory.md`：补充“可通过管理员 `clear` 指令清空当前群长期记忆”及范围说明。
- `Docs/user/commands.md` 或相关用户命令文档：补充新命令与管理员权限说明。
- 如有必要，在 `Docs/dev/overview.md` 的聊天链路/命令区加一句记忆清理入口说明。

## Rollout
本功能为本地代码变更，无数据库 schema 迁移。部署时同步上传涉及文件并重启 bot 进程即可。
