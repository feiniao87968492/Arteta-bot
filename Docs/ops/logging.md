# 日志系统

## 1. 架构概览

日志系统基于 **loguru**，通过 **InterceptHandler** 桥接标准库 `logging`，实现统一日志输出。

```
标准 logging（NoneBot 自身/旧插件）
        │
        ▼
  InterceptHandler ──→ loguru ──→ 文件 sink（DEBUG+，10MB 轮转，5 个保留）
                                    │
                                    └──→ 终端 sink（生产 INFO+ / 开发 DEBUG+，彩色）
```

所有日志最终汇总到两个 sink，由 `bot.py` 中的 `setup_logging()` 统一配置。

## 2. InterceptHandler

`InterceptHandler` 继承 `logging.Handler`，将标准 logging 的 `LogRecord` 转发到 loguru：

```python
class InterceptHandler(logging.Handler):
    def emit(self, record):
        logger_opt = logger.opt(depth=6, exception=record.exc_info)
        logger_opt.log(record.levelno, record.getMessage())
```

关键细节：

- **depth=6**：loguru 需要向上追溯 6 层调用栈才能找到真正发起日志调用的代码位置（而非 InterceptHandler 内部）。这是 loguru 官方推荐值，适配标准 logging 的调用栈深度。
- **exception=record.exc_info**：将标准 logging 的异常信息（`record.exc_info`）传递给 loguru，使 loguru 能够打印完整 Traceback。如果 `record.exc_info` 为 `None`（无异常），loguru 自动忽略。

## 3. 文件 sink

```python
logger.add(
    log_file,                        # 路径见下
    rotation="10 MB",                # 单文件超过 10MB 自动轮转
    retention=5,                     # 保留最近 5 个文件
    level="DEBUG",                   # 记录 DEBUG 及以上
    encoding="utf-8",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<7} | {name}:{line} | {message}",
)
```

- **路径**：生产环境 `/opt/arteta_bot/logs/arteta_bot.log`，开发环境 `<项目根>/logs/arteta_bot.log`
- **level=DEBUG**：文件 sink 始终为 DEBUG 级别，兜底一切日志
- **轮转**：10MB 触发轮转，保留最近 5 个文件（.log, .log.1, ..., .log.4）
- **格式**：时间精确到毫秒 | 级别左对齐 7 字符 | 模块名:行号 | 消息体

## 4. 终端 sink

```python
logger.add(
    sys.stdout,
    level="INFO" if is_prod else "DEBUG",   # 生产 INFO+ / 开发 DEBUG+
    colorize=True,
    format="<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level> | <cyan>{module:<15}</cyan> | <level>{message}</level>",
)
```

- **终端级别**：生产环境只输出 INFO 及以上（减少干扰）；开发环境输出 DEBUG 及以上
- **彩色化**：时间绿色、级别按等级着色（TRACE=白, DEBUG=青, INFO=绿, WARNING=黄, ERROR=红, CRITICAL=红底）、模块名青色、消息体按等级着色
- **简短格式**：时间仅 HH:mm:ss，不含日期，适合实时 tail

## 5. 环境切换

环境由环境变量 `ENVIRONMENT` 控制：

| 特性 | `ENVIRONMENT=prod` | 其他（默认） |
|------|-------------------|-------------|
| 文件路径 | `/opt/arteta_bot/logs/arteta_bot.log` | `<项目根>/logs/arteta_bot.log` |
| 终端级别 | `INFO` | `DEBUG` |

## 6. 使用方式

### 新插件

直接在文件中导入并使用 loguru logger：

```python
from loguru import logger

logger.info("插件已加载")
logger.debug("调试信息: {}", variable)
logger.error("请求失败: {}", e)
```

loguru 支持 `{}` 占位符格式，自动处理类型转换，避免 `%` 格式化或 f-string。

### 旧插件（仍使用标准 logging）

项目中有 5 个插件仍使用 `import logging; logger = logging.getLogger(__name__)`：

- `plugins/arteta_chat.py`
- `plugins/arteta_daily.py`
- `plugins/arteta_like.py`
- `plugins/arteta_tools.py`
- `plugins/arteta_weekly.py`

这些插件的日志通过 InterceptHandler 自动桥接到 loguru，无需修改代码。日志格式、文件输出、终端输出完全与 loguru 一致。

### 日志级别对照

| 标准 logging | loguru | 使用场景 |
|-------------|--------|---------|
| `logging.debug()` | `logger.debug()` | 调试信息，变量值 |
| `logging.info()` | `logger.info()` | 常规操作，启动/完成 |
| `logging.warning()` | `logger.warning()` | 预期内的异常 |
| `logging.error()` | `logger.error()` | 非预期错误 |
| `logging.critical()` | `logger.critical()` | 致命错误 |
| — | `logger.trace()` | 更详细的调试（loguru 独有） |

## 7. 查看方式

### 通过 supervisorctl（生产环境，推荐）

```bash
# 实时跟踪日志
supervisorctl tail -f arteta_bot

# 查看最后 100 行
supervisorctl tail arteta_bot

# 查看 stdout + stderr
supervisorctl tail -f arteta_bot stderr
```

### 直接 tail 日志文件

```bash
# 实时跟踪
tail -f logs/arteta_bot.log

# 查看最后 50 行
tail -50 logs/arteta_bot.log

# 按关键字过滤
grep "ERROR" logs/arteta_bot.log

# 只查看某个插件的日志
grep "arteta_chat" logs/arteta_bot.log

# 查看轮转的历史日志
tail -50 logs/arteta_bot.log.1
```

### 文件位置

| 环境 | 路径 |
|------|------|
| 生产（ECS） | `/opt/arteta_bot/logs/arteta_bot.log` |
| 本地开发 | `<项目根>/logs/arteta_bot.log` |

## 8. 示例输出

```
2026-05-10 14:30:15.123 | INFO    | bot:51       | Loguru 日志系统已初始化
2026-05-10 14:30:15.345 | INFO    | arteta_memory:42 | ChromaDB 连接成功，集合: group_memories
2026-05-10 14:30:15.678 | WARNING | arteta_weekly:99 | [WeeklyNews] BBC 抓取异常: ConnectTimeout:
2026-05-10 14:30:16.012 | ERROR   | arteta_chat:411   | [图片识别失败：HTTP 403 body=Forbidden]
```

各字段说明：

| 字段 | 示例 | 说明 |
|------|------|------|
| 时间 | `2026-05-10 14:30:15.123` | 精确到毫秒，文件 sink 包含日期 |
| 级别 | `INFO` | 左对齐 7 字符 |
| 模块 | `arteta_memory:42` | 文件名 + 行号，定位代码位置 |
| 消息 | `ChromaDB 连接成功...` | 实际日志内容 |

终端显示的格式不同（仅 HH:mm:ss，彩色，模块名最多 15 字符），但信息量相同。
