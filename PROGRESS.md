# Arteta Bot - 修改日志

## 项目概述
基于 nonebot 的 QQ 机器人，扮演阿森纳主教练阿尔特塔。

## 修改记录

### 2026-05-04: 实现个人档案系统

**问题描述**：
- 大模型对不同成员之间的记忆非常混乱
- 需要为每个QQ号维护个人档案
- 需要记录历史昵称和发言

**修改方案**：

#### 1. 数据库结构扩展
在 `arsenal_data.db` 中添加两个新表：

**nicknames 表** - 记录历史昵称：
```sql
CREATE TABLE IF NOT EXISTS nicknames (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    group_id TEXT NOT NULL,
    nickname TEXT NOT NULL,
    first_seen INTEGER NOT NULL,
    last_seen INTEGER NOT NULL,
    UNIQUE(user_id, group_id, nickname)
)
```

**messages 表** - 记录发言历史：
```sql
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    group_id TEXT NOT NULL,
    message TEXT NOT NULL,
    timestamp INTEGER NOT NULL
)
```

#### 2. 代码修改位置
- 文件：`plugins/arteta_chat.py`
- 修改函数：`init_db_safely()` - 添加新表创建
- 新增函数：`update_nickname_history()` - 更新昵称历史
- 新增函数：`save_message()` - 保存发言记录
- 新增函数：`get_user_profile()` - 获取用户档案
- 新增命令：`/档案` 或 `/profile` - 查询个人档案

#### 3. 实现细节
- 昵称变更时，自动记录到 nicknames 表（在 `update_and_get_player()` 中调用）
- 每次发言自动保存到 messages 表（在 `process_chat()` 中调用）
- 提供 `/档案` 命令查看个人档案（历史昵称、发言统计等）
- 档案显示内容：当前昵称、QQ号、身份定位、信任度、上次活跃时间、发言总数、最近5个历史昵称、最近5条发言

#### 4. 修改方式详解

**步骤1：扩展数据库初始化**
- 在 `init_db_safely()` 函数中添加两个新表的创建语句
- 使用 `CREATE TABLE IF NOT EXISTS` 确保兼容性

**步骤2：添加数据记录函数**
- `update_nickname_history()`: 记录每次昵称变更，使用 UPSERT 逻辑避免重复
- `save_message()`: 保存每条发言消息，包含时间戳

**步骤3：集成到现有流程**
- 在 `update_and_get_player()` 函数开头调用 `update_nickname_history()`
- 在 `process_chat()` 函数中，获取用户信息后调用 `save_message()`

**步骤4：添加查询命令**
- 定义新命令：`profile_cmd = on_command("档案", aliases={"profile", "个人档案"}, priority=6, block=True)`
- 实现 `handle_profile()` 处理函数，调用 `get_user_profile()` 获取完整档案

---

## 部署状态

### 2026-05-04 15:16 部署完成

**部署步骤**：
1. ✅ 本地代码修改完成（`plugins/arteta_chat.py`）
2. ✅ 上传到服务器 `/opt/arteta_bot/plugins/arteta_chat.py`
3. ✅ 安装依赖：`pillow`, `pilmoji`
4. ✅ 上传字体文件：`msyh.ttc`
5. ✅ 重启机器人服务
6. ✅ 验证数据库表创建成功

**验证结果**：
- 数据库表：`players`, `nicknames`, `messages` 已创建
- 机器人进程：PID 215632 正在运行
- HTTP 端口：8088 正常监听
- 插件加载：所有插件加载成功

**服务器信息**：
- 地址：http://118.178.140.171/
- 项目目录：`/opt/arteta_bot/`
- 数据库路径：`/opt/arteta_bot/arsenal_data.db`
- Python 环境：`/opt/arteta_bot/venv/bin/python`

---

## 使用说明

### 新增命令
- `/档案` 或 `/profile` 或 `/个人档案` - 查看个人档案

### 自动记录功能
- 每次用户发言自动保存到 `messages` 表
- 每次昵称变更自动记录到 `nicknames` 表
- 数据库会在机器人启动时自动创建新表

### 档案显示内容
- 当前昵称和 QQ 号
- 身份定位（青训生/一线队/核心首发/传奇队长）
- 信任度分数
- 上次活跃时间
- 发言总数
- 最近 5 个历史昵称（含时间范围）
- 最近 5 条发言记录（含时间戳）

---

## 注意事项
- 数据库路径：`arsenal_data.db`
- 管理员 QQ：2648955710
- 所有时间戳使用 Unix 时间戳格式
- 字体文件：`msyh.ttc`（已上传到服务器）

---

### 2026-05-04 15:24: 修复图片识别 HTTP 403 错误

**问题描述**：
- 用户引用图片时，图片识别失败，返回 `[图片识别失败：HTTP 403]`
- 导致大模型无法获取图片内容

**问题原因**：
- QQ 图片服务器需要特定的请求头才能访问
- 原代码直接使用 `httpx.AsyncClient()` 下载图片，没有添加请求头
- 服务器拒绝了没有正确请求头的请求

**修复方案**：
- 修改 `analyze_image()` 函数
- 添加正确的请求头：
  - `User-Agent`: 模拟浏览器访问
  - `Referer`: 设置为 QQ 官网
  - `Accept`: 设置为图片类型
- 添加 `verify=False` 以支持 HTTPS 连接

**修改位置**：
- 文件：`plugins/arteta_chat.py`
- 函数：`analyze_image()`
- 行号：约 370-397

**验证方法**：
- 用户可以再次引用图片测试
- 检查日志中是否还有 HTTP 403 错误
- 确认大模型能正确获取图片内容描述

---

### 2026-05-04 15:29: 改进图片识别方案

**问题**：
- HTTP 403 错误仍然存在，QQ 图片服务器需要更复杂的认证

**新方案**：
- 使用 OneBot 的 `get_image` API 获取图片文件
- 将图片转换为 base64 后直接调用 Vision API
- 避免直接下载 QQ 图片 URL

**修改内容**：
1. 新增 `analyze_image_base64()` 函数：处理 base64 编码的图片
2. 修改 `fetch_quoted_chain()` 函数：
   - 使用 `bot.get_image(file=file_id)` 获取图片
   - 读取本地文件并转换为 base64
   - 调用 `analyze_image_base64()` 进行识别
3. 简化 `analyze_image()` 函数：复用 `analyze_image_base64()`

**优势**：
- 绕过 QQ 图片服务器的访问限制
- 使用 OneBot 标准 API，更稳定可靠
- 支持本地文件缓存

---

### 2026-05-04 15:35: 修复容器文件系统隔离问题

**问题**：
- `bot.get_image()` 返回的文件路径是 Docker 容器内部路径
- bot 进程运行在宿主机上，无法访问容器内部文件

**解决方案**：
- 直接使用消息段中的 `url` 字段下载图片
- 不再依赖 `bot.get_image()` 返回的本地文件路径

**修改内容**：
- 简化图片处理逻辑
- 直接从 URL 下载图片并识别

**验证**：
- 请再次测试引用图片功能

---

### 2026-05-04 15:40: 使用 get_image API 获取认证 URL

**问题**：
- 直接从消息段中的 URL 下载图片仍然返回 HTTP 403
- QQ 图片服务器需要特殊的认证参数（rkey）

**解决方案**：
- 使用 `bot.get_image(file=file_id)` 获取带认证的 URL
- 该 API 返回的 URL 包含完整的认证参数
- 使用返回的 `url` 字段下载图片

**修改内容**：
- 修改 `fetch_quoted_chain()` 函数中的图片处理逻辑
- 先调用 `bot.get_image()` 获取认证 URL
- 再使用认证 URL 下载图片

**验证**：
- 请再次测试引用图片功能

---

### 2026-05-04: 实现人格画像系统

**问题描述**：
- 机器人对不同成员的回复缺乏个性化
- 只传递最基本的用户信息（昵称、等级、好感度）
- 没有根据用户特征调整回复风格

**修改方案**：

#### 1. 数据库结构扩展
在 `arsenal_data.db` 中添加：

**players 表新增字段**：
- `profile_json TEXT DEFAULT '{}'` - 存储人格画像 JSON

**profile_updates 表** - 记录画像更新历史：
```sql
CREATE TABLE IF NOT EXISTS profile_updates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    group_id TEXT NOT NULL,
    old_profile TEXT,
    new_profile TEXT,
    trigger_message TEXT,
    timestamp INTEGER NOT NULL
)
```

**profile_json 存储的 JSON 结构**：
```json
{
  "personality": "性格特征",
  "interests": "兴趣爱好",
  "favorite_team": "支持的球队",
  "rival_teams": "讨厌的球队",
  "speaking_style": "说话风格",
  "relationship_with_arteta": "与阿尔特塔的关系",
  "notable_events": "关键事件",
  "last_profile_update": 1714800000,
  "message_count_at_update": 42
}
```

#### 2. 新增函数
- `get_message_count()` - 获取用户消息总数
- `should_update_profile()` - 判断是否触发画像更新
- `update_user_profile()` - 调用 LLM 分析用户消息并更新画像
- `get_profile_section()` - 获取用户画像的 prompt 片段

#### 3. 画像更新触发策略
- 新用户 3 条消息后触发初始化
- 每 5 条消息触发一次
- 超过 24 小时触发
- 10 分钟冷却期防止频繁调用

#### 4. Prompt 构建优化
在 `process_chat()` 中：
- 加载用户画像数据
- 构建包含性格、兴趣、球队偏好等信息的 profile_section
- 添加个性化回复要求指令

#### 5. ARTETA_PROMPT 增强
添加个性化互动指令：
- 根据球员档案调整回应方式
- 对热刺球迷适当调侃
- 对忠实枪迷给予更多鼓励
- 根据说话风格调整态度

#### 6. /档案 命令增强
在档案输出中显示：
- 主教练对你的了解（性格、兴趣、球队偏好等）
- 说话风格
- 双方关系描述

**修改位置**：
- 文件：`plugins/arteta_chat.py`
- 修改函数：`init_db_safely()`, `get_user_profile()`, `handle_profile()`, `process_chat()`
- 新增函数：`get_message_count()`, `should_update_profile()`, `update_user_profile()`, `get_profile_section()`

**验证方法**：
1. 发送 3+ 条消息后观察是否触发画像更新（检查日志）
2. 使用 `/档案` 命令查看画像是否正确显示
3. 对比不同用户的回复，验证个性化效果

---

## 部署状态

### 2026-05-04: 人格画像系统部署

**部署步骤**：
1. ✅ 本地代码修改完成（`plugins/arteta_chat.py`）
2. ⏳ 上传到服务器 `/opt/arteta_bot/plugins/arteta_chat.py`
3. ⏳ 重启机器人服务
4. ⏳ 验证数据库表创建成功

**验证命令**：
```bash
# 检查 profile_json 列是否存在
sqlite3 arsenal_data.db "PRAGMA table_info(players);"

# 检查 profile_updates 表是否存在
sqlite3 arsenal_data.db ".tables"

# 查看画像数据
sqlite3 arsenal_data.db "SELECT user_id, profile_json FROM players WHERE profile_json != '{}';"
```

---

### 2026-05-04: 终极修复图片识别 HTTP 403 失败问题

**问题描述**：
- 经过 4 轮修复（添加请求头、bot.get_image 本地路径、Docker 路径转换、get_image 认证 URL），图片识别仍然失败
- 引用(回复)图片消息始终无法返回图片描述

**根因分析**（参考 `astrbot_backup_20260504_215419` 备项目）：

1. **QQ CDN 的 HTTPS 端点验证严格**：备份项目中所有 QQ 图片 URL 都通过 `url.replace("https://", "http://")` 转为 HTTP 下载。HTTPS 端点要求更复杂的 rkey 认证，但 HTTP 端点验证宽松。
2. **缺少多重下载策略**：原代码仅使用一个 httpx 客户端单一策略，没有 fallback 机制。
3. **硬编码 MIME 类型**：`data:image/jpeg;base64,...` 对所有图片都写死为 jpeg，对于 PNG/GIF 图片可能导致 Vision API 处理异常。
4. **脆弱的 Docker 路径转换**：硬编码了容器 volume hash，在不同部署环境下失效，且一旦路径转换失败就走 URL 下载，形成双重失败。

**修复方案**：

**修改文件**：`plugins/arteta_chat.py`

**修改内容**：

1. **新增 `_detect_image_format()`**：通过文件头魔数检测实际图片格式（jpeg/png/gif/webp/heic），构建正确的 data URL MIME 类型。

2. **新增 `_download_image_bytes()`**：三重策略下载：
   - 策略1：httpx + HTTPS + 请求头（Referer/User-Agent）
   - 策略2：httpx + HTTP（从 HTTPS 降级，QQ CDN 对 HTTP 更宽松）
   - 策略3：aiohttp + HTTP（匹配备份项目验证过的成功方案）

3. **简化 `fetch_quoted_chain()` 图片处理**：
   - 移除脆弱的 Docker 路径转换（`/app/.config/QQ/` → volume path）
   - 移除本地文件读取逻辑
   - 统一使用 URL 下载（`bot.get_image()` 获取最新 URL + 消息段 URL 作为 fallback）
   - 依赖 `_download_image_bytes()` 的多重策略处理下载

4. **增强 `analyze_image_base64()` 错误输出**：
   - 在错误消息中包含 API 响应体前 200 字符，方便定位 Vision API 的具体错误

**优势**：
- 多重下载策略确保即使 QQ CDN 的 HTTPS 端点失败，HTTP 端点也能成功
- 正确检测图片格式，避免 Vision API 因 MIME 类型错误而失败
- 备份项目验证过的 aiohttp + HTTP 方案作为最后 fallback
- 简化的引用消息图片处理，消除脆弱的路径转换依赖

---

### 2026-05-04: 发誓功能新增 /clear 清除誓言

**问题描述**：
- 需要提供一种方式清除自己的誓言记录

**修改方案**：
- 在 `plugins/arteta_swear.py` 的 `handle_swear()` 中新增 `/clear` 判断
- 当输入 `发誓 /clear`（不区分大小写）时，删除该用户的所有誓言记录
- 空誓言（没有誓言可清除）和清除成功分别给予不同回复

**修改位置**：
- 文件：`plugins/arteta_swear.py`
- 函数：`handle_swear()` - 在解析 content 后增加 `/CLEAR` 判断分支

**部署方式**：
- 通过 `supervisorctl restart arteta_bot` 热重启
- Supervisor 管理，`autorestart=true`

---

### 2026-05-05: HTML+KaTeX+Playwright 渲染管道 + 提示词修复

**问题描述**：
- `/算法` 命令涉及数学公式（如积分中值定理证明），PIL 方案无法渲染 LaTeX 公式
- LLM 输出的公式用 `$$...$$` 包裹，在 KaTeX 中变成块级展示，连短公式和逗号都独占一行

**解决过程**：

#### 阶段 1：渲染管道建立

**新增文件**：
- `plugins/arteta_render.py` - 共享渲染模块，含 PIL 回退方案和 HTML 渲染器
- `templates/arteta_render.html` - HTML 模板，集成 KaTeX + highlight.js + marked.js

**新增函数（`arteta_render.py`）**：
- `html_to_image()` - 使用 Playwright 将 HTML 转为 PNG 截图
- `needs_html_render()` - 检测文本是否需要 HTML 渲染（公式或代码块）
- `normalize_math_delimiters()` - 将 `\(...\)` / `\[...\]` 统一为 KaTeX 兼容的 `$...$` / `$$...$$`
- `text_to_tactical_board()` - 原有 PIL 方案（回退用）
- `close_browser()` - 清理 Playwright 浏览器实例

**修改文件**：
- `plugins/arteta_chat.py`：
  - `handle_algo()` - 新增 `/算法` 命令处理
  - `process_chat()` - 渲染决策路由：`needs_html_render()` → `html_to_image()` → fallback `text_to_tactical_board()`
  - `ARTETA_PROMPT` - 添加数学公式和代码渲染纪律

**爬坑记录**：

1. **Python 3.13 raw string tokenizer bug (Windows)**：`r"\\\["` 在 Windows 上产生 2 个反斜杠而非 3 个。修复：使用 `chr(92)` 拼接绕过。
2. **`quality=95` + `type="png"` 冲突**：Playwright 的 `quality` 参数仅支持 JPEG。修复：移除 `quality=95`。
3. **f-string 的 `{dy}{dx}` 崩溃**：`f"$\\frac{dy}{dx}$"` 中 `{dy}` 被 Python 视为表达式。修复：改用普通字符串 `"$\\frac{{dy}}{{dx}}$"`。
4. **缺少 Playwright 浏览器**：服务器上 `playwright install chromium` 未运行，Chromium 缺失 165MB。修复：`playwright install --with-deps chromium` 下载并安装系统依赖。

#### 阶段 2：提示词修复（公式渲染优化）

**问题**：LLM 被要求全部使用 `$$...$$`（块级展示），导致短公式也独占一行。

**修改位置**（`plugins/arteta_chat.py`）：
- 第 83 行（ARTETA_PROMPT）：区分行内公式用 `$...$`，独立公式用 `$$...$$`
- 第 1148-1155 行（`handle_algo()` 的 `algo_prompt`）：同样区分规则

**当前状态**：✅ `/算法` 公式渲染正常工作，HTML 截图支持 KaTeX 公式 + 代码高亮 + PIL 回退

**服务器信息**：
- Playwright Chromium 安装路径：`/home/arteta/.cache/ms-playwright/chromium-1140`
- 系统依赖：xvfb, libgtk-3, libnss3, libx11-xcb 等 14 个包已安装

---

### 2026-05-05: 修复 arteta_help.py 文件损坏

**问题描述**：
- 上次删除 quiz 功能并更新帮助指令列表时，写入操作导致 `arteta_help.py` 被破坏
- 文件膨胀到 2.6MB，全部是重复的垃圾内容
- 没有有效的 Python 语法结构，Plugin 无法加载
- 输入"帮助"没有任何响应（命令找不到处理器）

**修复方案**：

**修改文件**：
- `plugins/arteta_help.py` — 完全重写（从 2.6MB 垃圾内容恢复为 2KB 有效代码）

**修复内容**：
1. 重写整个文件，包含所有当前活跃指令的帮助说明
2. 涵盖指令：A/塔子、算法/amath、cmath、画图、发誓、我的誓言、好感度、档案、盒、英超局势、刷新情报、下放/禁言
3. 使用 HTML 渲染（含公式和代码高亮）或 PIL 回退渲染帮助图片

**部署步骤**：
1. 本地语法验证通过
2. SCP 上传到服务器 `/opt/arteta_bot/plugins/arteta_help.py`
3. `supervisorctl restart arteta_bot` 重启

**爬坑记录**：
- 首次部署后运行时报错 `NameError: name 'MessageSegment' is not defined` — 缺少 `MessageSegment` 导入
- 修复后二次部署，验证通过

**当前状态**：✅ `/帮助` 指令正常工作

---

### 2026-05-06: 合并理科指令入口 + 好感度系统改造 + 好感度排行柱状图

**修改一：合并数学/物理/算法指令入口**

- 将 `cmath`/`物理`/`数学`/`计算` 独立指令移除，全部合并到 `/算法`（`algo_cmd`）
- 修改文件：`plugins/arteta_chat.py`（`algo_cmd` 新增别名）、`plugins/arteta_cmath.py`（移除命令注册）、`plugins/arteta_help.py`（更新帮助文本）

**修改二：爱憎分明好感度系统**

- **三级关键词检测**（重度 -200~-100 / 中度 -100~-40 / 轻度 -40~-10 / 正常 +10~+50 / 正面 +50~+200）
- **LLM Prompt 增强**：三段式回复纪律指令，6 个等级从热情到愤怒逐步升级
- **等级阈值调整**：传奇队长 ≥500 / 核心首发 ≥200 / 一线队 ≥50 / 青训生 ≥0 / 预备队 ≥-50 / 看台内鬼 <-50
- 管理员不参与好感度变动
- 修改文件：`plugins/arteta_chat.py`（`update_and_get_player()`、`process_chat()`、`handle_fav()`）

**修改三：新增 `/好感度排行` 指令**

- 使用 matplotlib 绘制横向柱状图，显示 TOP 10（红色柱）和 BOTTOM 10（灰色柱）两张图
- 管理员柱子显示金色
- 昵称超出 8 字自动截断
- 新增函数：`favorability_bar_chart()`（`arteta_render.py`）
- 新增命令：`rank_cmd`（`arteta_chat.py`）
- 别名：`排行`、`ranking`、`信任度排行`

**爬坑记录**：
1. **matplotlib 颜色值范围**：`(219, 0, 7)` 是 0-255 范围，matplotlib 要求 0-1。修复：改用 hex 字符串 `'#DB0007'`
2. **LaTeX 渲染冲突**：`arteta_cmath.py` 全局设置 `text.usetex=True`，导致柱状图中中文昵称被 LaTeX 渲染失败。修复：在 `favorability_bar_chart()` 中用 `try/finally` 临时关闭 `usetex`

**部署状态**：
- ✅ 所有修改已部署到服务器（`118.178.140.171`）
- ✅ PID 237996 运行中，所有插件加载成功
- ✅ 零报错

---

### 2026-05-06: 人格优化项目（Function Calling + 知识库 + Prompt 重构）

**问题诊断**：
- 过度强调比赛比分（`fetch_global_intel()` 每次回复注入赛果）
- "端水"倾向（prompt 强调积极心态，缺乏观点鲜明指令）
- 重复老故事（灯泡演讲等写死在 prompt）

**解决方案**：三大子系统

#### 子系统 A：Function Calling
**新增文件**：`plugins/arteta_tools.py`

DeepSeek 原生 tool use，注册 5 个工具让 LLM 按需调用：

| Tool | 触发场景 | 数据源 |
|------|---------|--------|
| `get_arsenal_result` | "赢了没？"、"比分" | football-data.org |
| `get_pl_table` | "排第几"、"积分榜" | football-data.org |
| `get_arsenal_injuries` | "厄德高伤了吗" | DuckDuckGo（英文搜索） |
| `search_news(q)` | "转会传闻"、"新闻" | DuckDuckGo（英文搜索词） |
| `get_football_knowledge(topic)` | "什么是内收型边后卫" | 本地知识库 |

**核心函数**：
- `register_config(**kwargs)` — 注入 API 配置
- `call_deepseek_tool(messages)` — 单次 DeepSeek API 调用（含 tools 参数）
- `execute_tool_call(tc)` — 分发执行具体工具
- `run_tool_loop(user_messages)` — 完整调用循环（最多 5 轮），发送→tool_call→执行→回送→...→最终回复

#### 子系统 B：本地知识库
**新增文件**：`plugins/arteta_knowledge.py`

关键词匹配引擎，按文件名→内容频率→标题分级评分，返回最佳匹配文件内容。

**新增目录**：`knowledge_base/`（截止目前）

| 文件 | 内容 |
|------|------|
| `glossary.md` | 7 个战术术语（内收型边后卫、2-3-5、高位逼抢、第 6 人、肋部、能量、连线） |
| `documentary/01-locker-room-speeches.md` | 灯泡演讲、大脑心脏演讲、标准训话 |
| `tactics/01-inverted-fullback.md` | 内收型边后卫详解+球员分析（已 web-access 丰富） |
| `tactics/02-high-press.md` | 三线压迫系统+压迫模式+赛季演变（已 web-access 丰富） |
| `tactics/03-attacking-patterns.md` | 2-3-5 进攻站位+肋部进攻+边路三角+第 6 人（已 web-access 丰富） |
| `press/01-classic-quotes.md` | 转会/信任/态度/process 四类语录 |

**待 web-access 完成补充**：`press/02-post-match.md`、`philosophy/02-player-development.md`

#### 子系统 C：Prompt 重写

**修改位置**：`plugins/arteta_chat.py`

1. **ARTETA_PROMPT 重写**（第 79-104 行）：
   - 移除三个固定故事（灯泡/大脑心脏/标准训话 → 移入知识库）
   - 移除"绝对排版纪律"（严禁列表/严禁小标题）
   - 增加"观点要鲜明，不要端水，不要打官腔"
   - 增加"不要反复讲同一个故事"
   - 增加 `get_football_knowledge` 工具引用指引
   - 保留：正面回答、引用消息分析、信任度标注、数学公式/代码渲染

2. **process_chat() 改造**（第 1067-1143 行）：
   - 移除 `fetch_global_intel()` 被动数据注入
   - 移除 `intel_section` 构建
   - 移除 6 级回复纪律表格（传奇队长/核心首发/一线队/青训生/预备队/看台内鬼）
   - 替换为简化 `base_prompt` + `run_tool_loop()` 函数调用
   - 渲染逻辑不变（html_to_image / PIL 回退）

3. **配置注入**：`register_tools_config()` 在 `init_db_safely()` 后调用

#### 修改汇总

| 操作 | 文件 |
|------|------|
| 新增 | `plugins/arteta_tools.py` |
| 新增 | `plugins/arteta_knowledge.py` |
| 新增 | `knowledge_base/` 目录（7 个 .md 文件） |
| 修改 | `plugins/arteta_chat.py`（import、配置注入、process_chat、ARTETA_PROMPT） |

#### 设计文档
- 设计文档：`docs/superpowers/specs/2026-05-06-arteta-personality-optimization-design.md`
- 实施计划：`docs/superpowers/plans/2026-05-06-arteta-personality-optimization.md`
- Session 记录：`docs/session-2026-05-06-personality-optimization.md`

#### 当前进度
- ✅ 代码全部完成（`arteta_tools.py`、`arteta_knowledge.py`、`arteta_chat.py` 修改）
- ✅ 知识库已收集发布会话术和战术分析
- ⏳ 纪录片资料待补充（web-access agent 未完成）
- 🔴 待部署到服务器

#### 部署状态
- 🔴 等待纪录片资料补充完成后部署

---

### 2026-05-06: 人格优化项目部署 + 多项修复与改进

**部署人格优化项目（22:00-22:36）**：
- 上传 `arteta_tools.py`、`arteta_knowledge.py`、`arteta_chat.py` 到服务器
- 上传 `knowledge_base/` 目录（9 个 .md 文件）
- 修复 Python 3.8 兼容性：`dict[str, str]` → `Dict[str, str]`，`list[...]` → `List[...]` 等
- 修复 `FinishedException` 被 `except Exception` 误捕获导致多余报错

**新增 `画图-pro` 命令（gpt-image-2）**：
- 文件：`plugins/arteta_image.py`、`.env.dev`、`.env.prod`
- 新增命令 `画图-pro`（别名 `画图pro`、`画图2`），使用 `https://www.boxying.com/v1/images/generations`
- 新增配置项：`IMAGE2_API_KEY`、`IMAGE2_API_URL`、`IMAGE2_MODEL`
- 爬坑：Supervisor 设置 `ENVIRONMENT=prod`，配置必须写在 `.env.prod` 而非 `.env.dev`

**修复 DeepSeek reasoning_content 错误**：
- 文件：`plugins/arteta_tools.py`
- DeepSeek thinking 模式下返回的 `reasoning_content` 字段必须在 function calling 循环后续轮次原样传回
- `call_deepseek_tool()` 中新增保留 `reasoning_content` 的逻辑

**好感度排行柱状图改进**：
- 文件：`plugins/arteta_chat.py`、`plugins/arteta_render.py`
- 管理员不参与球员排名（单独剔除，避免数值过高压扁柱状图）
- 反转 Y 轴顺序，好感度高的排在图表顶部
- 昵称不再截断 8 字限制，左侧边距根据最长昵称自动调整

**好感度系统加强**：
- 文件：`plugins/arteta_chat.py`
- 负面关键词大幅扩充（重度/中度/轻度各新增约 10 个关键词）
- 惩罚力度加大：重度 `-250~-120`、中度 `-150~-60`、轻度 `-60~-15`
- Prompt 信任度标注指令重写：必须写明具体数值，禁止「一些」「一点」等模糊表述

---

### 2026-05-07: 好感度系统重写（LLM 标记评估 + 关键词辅助）

**问题**：
- 纯关键词匹配太脆弱，创意型辱骂（"塔牲""董卓""塔嗨"等变形词）全部漏过
- 关键词列表再长也赶不上用户的创造力
- 默认 `else` 分支给中立/负面消息加好感度，不合理

**方案**：参考 `astrbot_backup` 项目的标记系统，改为 LLM 评估为主、关键词为辅助的双重架构。

#### 改动详情

**文件**：`plugins/arteta_chat.py`

**1. 新增好高度标记系统（替代关键词主检测）**：
```python
FAVOR_MARKERS = {
    "【好感度+++】": (380, 770, "令人惊叹的表现，极大提升了信任度"),
    "【好感度++】": (200, 370, "出色的交流，大幅提升了信任度"),
    "【好感度+】": (10, 190, "积极的互动，提升了信任度"),
    "【好感度=】": (0, 0, ""),
    "【好感度-】": (-190, -10, "不当言行，降低了信任度"),
    "【好感度--】": (-370, -200, "严重的负面言行，大幅降低了信任度"),
    "【好感度---】": (-770, -380, "极端恶劣的言行，信任度严重受损"),
}
```

**2. ARTETA_PROMPT 第 3 条重写**：从"信任度标注"改为"输出好感度标记的死命令"，要求 LLM 在回复末尾独立输出 `【好感度+】` 等七种标记之一。

**3. 新增 `extract_favor_marker(text)`**：从 LLM 回复中用正则提取最后一个好感度标记。

**4. 重构 `update_and_get_player()` → `get_player_data()` + `apply_favor_change()`**：
- `get_player_data()`：只获取当前数据 + 更新昵称历史（去掉关键词检测）
- `apply_favor_change()`：在 LLM 回复后调用，根据标记计算 delta 并更新数据库

**5. 流程重塑**：
- 之前：关键词检测 → 算好感度 → 告诉 LLM → LLM 回复
- 现在：获取当前数据 → LLM 回复（含标记）→ 提取标记 → 计算好感度 → 更新数据库 → 追加红字

**6. 关键词降级为辅助检测**（`check_keyword_penalty()`）：
- 保留之前的关键词列表，但改为在 LLM 评估基础上额外扣分
- 重度词额外 `-80~-40`、中度 `-40~-15`、轻度 `-20~-5`
- 无标记时好感度不变（不再默认加 10~50）

**7. 红字由代码保证**：
- `inc>0` → `[red]【信任度上升X点 - 原因】[/red]`
- `inc<0` → `[red]【信任度下降X点 - 原因】[/red]`
- `inc=0` → `[red]【信任度无变化】[/red]`
- 不再依赖 LLM 自觉输出

**部署状态**：
- ✅ 本地开发完成
- ✅ 三次部署到服务器 `/opt/arteta_bot/plugins/arteta_chat.py`
- ✅ 插件加载成功，零报错
- ✅ PID 244714 → 244748 → 最新 PID 运行中

---

### 2026-05-07: 图片识别 fallback 修复 + 点赞功能 + 群成员认知系统

#### A. 图片识别 fallback 条件修复

**问题**：
- `analyze_image_base64()` 中 fallback 判断条件 `not result.startswith("[图片识别失败")` 漏掉了 `[图片识别异常` 前缀
- SiliconFlow 超时时返回 `[图片识别异常：]`，被当成"成功结果"直接返回，备用 API 永远不会被调用
- 异常消息为空：`asyncio.TimeoutError()` 在 Python 3.8 中 `str()` 返回 `""`

**修复**：
- 添加 `_is_error()` 辅助函数，同时检查 `[图片识别失败` 和 `[图片识别异常` 两种前缀
- `except` 改为 `{type(e).__name__}: {e}`，避免空消息

**修改文件**：`plugins/arteta_chat.py`
**修改函数**：`analyze_image_base64()`, `_call_vision_api()`

#### B. QQ 名片赞功能

**新增文件**：`plugins/arteta_like.py`

**新增命令**：`赞我` / `点赞我` / `like_me`

**实现细节**：
- 每日限额：普通用户 10 次，VIP 用户 50 次
- VIP 检测：调用 `get_group_member_info` 检查 `is_vip`/`vip_level`，群管理/群主自动 VIP
- 数据库 `daily_likes` 表记录每日点赞次数
- 成功点赞时随机输出阿尔特塔风格鼓励语录（13 条）
- 额度用尽时输出调侃语录（6 条）
- API 不可用时优雅报错

#### C. 群成员认知系统

**目标**：让阿尔特塔认识群里的每一个人，了解成员关系。

**数据库扩展**（`arsenal_data.db`）：
- 新增 `member_relations` 表：记录成员间的回复/@ 互动关系

**互动追踪**（`process_chat()`）：
- 用户回复某人消息 → 记录一次互动
- 用户 @ 某人 → 记录一次互动
- 跳过自己 @ 自己和 @ 机器人自身

**新增 Function Calling 工具**（`plugins/arteta_tools.py`）：

| 工具 | 触发场景 | 返回 |
|------|---------|------|
| `get_group_members(group_id)` | 想知道群里都有谁 | 近24h活跃球员：昵称、身份、好感度、发言数 |
| `get_member_relations(group_id, user_id)` | 想了解球员间关系 | 该球员跟谁互动最多，谁最爱找他互动 |

**Prompt 增强**：
- ARTETA_PROMPT 第 4b 条：告诉塔子哥可以用这两个工具了解更衣室
- `base_prompt` 自动注入 `【更衣室概况】`：近24h活跃球员快照（top 8）
- base_prompt 注入群号

#### D. Bug Fix

`UnboundLocalError: local variable 'chain_text' referenced before assignment`
- 原因：新增的互动追踪代码引用了 `chain_text`，但该变量只在有引用消息时才被赋值
- 修复：在 reply 检测前初始化 `chain_text = ""`

**部署状态**：
- ✅ 文件：`plugins/arteta_chat.py`、`plugins/arteta_tools.py`、`plugins/arteta_like.py` 全部上传
- ✅ 数据库：`daily_likes`、`member_relations` 表创建成功
- ✅ 所有插件加载成功，零报错
- ✅ PID 247045 → 248160 → 248381 运行中

---

### 2026-05-09: 阿森纳周报功能（自动爬取新闻 + LLM 生成 + 知识库注入 + 群发布）

**设计文档**：`docs/superpowers/specs/2026-05-09-weekly-news-design.md`
**实施计划**：`docs/superpowers/plans/2026-05-09-weekly-news.md`

**新增文件**：
- `plugins/arteta_weekly.py` — 周报独立插件（~400 行）
- `knowledge_base/weekly-news.md` — 周报知识库文件（运行时自动生成）

**修改文件**：
- `plugins/arteta_help.py` — 帮助文档添加周报命令

**功能概述**：

| 模块 | 函数 | 说明 |
|------|------|------|
| 新闻抓取 | `fetch_bbc_news()` | BBC Sport Arsenal 页面（ConnectTimeout，服务器无法连接） |
| 新闻抓取 | `fetch_sky_news()` | Sky Sports Arsenal 页面（正常工作） |
| 新闻抓取 | `fetch_guardian_news()` | The Guardian Arsenal 页面（正常工作） |
| 正文抓取 | `fetch_article_content()` | 提取 `<p>` 标签文本，每篇最多 500 字 |
| 去重排序 | `fetch_arsenal_news()` | 三源异步并发 → 去重 → Top 8 |
| LLM 生成 | `generate_weekly_report()` | DeepSeek API，阿尔特塔风格更衣室周报 |
| 知识库 | `save_to_knowledge_base()` | 写入 `knowledge_base/weekly-news.md` |
| 知识库 | `clear_cache()` | 写入后清除知识库缓存，LLM 聊天立即命中 |
| 群发布 | `publish_to_groups()` | `text_to_tactical_board()` 渲染图片 → 全群发 |
| 定时任务 | `weekly_news_job()` | APScheduler cron 每周一 09:00 |
| 手动触发 | `handle_weekly_manual()` | `/周报` 命令，仅发当前群 |

**爬坑记录**：

1. **`str | None` 语法（Python 3.8）**：`-> str | None` 在 Python 3.8 不支持。修复：改为 `-> Optional[str]`。
2. **知识库缓存未失效**：`save_to_knowledge_base()` 写入后 `arteta_knowledge.py` 的 `_file_cache` 未清空，LLM 聊天看不到新周报。修复：写入后调用 `clear_cache()`。
3. **BBC 连接超时**：服务器无法连接 `bbc.com`（`ConnectTimeout`），异常消息为空字符串。修复：增加 `type(e).__name__` 日志、新增 Guardian 源补偿。
4. **`group_list` → `targets` 变量名遗漏**：重构 `publish_to_groups()` 支持单群发送时，将 `group_list` 改为 `targets`，但 try 块内漏改了一处，导致图片生成成功后发送循环抛出 `NameError`，然后回退发送纯文本。修复：统一为 `targets`。
5. **纯文本回退包含颜色标记**：图片渲染失败回退时，`final_text` 中包含 `[red]`/`[blue]` 标记。修复：回退前替换掉所有颜色标记。
6. **颜色标记跨行/未闭合**：LLM 输出的 `[red]...[/red]` 可能跨行或格式异常，`text_to_tactical_board` 的逐行正则无法匹配。修复：新增 `_clean_color_tags()` 预处理，跨行/未闭合标签自动去除。

**当前状态**：✅ 部署完成，`arteta_weekly` 插件加载成功。`/周报` 手动触发已测试通过。定时任务每周一 09:00 自动执行。


