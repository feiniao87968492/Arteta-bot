# 服务器环境配置

## 目录

- [Playwright Chromium 安装](#playwright-chromium-安装)
- [字体文件配置](#字体文件配置)
- [日志目录](#日志目录)
- [环境变量配置](#环境变量配置)

---

## Playwright Chromium 安装

项目中的图片渲染功能（积分榜、每日总结、解题渲染等）依赖 Playwright Chromium 浏览器。

```bash
# 安装 Playwright Chromium（含系统依赖）
playwright install --with-deps chromium
```

该命令会：

- 下载 Chromium 浏览器（约 165MB）
- 安装系统依赖库，包括：
  - `xvfb`（虚拟帧缓冲，用于无头渲染）
  - `libgtk-3`（GTK 图形库）
  - `libnss3`（Network Security Services 库）
  - 以及其他 Chromium 运行所需的系统库

> 如遇网络问题导致 Chromium 下载失败，可设置 Playwright 使用镜像源或手动下载 Chromium 并配置 `PLAYWRIGHT_BROWSERS_PATH` 环境变量。

---

## 字体文件

项目使用微软雅黑字体（`msyh.ttc`）进行图片渲染，以确保中文文本在渲染图片中的正确显示。

### 获取方式

从 Windows 系统复制字体文件：

```bash
# 在 Windows 系统上
# 字体文件位于 C:\Windows\Fonts\msyh.ttc
# 将 msyh.ttc 复制到项目根目录
```

### 配置

将 `msyh.ttc` 放置于项目根目录即可。如需使用其他中文字体，需修改 `plugins/arteta_render.py` 中的 `FONT_PATH` 变量。

> 注意：字体文件未包含在 Git 仓库中，每次部署后需手动放置。

---

## 日志目录

ECS 部署需要提前创建日志目录并设置正确的权限：

```bash
# 创建日志目录
mkdir -p /opt/arteta_bot/logs

# 设置目录所有者
chown arteta:arteta /opt/arteta_bot/logs

# 设置权限
chmod 755 /opt/arteta_bot/logs
```

部署脚本（`deploy/deploy_ecs.sh`）会自动创建 `/var/log/arteta_bot/` 目录并设置权限，此步骤为手动部署时的补充。

Supervisor 日志文件位置：

| 文件 | 路径 |
|------|------|
| 错误日志 | `/var/log/arteta_bot/error.log` |
| 访问日志 | `/var/log/arteta_bot/access.log` |

---

## 环境变量配置

### 运行模式

项目通过 `ENVIRONMENT` 环境变量区分部署环境：

```bash
# 设置运行环境为生产模式
export ENVIRONMENT=prod
```

### 配置文件

- **开发环境**：`.env.dev`（本地开发使用）
- **生产环境**：`.env.prod`（ECS 部署由 `deploy_ecs.sh` 自动生成）

### 环境变量说明

| 变量 | 说明 | 示例 |
|------|------|------|
| `ENVIRONMENT` | 运行环境 | `prod` |
| `HOST` | 监听地址 | `0.0.0.0` |
| `PORT` | 监听端口 | `8088` |
| `DEBUG` | 调试模式 | `false` |
| `SUPERUSERS` | 管理员 QQ 号列表 | `["2648955710"]` |
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 | `sk-xxxxxxxx` |
| `FOOTBALL_API_TOKEN` | football-data.org API 令牌 | `xxxxxxxx` |
| `COMMAND_START` | 命令前缀 | `["", "/"]` |
| `BISON_USE_PIC` | 长文本转图片发送 | `true` |
| `BISON_INIT_FILTER` | 启动时过滤旧消息 | `true` |
| `IMAGE_API_KEY` | 图片生成 API 密钥 | `sk-xxxxxxxx` |
| `IMAGE_API_URL` | 图片生成 API 地址 | `https://api.example.com` |
| `IMAGE_MODEL` | 图片生成模型 | `gpt-image-2` |
| `VISION_MODEL` | 图片识别模型 | `gpt-4o` |

### 初始配置步骤

1. 从 `.env.dev` 复制为 `.env`：

```bash
cp .env.dev .env
```

2. 编辑 `.env`，填入实际的 API Key 和配置参数
3. 设置 `ENVIRONMENT=prod` 以启用生产模式
