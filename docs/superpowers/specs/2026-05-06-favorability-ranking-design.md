# 好感度排行柱状图 - 设计说明

## 目标
新增 `/好感度排行` 指令，以两张横向柱状图展示本群好感度最高 10 人（TOP 10）和最低 10 人（BOTTOM 10）。

## 改动范围

### 修改文件
- `plugins/arteta_chat.py` — 新增命令注册和处理器
- `plugins/arteta_render.py` — 新增 `favorability_bar_chart()` 渲染函数

### 不修改
- 数据库结构不变（复用 `players` 表已有的 `favorability` 字段）
- 不新增依赖（matplotlib 已安装）

## 详细设计

### 1. 命令注册（arteta_chat.py）

```python
rank_cmd = on_command("好感度排行", aliases={"排行", "ranking", "信任度排行"}, priority=5, block=True)
```

### 2. 处理器逻辑（handle_ranking）

```python
@rank_cmd.handle()
async def handle_ranking(bot: Bot, event: GroupMessageEvent):
    group_id = str(event.group_id)
    # 查询本群所有玩家，按好感度降序
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT nickname, favorability, level FROM players WHERE group_id = ? ORDER BY favorability DESC",
            (group_id,)
        ) as cursor:
            rows = await cursor.fetchall()
    # 无数据返回
    if not rows:
        await rank_cmd.finish("还没有球员数据，让大家先来交流！")
    # TOP 10 和 BOTTOM 10
    top10 = rows[:10]
    bottom10 = list(reversed(rows[-10:])) if len(rows) > 10 else []
    # 生成两张图
    img_top = favorability_bar_chart(top10, title="TOP 10 | 信任度排行", color=(219, 0, 7))
    await rank_cmd.send(MessageSegment.image(img_top))
    if bottom10:
        img_bottom = favorability_bar_chart(bottom10, title="BOTTOM 10 | 需要反思", color=(100, 116, 139))
        await rank_cmd.finish(MessageSegment.image(img_bottom))
```

### 3. 渲染函数（arteta_render.py）

**参数**：`data: list[tuple[nickname, favorability, level]]`, `title: str`, `color: tuple`

**流程**：
1. 创建 matplotlib 画布（16:9 比例，16寸宽）
2. 设置深色细边框，白色背景
3. 水平柱状图：`barh`
4. 昵称截断：超过 8 个中文字符宽度时加 `...`
5. 柱右侧标注好感度数值
6. 柱内或右侧标注等级
7. 管理员 QQ（2648955710）柱子用金色 `#F59E0B`
8. 顶部大标题 + 阿森纳红色装饰线
9. 保存为 PNG 字节流返回

### 4. 错误处理
- 群内无数据：直接文本回复
- 群内少于 10 人：TOP 显示全部，BOTTOM 为空（不发第二张图）
- 昵称过长：截断显示
