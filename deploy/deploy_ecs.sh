#!/usr/bin/env bash
# ============================================================
# Arteta Bot - 阿里云 ECS 一键部署脚本
# 适用系统: Ubuntu 22.04 LTS
# 使用方式: chmod +x deploy_ecs.sh && sudo bash deploy_ecs.sh
# ============================================================
set -euo pipefail

# ---- 颜色输出 ----
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${CYAN}[INFO]${NC} $1"; }
ok()    { echo -e "${GREEN}[OK]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()   { echo -e "${RED}[ERR]${NC} $1"; }

# ---- 检查 root ----
if [[ $EUID -ne 0 ]]; then err "请使用 sudo 或 root 运行"; exit 1; fi

# ---- 配置参数（按需修改）----
BOT_DIR="/opt/arteta_bot"
BOT_USER="arteta"
DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY:-}"
FOOTBALL_API_TOKEN="${FOOTBALL_API_TOKEN:-da24063a4040404c89250b601f8994a2}"
SUPERUSERS="${SUPERUSERS:-[\"2648955710\"]}"

# ---- 1. 系统初始化 ----
info ">>> 更新系统包..."
apt update -y && apt upgrade -y

info ">>> 安装基础依赖..."
apt install -y python3 python3-pip python3-venv git wget unzip curl supervisor

ok "系统初始化完成"

# ---- 2. 创建运行用户 ----
if ! id "$BOT_USER" &>/dev/null; then
    useradd -m -s /bin/bash "$BOT_USER"
    ok "创建用户 $BOT_USER"
fi

# ---- 3. 准备项目目录 ----
info ">>> 准备项目目录..."
mkdir -p "$BOT_DIR"
mkdir -p "$BOT_DIR/data"
mkdir -p "$BOT_DIR/plugins"
mkdir -p /var/log/arteta_bot

# ---- 4. 设置 Python 虚拟环境 ----
info ">>> 配置 Python 虚拟环境..."
python3 -m venv "$BOT_DIR/venv"
source "$BOT_DIR/venv/bin/activate"

pip install --upgrade pip
pip install nonebot2 nonebot-adapter-onebot nonebot-plugin-apscheduler httpx aiosqlite pillow

ok "Python 依赖安装完成"

# ---- 5. 写入 .env 配置 ----
info ">>> 写入配置文件..."
cat > "$BOT_DIR/.env.prod" << EOF
HOST=0.0.0.0
PORT=8088
DEBUG=false
SUPERUSERS=${SUPERUSERS}
DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY}
COMMAND_START=["", "/"]
zhipu_api_key=""
FOOTBALL_API_TOKEN=${FOOTBALL_API_TOKEN}
BISON_USE_PIC=true
BISON_INIT_FILTER=true
EOF

echo "ENVIRONMENT=prod" > "$BOT_DIR/.env"
ok "配置文件写入完成"

# ---- 6. 写入 supervisor 配置 ----
info ">>> 配置 Supervisor 进程守护..."
cat > /etc/supervisor/conf.d/arteta_bot.conf << 'SUPERVISOR_EOF'
[program:arteta_bot]
command=%(ENV_BOT_DIR)s/venv/bin/python bot.py
directory=%(ENV_BOT_DIR)s
user=arteta
autostart=true
autorestart=true
startretries=3
stderr_logfile=/var/log/arteta_bot/error.log
stdout_logfile=/var/log/arteta_bot/access.log
environment=ENVIRONMENT="prod"
SUPERVISOR_EOF

# supervisor 不支持 %(ENV_X)s，直接替换为实际路径
sed -i "s|%(ENV_BOT_DIR)s|$BOT_DIR|g" /etc/supervisor/conf.d/arteta_bot.conf

supervisorctl reread && supervisorctl update
ok "Supervisor 配置完成"

# ---- 7. 设置目录权限 ----
chown -R "$BOT_USER":"$BOT_USER" "$BOT_DIR"
chown -R "$BOT_USER":"$BOT_USER" /var/log/arteta_bot
chmod 755 "$BOT_DIR"
ok "目录权限设置完成"

# ---- 8. 配置定时备份 ----
info ">>> 配置 SQLite 数据库每日备份..."
cat > /etc/cron.daily/arteta_bot_backup << 'CRON_EOF'
#!/bin/bash
BACKUP_DIR="/opt/arteta_bot_backups"
mkdir -p "$BACKUP_DIR"
cp /opt/arteta_bot/arsenal_data.db "$BACKUP_DIR/arsenal_data_$(date +\%Y\%m\%d).db"
find "$BACKUP_DIR" -name "arsenal_data_*.db" -mtime +7 -delete
CRON_EOF
chmod +x /etc/cron.daily/arteta_bot_backup
ok "定时备份配置完成"

# ---- 9. 输出部署说明 ----
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  部署完成！以下步骤需要手动操作${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "${YELLOW}1. 安装 NapCat QQ（OneBot 协议实现）：${NC}"
echo "   cd /opt"
echo "   curl -o napcat.sh https://nclatest.znin.net/NapNeko/NapCat-Installer/main/script/install.sh"
echo "   sudo bash napcat.sh"
echo ""
echo -e "${YELLOW}2. 配置 NapCat WS 服务端（编辑 ~/napcat/config/onebot11.json）：${NC}"
echo '   { "ws_server": { "enable": true, "host": "127.0.0.1", "port": 8088 } }'
echo ""
echo -e "${YELLOW}3. 启动机器人：${NC}"
echo "   supervisorctl start arteta_bot"
echo "   supervisorctl tail -f arteta_bot"
echo ""
echo -e "${YELLOW}4. 检查状态：${NC}"
echo "   supervisorctl status"
echo ""
echo -e "${YELLOW}5. 上传 bot.py 和 plugins/ 目录到 ${BOT_DIR}/${NC}"
echo ""
echo -e "${CYAN}日志文件: /var/log/arteta_bet/{error,access}.log${NC}"
echo -e "${CYAN}数据库备份: /opt/arteta_bot_backups/${NC}"
echo ""
echo -e "${YELLOW}⚠  安全组记得添加 8088 端口入方向规则${NC}"
echo ""
