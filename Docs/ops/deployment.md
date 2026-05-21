# Arteta Bot 部署指南

## 目录

- [前置条件](#前置条件)
- [本地部署](#本地部署)
- [ECS 部署（推荐）](#ecs-部署推荐)
- [Docker 部署](#docker-部署)
- [进程管理](#进程管理)
- [安全组规则](#安全组规则)
- [数据库备份](#数据库备份)
- [日志查看](#日志查看)

---

## 前置条件

- Python 3.8+
- QQ 号（用于 NapCat QQ 登录）
- DeepSeek API Key
- football-data.org API Token（免费，[申请地址](https://www.football-data.org/)）
- NapCat QQ（OneBot V11 协议实现，[官方文档](https://napcat.napneko.com/)）

---

## 本地部署

```bash
# 1. 克隆仓库
git clone https://github.com/feiniao87968492/Arteta-bot.git
cd Arteta-bot

# 2. 安装依赖
pip install nonebot2 nonebot-adapter-onebot nonebot-plugin-apscheduler httpx aiosqlite pillow pilmoji duckduckgo_search loguru

# 3. 配置环境变量
cp .env.dev .env
# 编辑 .env，填入你的 API Key：
#   - DEEPSEEK_API_KEY：DeepSeek API 密钥
#   - FOOTBALL_API_TOKEN：football-data.org API 令牌
#   - SUPERUSERS：管理员 QQ 号列表

# 4. 安装 NapCat QQ
# 参考 https://napcat.napneko.com/ 安装 NapCat 并配置 WebSocket

# 5. 启动机器人
python bot.py
```

---

## ECS 部署（推荐）

在阿里云 ECS（Ubuntu 22.04）上一键部署：

```bash
# 1. 上传项目到服务器
# 将 bot.py、plugins/、data/ 等文件上传到 /opt/arteta_bot/

# 2. 编辑部署脚本参数
# 编辑 deploy/deploy_ecs.sh，修改以下参数：
#   - DEEPSEEK_API_KEY：你的 DeepSeek API 密钥
#   - FOOTBALL_API_TOKEN：football-data.org API 令牌
#   - SUPERUSERS：管理员 QQ 号列表

# 3. 运行部署脚本
sudo bash deploy/deploy_ecs.sh

# 4. 安装 NapCat QQ
curl -o napcat.sh https://nclatest.znin.net/NapNeko/NapCat-Installer/main/script/install.sh
sudo bash napcat.sh

# 5. 配置 NapCat WebSocket
# 编辑 ~/napcat/config/onebot11.json，设置 ws_server：
# { "ws_server": { "enable": true, "host": "127.0.0.1", "port": 8088 } }

# 6. 启动机器人
supervisorctl start arteta_bot
```

部署脚本会自动完成以下操作：
- 安装系统依赖（Python 3、pip、venv、git、supervisor 等）
- 创建运行用户 `arteta`
- 创建项目目录和日志目录
- 配置 Python 虚拟环境并安装依赖
- 生成 `.env.prod` 配置文件
- 配置 Supervisor 进程守护
- 设置目录权限
- 配置 SQLite 数据库每日备份

---

## Docker 部署

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

Docker 部署脚本会自动安装 Docker 和 Docker Compose（如未安装），创建持久化数据目录，并启动所有容器。

常用 Docker 命令：

```bash
docker-compose logs -f arteta-bot    # 查看机器人日志
docker-compose logs -f napcat        # 查看 NapCat 日志
docker-compose restart arteta-bot    # 重启机器人
docker-compose down                  # 停止所有服务
docker-compose pull                  # 更新 NapCat 镜像
```

Docker 部署的数据库位于 `deploy/bot_data/arsenal_data.db`，请自行配置备份。

---

## 进程管理

ECS 部署使用 Supervisor 管理机器人进程：

```bash
supervisorctl status arteta_bot         # 查看运行状态
supervisorctl restart arteta_bot        # 重启机器人
supervisorctl start arteta_bot          # 启动机器人
supervisorctl stop arteta_bot           # 停止机器人
supervisorctl tail -f arteta_bot        # 实时查看日志
```

Supervisor 配置位于 `/etc/supervisor/conf.d/arteta_bot.conf`，包含自动重启策略（最多重试 3 次）。

---

## 安全组规则

阿里云控制台 → 安全组 → 添加入方向规则：

| 端口 | 用途 | 建议 |
|------|------|------|
| 8088 | OneBot WebSocket | 仅允许 127.0.0.1（同机部署则不开） |
| 22 | SSH | 仅允许你的公网 IP |

---

## 数据库备份

ECS 部署已自动配置每日备份：

- **备份路径**：`/opt/arteta_bot_backups/`
- **备份文件**：`arsenal_data_YYYYMMDD.db`
- **保留策略**：保留最近 7 天，旧备份自动删除
- **备份脚本**：`/etc/cron.daily/arteta_bot_backup`

备份脚本内容：

```bash
#!/bin/bash
BACKUP_DIR="/opt/arteta_bot_backups"
mkdir -p "$BACKUP_DIR"
cp /opt/arteta_bot/arsenal_data.db "$BACKUP_DIR/arsenal_data_$(date +\%Y\%m\%d).db"
find "$BACKUP_DIR" -name "arsenal_data_*.db" -mtime +7 -delete
```

---

## 日志查看

### ECS 部署

机器人日志位于 `/var/log/arteta_bot/` 目录：

```bash
# 错误日志
tail -f /var/log/arteta_bot/error.log

# 访问日志
tail -f /var/log/arteta_bot/access.log

# 使用 Supervisor 查看
supervisorctl tail -f arteta_bot
```

### Docker 部署

```bash
docker-compose logs -f arteta-bot    # 机器人日志
docker-compose logs -f napcat        # NapCat 日志
```
