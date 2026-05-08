# Arteta Bot 部署指南

## 目录

- [ECS 部署（推荐）](#ecs-部署推荐)
- [Docker 部署](#docker-部署)
- [部署后配置](#部署后配置)

---

## ECS 部署（推荐）

在阿里云 ECS（Ubuntu 22.04）上一键部署：

```bash
# 1. 上传项目到服务器后
cd /opt/arteta_bot

# 2. 编辑 deploy_ecs.sh 修改参数（DeepSeek Key 等）
# 3. 运行部署脚本
sudo bash deploy/deploy_ecs.sh

# 4. 安装 NapCat QQ
curl -o napcat.sh https://nclatest.znin.net/NapNeko/NapCat-Installer/main/script/install.sh
sudo bash napcat.sh

# 5. 配置 NapCat WebSocket
# 编辑 ~/napcat/config/onebot11.json:
# { "ws_server": { "enable": true, "host": "127.0.0.1", "port": 8088 } }

# 6. 上传源码
# 将项目中的 bot.py、plugins/、data/ 上传到 /opt/arteta_bot/

# 7. 启动
supervisorctl start arteta_bot
```

### 进程管理

```bash
supervisorctl status arteta_bot        # 查看状态
supervisorctl restart arteta_bot       # 重启
supervisorctl tail -f arteta_bot       # 查看日志
```

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

---

## 部署后配置

### 安全组规则

阿里云控制台 → 安全组 → 添加入方向：

| 端口 | 用途 | 建议 |
|------|------|------|
| 8088 | OneBot WebSocket | 仅允许 127.0.0.1（同机部署则不开） |
| 22 | SSH | 仅允许你的 IP |

### 数据库备份

ECS 部署已自动配置每日备份到 `/opt/arteta_bot_backups/`，保留 7 天。

Docker 部署的数据库在 `deploy/bot_data/arsenal_data.db`，请自行配置备份。

### 日志

- ECS: `/var/log/arteta_bot/{error,access}.log`
- Docker: `docker-compose logs -f arteta-bot`
