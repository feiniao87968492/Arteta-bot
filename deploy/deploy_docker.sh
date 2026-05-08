#!/usr/bin/env bash
# ============================================================
# Arteta Bot - Docker 部署脚本
# 适用: 阿里云 ECS / 轻量应用服务器 (需预装 Docker)
# ============================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${CYAN}[INFO]${NC} $1"; }
ok()    { echo -e "${GREEN}[OK]${NC} $1"; }

# ---- 检查 Docker ----
if ! command -v docker &>/dev/null; then
    info "正在安装 Docker..."
    curl -fsSL https://get.docker.com | bash
    systemctl enable docker && systemctl start docker
    ok "Docker 安装完成"
fi

if ! command -v docker-compose &>/dev/null; then
    info "正在安装 Docker Compose..."
    curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    chmod +x /usr/local/bin/docker-compose
    ok "Docker Compose 安装完成"
fi

# ---- 配置参数 ----
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# ---- 环境变量提示 ----
if [ -z "${DEEPSEEK_API_KEY:-}" ]; then
    echo ""
    echo -e "${YELLOW}⚠  请设置环境变量后再运行:${NC}"
    echo "  export DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    echo "  export FOOTBALL_API_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxx"
    echo "  export SUPERUSERS='[\"2648955710\"]'"
    echo ""
    echo "  或者创建 .env 文件:"
    echo "  cat > $PROJECT_DIR/deploy/.env << 'EOF'"
    echo "  DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    echo "  FOOTBALL_API_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxx"
    echo "  SUPERUSERS=[\"2648955710\"]"
    echo "  EOF"
    echo ""
    exit 1
fi

# ---- 创建持久化目录 ----
mkdir -p "$PROJECT_DIR/deploy/napcat"
mkdir -p "$PROJECT_DIR/deploy/bot_data"

# ---- 启动服务 ----
info ">>> 构建并启动容器..."
cd "$SCRIPT_DIR"
docker-compose --env-file .env up -d --build

ok "服务已启动"
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Arteta Bot Docker 部署完成${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "查看日志:"
echo -e "  ${CYAN}docker-compose logs -f arteta-bot${NC}    # 机器人日志"
echo -e "  ${CYAN}docker-compose logs -f napcat${NC}       # NapCat 日志"
echo ""
echo -e "进入 NapCat 扫码登录:"
echo -e "  ${CYAN}docker attach napcat${NC}"
echo ""
echo -e "常用命令:"
echo -e "  ${CYAN}docker-compose restart arteta-bot${NC}   # 重启机器人"
echo -e "  ${CYAN}docker-compose down${NC}                 # 停止所有服务"
echo -e "  ${CYAN}docker-compose pull${NC}                 # 更新 NapCat 镜像"
echo ""
