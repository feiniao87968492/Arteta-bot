# Arteta Bot — 阿森纳 QQ 群聊机器人

基于 NoneBot2 + OneBot V11 协议的 QQ 群聊机器人，以阿森纳主教练米克尔·阿尔特塔（Mikel Arteta）的身份与群成员互动。

内置 DeepSeek 大语言模型对话、本地知识库、英超积分查询、AI 图片生成、好感度系统、誓言系统等功能。

## 功能

### AI 对话
**指令:** `A` / `塔子` / `阿尔特塔` + 消息内容

以阿尔特塔风格与群友聊天、聊球、讨论战术。接入 DeepSeek API，支持 Function Calling 实时获取阿森纳比赛结果、英超积分榜、伤病信息、搜索新闻等。

### 理科解题
**指令:** `算法` / `数学` / `物理` / `计算` + 题目

调用 DeepSeek 模型解题，并使用 LaTeX 引擎渲染为图片输出，支持高等数学、算法、物理等复杂公式推导。

### AI 图片生成
**指令:** `画图` + 画面描述

通过 gpt-image-2 模型根据文字描述生成图片。

**指令:** `图生图` + 修改要求（需回复/附带图片）

基于参考图片进行二次生成。

### 英超积分榜
**指令:** `英超局势` / `积分榜` / `英超排名`

从 football-data.org 获取实时积分榜数据，调用 AI 生成阿尔特塔风格的局势分析，渲染为图片输出。

### 好感度系统
- **指令:** `好感度` — 查看自己的信任度数值和队内定位
- **指令:** `档案` [@某人] — 查看自己或队友的详细档案
- **指令:** `盒` [@某人] — 查看队友信息
- **指令:** `好感度排行` / `排行` — 查看信任度排行

基于 SQLite 持久化存储，记录群成员的活跃度和互动数据。

### QQ 名片点赞
**指令:** `赞我` / `点赞我`

自动为群成员点赞。普通成员每日 10 次，群管理员/群主/VIP 成员每日 50 次（基于 NapCat send_like API）。

### 誓言系统
**指令:** `发誓` + 目标内容 — 立下誓言，记录在战术笔记中
**指令:** `我的誓言` — 查看自己立下的所有誓言
**指令:** `发誓 /CLEAR` — 清除誓言

### 本地知识库
在 `knowledge_base/` 目录下的 Markdown 文件中存储阿尔特塔的战术理念、发布会语录、哲学思想等，AI 对话时可自动检索引用。

### 球队管理（仅管理员）
**指令:** `下放` / `禁言` / `红牌` [@某人]

将违纪成员禁言 10 分钟并扣除信任度（需机器人为群管理员）。

### 帮助菜单
**指令:** `帮助` / `menu` / `指令`

显示所有可用指令。

## 部署方法

### 前置要求

- Python 3.8+
- QQ 号（用于 NapCat 登录）
- DeepSeek API Key
- football-data.org API Token（免费，[申请地址](https://www.football-data.org/)）

### 本地部署

```bash
# 1. 克隆仓库
git clone https://github.com/feiniao87968492/Arteta-bot.git
cd Arteta-bot

# 2. 安装依赖
pip install nonebot2 nonebot-adapter-onebot nonebot-plugin-apscheduler httpx aiosqlite pillow pilmoji duckduckgo_search

# 3. 配置环境变量
cp .env.dev .env
# 编辑 .env，填入你的 API Key

# 4. 安装 NapCat QQ
# 参考 https://napcat.napneko.com/ 安装 NapCat 并配置 WebSocket

# 5. 启动机器人
python bot.py
```

### Docker 部署

```bash
# 1. 创建 .env 文件
cat > deploy/.env << 'EOF'
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx
FOOTBALL_API_TOKEN=xxxxxxxxxxxxxxxx
SUPERUSERS=["2648955710"]
EOF

# 2. 运行部署脚本
bash deploy/deploy_docker.sh

# 3. 进入 NapCat 容器扫码登录 QQ
docker attach napcat
```

### ECS（阿里云）部署

```bash
# 1. 上传项目到服务器后
cd /opt/arteta_bot

# 2. 编辑 deploy_ecs.sh 修改参数
# 3. 运行部署脚本
sudo bash deploy/deploy_ecs.sh

# 4. 安装 NapCat QQ
curl -o napcat.sh https://nclatest.znin.net/NapNeko/NapCat-Installer/main/script/install.sh
sudo bash napcat.sh

# 5. 配置 NapCat WebSocket
# 编辑 ~/napcat/config/onebot11.json:
# { "ws_server": { "enable": true, "host": "127.0.0.1", "port": 8088 } }

# 6. 启动
supervisorctl start arteta_bot
```

### 字体文件

本项目使用微软雅黑字体（`msyh.ttc`）进行图片渲染。字体文件未包含在仓库中，请自行从 Windows 系统目录 `C:\Windows\Fonts\msyh.ttc` 复制到项目根目录，或使用其他中文字体并修改 `arteta_render.py` 中的 `FONT_PATH`。

## 项目结构

```
arteta_bot/
├── bot.py                    # 机器人启动入口
├── pyproject.toml            # 项目配置与依赖
├── .env.dev                  # 环境变量示例
├── plugins/
│   ├── arteta_chat.py        # AI 对话核心插件
│   ├── arteta_admin.py       # 管理员/禁言插件
│   ├── arteta_cmath.py       # 理科解题渲染插件
│   ├── arteta_help.py        # 帮助菜单插件
│   ├── arteta_image.py       # AI 图片生成插件
│   ├── arteta_knowledge.py   # 本地知识库检索
│   ├── arteta_like.py        # QQ 名片点赞插件
│   ├── arteta_render.py      # 图片渲染引擎
│   ├── arteta_standings.py   # 英超积分榜插件
│   ├── arteta_swear.py       # 誓言系统插件
│   └── arteta_tools.py       # Function Calling 工具
├── knowledge_base/           # 本地知识库目录
├── deploy/                   # 部署脚本与配置
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── deploy_docker.sh
│   ├── deploy_ecs.sh
│   └── deploy_remote.py
├── data/                     # 运行时数据（自动创建）
└── templates/                # HTML 渲染模板
```

## 技术栈

- **框架:** NoneBot2
- **协议:** OneBot V11（NapCat QQ）
- **LLM:** DeepSeek API
- **图片生成:** gpt-image-2 API
- **图片渲染:** Pillow / Pilmoji / Playwright
- **数据存储:** SQLite / aiosqlite
- **足球数据:** football-data.org API
- **网络搜索:** DuckDuckGo Search
