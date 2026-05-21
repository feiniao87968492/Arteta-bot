# Loguru 统一日志系统设计

## 概述

为 Arteta Bot 引入 loguru 作为统一日志框架，替换当前各插件各自为政的 `import logging` + `logging.getLogger(__name__)` 分散模式。

## 动机

- 5 个插件各自定义 logger，格式不统一（有的用 `[ModuleName]` 前缀，有的裸输出）
- `bot.py` 入口零日志配置，nonebot 自身日志与插件日志混杂
- `arteta_chat.py` 引用了 `logger.error(...)` 但从未定义 `logger`（潜在 NameError bug）
- 线上通过 `supervisorctl tail -f` 查看 stdout，无法分级过滤、没有轮转、没有独立文件
- 排查问题时需要在混杂输出中手动 grep

## 方案

### 依赖

新增 `loguru` 依赖。

### 配置入口

在 `bot.py` 中，`nonebot.init()` 之前配置 loguru。唯一配置点，后续所有插件自动继承。

### 核心配置

```python
import sys
import os
import logging
from loguru import logger

# 清除 loguru 默认 handler
logger.remove()

# 将标准 logging 重定向到 loguru
class InterceptHandler(logging.Handler):
    def emit(self, record):
        logger_opt = logger.opt(depth=6, exception=record.exc_info)
        logger_opt.log(record.levelno, record.getMessage())

logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

# 确保日志目录存在
LOG_DIR = "/opt/arteta_bot/logs" if os.getenv("ENVIRONMENT") == "prod" else os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

# 文件日志：DEBUG+，10MB 轮转，保留 5 个
logger.add(
    os.path.join(LOG_DIR, "arteta_bot.log"),
    rotation="10 MB",
    retention=5,
    level="DEBUG",
    encoding="utf-8",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<7} | {name}:{line} | {message}",
)

# 终端日志：生产 INFO+ / 开发 DEBUG+，彩色输出
logger.add(
    sys.stdout,
    level="INFO" if os.getenv("ENVIRONMENT") == "prod" else "DEBUG",
    colorize=True,
    format="<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level> | <cyan>{module:<15}</cyan> | <level>{message}</level>",
)
```

### 插件集成

**已有插件（5 个）：** 通过 `InterceptHandler` 自动捕获所有 `logging.getLogger(__name__)` 调用，无需修改代码。

**arteta_chat.py：** 修复缺失 logger 定义。该文件第 175 行使用 `logger.error(...)` 但从未 import。修复方式为在文件开头加入 `from loguru import logger`。

**新插件：** 直接使用 `from loguru import logger`，使用 loguru 原生语法。

### 本地开发 vs 线上生产

| 维度 | 本地开发 | 线上生产 |
|------|---------|---------|
| 终端日志级别 | DEBUG | INFO |
| 文件日志路径 | `<project>/logs/arteta_bot.log` | `/opt/arteta_bot/logs/arteta_bot.log` |
| 文件日志级别 | DEBUG | DEBUG |
| 颜色输出 | 开启 | 开启 |

通过 `ENVIRONMENT` 环境变量（已有 `.env` 配置）自动切换。

### 部署

首次部署需创建日志目录并设置权限：

```bash
mkdir -p /opt/arteta_bot/logs && chown arteta:arteta /opt/arteta_bot/logs
```

### 兼容性说明

- Python 3.8 兼容（loguru 0.7.x 支持 Python 3.8）
- nonebot 自身日志通过标准 logging 输出 → InterceptHandler 捕获 → loguru 统一格式
- `logging.basicConfig(force=True)` 需要 Python 3.8+，满足要求
- 现有 `%s` 风格格式化（如 `logger.warning("... %s", e)`）通过 `record.getMessage()` 正确处理

### 未涉及

- 日志远程推送（ELK、Sentry 等）— 后续可按需添加，loguru 有原生 `sink` 扩展点
- 日志染色/tracing ID — 当前无多服务链路追踪需求
