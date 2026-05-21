# Loguru 统一日志系统 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace scattered `import logging` with loguru-backed centralized logging — file rotation + terminal output with dev/prod differentiation.

**Architecture:** Single config point in `bot.py` + `InterceptHandler` bridging stdlib logging to loguru. All existing `logging.getLogger(__name__)` calls work unchanged.

**Tech Stack:** Python 3.8+, loguru 0.7.x

---

### Task 1: Add loguru config to bot.py

**Files:**
- Modify: `bot.py` (full rewrite, 15 lines → ~40 lines)

- [ ] **Step 1: Rewrite bot.py with loguru config**

Replace the current `bot.py` with:

```python
# bot.py (外层启动入口)
import sys
import os
import logging
import nonebot
from loguru import logger
from nonebot.adapters.onebot.v11 import Adapter


class InterceptHandler(logging.Handler):
    """将标准 logging 重定向到 loguru"""
    def emit(self, record):
        logger_opt = logger.opt(depth=6, exception=record.exc_info)
        logger_opt.log(record.levelno, record.getMessage())


def setup_logging():
    logger.remove()  # 清除 loguru 默认 stderr handler

    is_prod = os.getenv("ENVIRONMENT") == "prod"

    # 日志目录：生产走固定路径，开发走项目本地
    log_dir = "/opt/arteta_bot/logs" if is_prod else os.path.join(os.path.dirname(__file__), "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "arteta_bot.log")

    # 文件日志：DEBUG+，10MB 轮转，保留 5 个
    logger.add(
        log_file,
        rotation="10 MB",
        retention=5,
        level="DEBUG",
        encoding="utf-8",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<7} | {name}:{line} | {message}",
    )

    # 终端日志：生产 INFO+ / 开发 DEBUG+，彩色
    logger.add(
        sys.stdout,
        level="INFO" if is_prod else "DEBUG",
        colorize=True,
        format="<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level> | <cyan>{module:<15}</cyan> | <level>{message}</level>",
    )

    # 截获标准 logging → loguru
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)


if __name__ == "__main__":
    setup_logging()
    logger.info("Loguru 日志系统已初始化")

    nonebot.init()
    driver = nonebot.get_driver()
    driver.register_adapter(Adapter)
    nonebot.load_plugins("plugins")
    nonebot.run()
```

Key details:
- `InterceptHandler` 放在 `bot.py` 中（不抽独立文件，只在此处使用）
- `setup_logging()` 在 `nonebot.init()` 之前调用，确保插件加载时就已有日志配置
- `force=True` 确保覆盖任何其他插件可能设置的 logging 配置

- [ ] **Step 2: 本地测试 bot.py 启动不报错**

Run:
```bash
cd D:\Users\zty\arteta_bot
python bot.py 2>&1 | head -20
```

Expected: Loguru 初始化消息输出，无 ImportError 或语法错误。然后 Ctrl+C 中断。

- [ ] **Step 3: 确认 logs/ 目录已生成文件**

Run:
```bash
ls -la logs/
```

Expected: `arteta_bot.log` 存在，文件内容包含刚才的启动日志。

- [ ] **Step 4: Commit**

```bash
git add bot.py
git commit -m "feat: add loguru centralized logging in bot.py"
```

---

### Task 2: Fix missing logger in arteta_chat.py

**Files:**
- Modify: `plugins/arteta_chat.py`

- [ ] **Step 1: Add loguru import to arteta_chat.py**

在第 1 行 imports 区域末尾、`from typing import Optional` 之后，加入：

```python
from loguru import logger
```

现有第 175 行的 `logger.error(f"[WebSearch] DDGS 搜索失败: {e}")` 不需要改动，它引用的正是这个 `logger`。

- [ ] **Step 2: Commit**

```bash
git add plugins/arteta_chat.py
git commit -m "fix: add missing logger import in arteta_chat.py"
```

---

### Task 3: Install loguru locally

- [ ] **Step 1: 本地虚拟环境安装 loguru**

Run:
```bash
cd D:\Users\zty\arteta_bot
pip install loguru
```

Expected: Successfully installed loguru-0.7.3 (或类似版本)

---

### Task 4: Deploy to server

**Files:**
- Upload: `bot.py`, `plugins/arteta_chat.py`
- Server commands: pip install, mkdir, supervisorctl restart

- [ ] **Step 1: 上传修改文件到服务器**

Run:
```bash
ssh root@118.178.140.171 "mkdir -p /opt/arteta_bot/logs && chown arteta:arteta /opt/arteta_bot/logs"
scp bot.py root@118.178.140.171:/opt/arteta_bot/bot.py
scp plugins/arteta_chat.py root@118.178.140.171:/opt/arteta_bot/plugins/arteta_chat.py
```

- [ ] **Step 2: 服务器安装 loguru**

Run:
```bash
ssh root@118.178.140.171 "/opt/arteta_bot/venv/bin/pip install loguru"
```

Expected: Successfully installed loguru

- [ ] **Step 3: 重启机器人**

Run:
```bash
ssh root@118.178.140.171 "chown arteta:arteta /opt/arteta_bot/bot.py /opt/arteta_bot/plugins/arteta_chat.py && supervisorctl restart arteta_bot"
```

---

### Task 5: Verify

- [ ] **Step 1: 检查进程状态**

Run:
```bash
ssh root@118.178.140.171 "supervisorctl status && sleep 2 && supervisorctl status"
```

Expected: `arteta_bot RUNNING pid xxx`。如果两次状态都是 RUNNING 说明没有 crash-loop。

- [ ] **Step 2: 检查日志文件**

Run:
```bash
ssh root@118.178.140.171 "ls -la /opt/arteta_bot/logs/ && echo '---' && head -20 /opt/arteta_bot/logs/arteta_bot.log"
```

Expected: `arteta_bot.log` 存在，日志行格式为 `2026-05-10 ... | INFO    | bot | Loguru 日志系统已初始化`。

- [ ] **Step 3: 检查 nonebot 日志也被 loguru 接管**

Run:
```bash
ssh root@118.178.140.171 "grep -c 'nonebot' /opt/arteta_bot/logs/arteta_bot.log"
```

Expected: 输出 > 0（nonebot 自身的日志通过 InterceptHandler 进入了 loguru）

- [ ] **Step 4: 检查无报错**

Run:
```bash
ssh root@118.178.140.171 "grep -i 'error\|traceback\|exception' /opt/arteta_bot/logs/arteta_bot.log | tail -20"
```

Expected: 无启动相关的 ERROR/TRACEBACK 行。

---

### Rollback Plan

如果部署后 bot 启动失败：

```bash
# 回退 bot.py 到 git 版本
ssh root@118.178.140.171 "cd /opt/arteta_bot && git checkout bot.py"

# 或回退到备份
ssh root@118.178.140.171 "cp /opt/arteta_bot/plugins/arteta_chat.py.bak /opt/arteta_bot/plugins/arteta_chat.py"

# 重启回退
ssh root@118.178.140.171 "supervisorctl restart arteta_bot"
```
