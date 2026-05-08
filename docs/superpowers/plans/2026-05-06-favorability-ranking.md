# 好感度排行柱状图 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `/好感度排行` 指令，用 matplotlib 生成两张横向柱状图（TOP 10 / BOTTOM 10），展示群成员好感度排行。

**Architecture:** 在 `arteta_render.py` 中新增 `favorability_bar_chart()` 函数（matplotlib 柱状图渲染），在 `arteta_chat.py` 中新增 `rank_cmd` 命令注册和 `handle_ranking` 处理器。两张图片先后发送。

**Tech Stack:** Python, NoneBot, matplotlib, aiosqlite

---

### Task 1: 新增 favorability_bar_chart() 渲染函数

**Files:**
- Modify: `plugins/arteta_render.py` — 在文件末尾（`close_browser` 之前）添加新函数

- [ ] **Step 1: 添加 matplotlib 导入**

在 `arteta_render.py` 顶部添加（第 7 行 `import logging` 之后）：
```python
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
```

- [ ] **Step 2: 添加字体配置辅助函数**

在 `close_browser` 函数之前（约第 193 行），添加：
```python
def _get_chinese_font():
    """获取中文字体，如果 msyh.ttc 不存在则回退到 sans-serif"""
    font_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "msyh.ttc")
    if os.path.exists(font_path):
        return font_path
    # 尝试系统字体
    for p in ["C:/Windows/Fonts/msyh.ttc", "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
              "/home/arteta/.fonts/msyh.ttc", "/opt/arteta_bot/msyh.ttc"]:
        if os.path.exists(p):
            return p
    return None
```

- [ ] **Step 3: 添加 favorability_bar_chart() 函数**

在 `_get_chinese_font()` 之后，`async def close_browser()` 之前，添加：
```python
def favorability_bar_chart(data: list, title: str = "信任度排行", bar_color: tuple = (219, 0, 7)) -> bytes:
    """绘制横向柱状图，data 为 [(nickname, favorability, level), ...]"""
    font_path = _get_chinese_font()
    if font_path:
        plt.rcParams['font.family'] = 'sans-serif'
        plt.rcParams['font.sans-serif'] = [font_path]
        plt.rcParams['axes.unicode_minus'] = False
    else:
        plt.rcParams['font.family'] = 'sans-serif'
        plt.rcParams['axes.unicode_minus'] = False

    n = len(data)
    fig_height = max(3, n * 0.55)
    fig, ax = plt.subplots(figsize=(14, fig_height))
    fig.patch.set_facecolor('#F8FAFC')
    ax.set_facecolor('#F8FAFC')

    # 提取数据
    names = []
    values = []
    levels = []
    colors = []
    for item in data:
        if len(item) == 4:
            nickname, fav, level, user_id = item
        else:
            nickname, fav, level = item
            user_id = ""
        display_name = nickname if len(nickname) <= 8 else nickname[:7] + "…"
        names.append(display_name)
        values.append(fav)
        levels.append(level)
        # 管理员柱子用金色
        colors.append('#F59E0B' if user_id == '2648955710' else bar_color)

    y_pos = range(n)

    # 绘制横向柱状图（每根柱子独立颜色）
    bars = ax.barh(y_pos, values, height=0.6, color=colors, edgecolor='white', linewidth=0.5)
    # 在右侧标注数值和等级
    for i, (v, lvl) in enumerate(zip(values, levels)):
        label = f"{v}  ({lvl})"
        ax.text(v + max(values) * 0.01 if v >= 0 else v - max(values) * 0.05,
                i, label, va='center', fontsize=11, color='#1E293B')

    # Y 轴标签
    ax.set_yticks(y_pos)
    ax.set_yticklabels(names, fontsize=12, color='#1E293B')

    # 隐藏上/右边框
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color('#CBD5E1')
    ax.spines['bottom'].set_color('#CBD5E1')

    # X 轴网格线
    ax.xaxis.grid(True, alpha=0.3, color='#CBD5E1')
    ax.set_axisbelow(True)

    # 标题 + 装饰红线
    ax.text(0.5, 1.08, title, transform=ax.transAxes, ha='center', va='bottom',
            fontsize=20, fontweight='bold', color='#DB0007')
    ax.plot([0, 1], [1.04, 1.04], transform=ax.transAxes, color='#DB0007', linewidth=3, clip_on=False)

    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()
```

**NOTE:** The font path handling in matplotlib needs a font path string, not a family name. The `plt.rcParams['font.sans-serif']` expects a list of font family names, not file paths. This needs to be handled differently.

**Fix for the font issue:** Instead of using rcParams with a file path, use `FontProperties` from matplotlib:

```python
from matplotlib.font_manager import FontProperties

def favorability_bar_chart(data: list, title: str = "信任度排行", bar_color: tuple = (219, 0, 7)) -> bytes:
    font_path = _get_chinese_font()
    if font_path:
        font_prop = FontProperties(fname=font_path)
        tick_font = font_prop
    else:
        font_prop = None
        tick_font = None

    # ... (same setup) ...

    # Y 轴标签 — use fontproperties
    ax.set_yticklabels(names, fontsize=12, color='#1E293B')
    if tick_font:
        for label in ax.get_yticklabels():
            label.set_fontproperties(tick_font)
    
    # Title font
    if font_prop:
        ax.text(0.5, 1.08, title, transform=ax.transAxes, ha='center', va='bottom',
                fontsize=20, fontweight='bold', color='#DB0007', fontproperties=font_prop)
    
    # Value labels
    for i, (v, lvl) in enumerate(zip(values, levels)):
        label = f"{v}  ({lvl})"
        ax.text(v + max(values) * 0.01 if v >= 0 else v - max(values) * 0.05,
                i, label, va='center', fontsize=11, color='#1E293B')
```

---

### Task 2: 新增命令注册和处理器

**Files:**
- Modify: `plugins/arteta_chat.py`

- [ ] **Step 1: 在指令定义区添加 rank_cmd**

在第 57 行 `fav_cmd` 之后添加：
```python
rank_cmd = on_command("好感度排行", aliases={"排行", "ranking", "信任度排行"}, priority=5, block=True)
```

- [ ] **Step 2: 添加 handle_ranking 处理器**

在 `handle_fav` 函数之后（约第 1260 行 `@profile_cmd.handle()` 之前），添加：
```python
@rank_cmd.handle()
async def handle_ranking(bot: Bot, event: GroupMessageEvent):
    group_id = str(event.group_id)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT nickname, favorability, level, user_id FROM players WHERE group_id = ? ORDER BY favorability DESC",
            (group_id,)
        ) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        await rank_cmd.finish("还没有球员数据，让大家先来交流！")

    top10 = rows[:10]
    bottom10 = list(reversed(rows[-10:])) if len(rows) > 10 else []

    try:
        img_top = favorability_bar_chart(top10, title="TOP 10 | 信任度排行", bar_color=(219, 0, 7))
        await rank_cmd.send(MessageSegment.image(img_top))
    except Exception as e:
        await rank_cmd.send(f"TOP 10 排行图生成失败：{str(e)}")

    if bottom10:
        try:
            img_bottom = favorability_bar_chart(bottom10, title="BOTTOM 10 | 需要反思", bar_color=(100, 116, 139))
            await rank_cmd.finish(MessageSegment.image(img_bottom))
        except Exception as e:
            await rank_cmd.finish(f"BOTTOM 10 排行图生成失败：{str(e)}")
    else:
        await rank_cmd.finish()
```

- [ ] **Step 3: 添加 import**

确认 `arteta_chat.py` 顶部已导入 `from plugins.arteta_render import favorability_bar_chart`（或添加到已有的 import 块中）。

当前 import 为：
```python
from plugins.arteta_render import (
    text_to_tactical_board,
    html_to_image,
    needs_html_render,
    close_browser as close_render_browser,
)
```

修改为：
```python
from plugins.arteta_render import (
    text_to_tactical_board,
    html_to_image,
    needs_html_render,
    favorability_bar_chart,
    close_browser as close_render_browser,
)
```

---

### Task 3: 部署到服务器

**Files:**
- Modify: `plugins/arteta_render.py` (SCP)
- Modify: `plugins/arteta_chat.py` (SCP)

- [ ] **Step 1: 上传文件并重启**

```bash
scp "D:\Users\zty\arteta_bot\plugins\arteta_render.py" arteta:/opt/arteta_bot/plugins/arteta_render.py
scp "D:\Users\zty\arteta_bot\plugins\arteta_chat.py" arteta:/opt/arteta_bot/plugins/arteta_chat.py
ssh arteta "supervisorctl restart arteta_bot && sleep 2 && supervisorctl status arteta_bot"
```

- [ ] **Step 2: 验证日志**

```bash
ssh arteta "tail -10 /var/log/arteta_bot/access.log"
```

确认 `arteta_render` 和 `arteta_chat` 插件加载成功。
