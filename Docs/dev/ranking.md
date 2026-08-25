# 好感度排行系统（Ranking Chart）

## 背景

`/好感度排行`（别名 `/排行`、`/ranking`、`/信任度排行`）指令用于展示群内球员的好感度排名，由 `arteta_chat.py` 中的 `rank_cmd` 处理器触发。数据源为 `players` 表的 `favorability` 字段，通过 `arteta_render.py` 的 `favorability_bar_chart()` 函数调用 matplotlib 绘制横向柱状图并输出为 PNG 图片。

## 显示内容

排行榜分两张图片先后发送：

| 图表 | 标题 | 柱状颜色 | 含义 |
|------|------|----------|------|
| TOP 10 | `球员 TOP 10 \| 信任度排行` | `#DB0007`（阿森纳红） | 好感度最高的 10 名球员 |
| BOTTOM 10 | `球员 BOTTOM 10 \| 需要反思` | `#64748B`（石板灰） | 好感度最低的 10 名球员 |

- BOTTOM 10 仅当总人数 > 10 时显示（`len(other_rows) > 10`）
- 数据从数据库按 `favorability DESC` 降序取出，在 `_do_bar_chart` 内反转后在图表上从上到下排列（最高者位于图表顶部）

## 管理员处理

管理员（QQ `2648955710`）在排名层直接过滤：

```python
other_rows = [r for r in rows if r[3] != ADMIN_QQ]
```

管理员被排除的原因是其好感度数值通常远高于普通用户，若包含在内会导致普通用户的柱状条过短、可视化效果变差。若过滤后无剩余数据，指令直接结束。

此外，`_do_bar_chart` 内部也保留了对管理员的特殊显示逻辑：若 `user_id == '2648955710'`，该柱状条显示为金色 `#F59E0B` 而非传入的 `bar_color`。但由于上层已过滤，此路径在正常流程中不会触发，仅作为防御性编程保留。

## 实现细节

### 1. LaTeX 临时禁用

`arteta_cmath.py` 全局将 `plt.rcParams['text.usetex']` 设为 `True`，以便在科学计算场景使用 LaTeX 公式渲染。但 matplotlib 的 LaTeX 渲染器（usetex）与中文字体存在兼容性问题——LaTeX 默认不包含中文字体支持，且 fontproperties 参数在 usetex 模式下无效。

`favorability_bar_chart()` 函数作为封装的入口函数，在绘制前保存旧值并临时关闭 `usetex`，通过 `try/finally` 保证无论绘制成功还是异常都能恢复：

```python
_old_usetex = plt.rcParams.get('text.usetex', False)
plt.rcParams['text.usetex'] = False
try:
    return _do_bar_chart(data, title, bar_color)
finally:
    plt.rcParams['text.usetex'] = _old_usetex
```

### 2. 颜色参数传递

`bar_color` 参数接受 CSS 十六进制字符串（如 `'#DB0007'`、`'#64748B'`）。在 matplotlib 的 0-1 范围 RGB 元组体系中，`#DB0007` 对应的元组应为 `(0.859, 0.0, 0.027)`。使用十六进制字符串而非元组可避免手动计算浮点值，且代码可读性更高——matplotlib 的 `barh()` 和 `text()` 等方法原生支持十六进制字符串。

函数签名：

```python
def favorability_bar_chart(
    data: list,
    title: str = "信任度排行",
    bar_color: tuple = (0.859, 0.0, 0.027)   # 默认值仍为元组，但调用处传字符串
) -> bytes
```

注意默认参数类型标注为 `tuple`，但实际调用时传入的是 `str`——这是因为调用方 `arteta_chat.py` 传入了 `bar_color='#DB0007'` 和 `bar_color='#64748B'`。此处的类型标注与实际用法不完全一致，属于历史遗留。

### 3. 中文字体查找与回退

`_get_chinese_font()` 按优先级查找可用中文字体文件：

1. 项目根目录的 `msyh.ttc`（微软雅黑）
2. `C:/Windows/Fonts/msyh.ttc`（Windows 系统字体）
3. `/usr/share/fonts/truetype/wqy/wqy-microhei.ttc`（Linux 文泉驿微米黑）
4. `/home/arteta/.fonts/msyh.ttc`（用户目录）
5. `/opt/arteta_bot/msyh.ttc`（部署目录）

若全部未找到，`font_prop` 为 `None`，图表使用 matplotlib 默认字体（中文将显示为方框）。

### 4. 左边界自适应

昵称长度差异较大（2-20+ 字符），使用固定左边距会导致长昵称被截断。代码通过计算最大昵称长度动态调整：

```python
max_name_len = max((len(n) for n in names), default=0)
left_margin = max(0.12, 0.12 + (max_name_len - 10) * 0.015)
fig.subplots_adjust(left=left_margin, right=0.92)
```

公式：基准边距 0.12，昵称每超出 10 字符增加 0.015。`subplots_adjust` 与 `tight_layout` 互斥，因此不启用自动布局。

### 5. 图像尺寸自适应

根据数据条目数动态计算图像高度：

```python
fig_height = max(3, n * 0.55)
```

至少 3 英寸，每行数据约 0.55 英寸。结合 `figsize=(14, fig_height)` 确保紧凑型排行（如仅有 3 人）不会产生过多空白。

### 6. 完整绘图流程

`_do_bar_chart` 的绘制步骤：

1. 反转数据列表（数据库降序 -> 图表顶部为最高者）
2. 设置图表和坐标轴背景色为 `#F8FAFC`
3. 准备昵称、数值、等级、颜色列表（管理员检测 + 默认颜色）
4. `ax.barh()` 绘制横向柱状图，柱高 0.6，白色边框
5. 在柱状条右侧标注 `数值 (等级)`，字体大小 11，颜色 `#1E293B`
6. 设置 Y 轴刻度标签为中文字体显示的昵称
7. 隐藏上边框和右边框，保留左右下边框并设为 `#CBD5E1`
8. 开启 X 轴网格线（透明度 0.3），确保柱状条绘制在网格线上层
9. 添加 `#DB0007` 红色粗标题，下方绘制同色装饰线
10. `fig.savefig()` 以 150 DPI 输出 PNG，`bbox_inches='tight'` 自动裁剪边距
11. `plt.close(fig)` 释放内存

### 7. 响应格式

返回 `MessageSegment.image(img_bytes)`，两张图依次发送。若生成异常，捕获后发送文字错误信息，避免指令无响应：

- TOP 10 出错：`await rank_cmd.send(...)` 发送错误消息
- BOTTOM 10 出错：`await rank_cmd.finish(...)` 发送错误消息并结束指令
