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
