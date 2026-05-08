FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget unzip curl \
    && rm -rf /var/lib/apt/lists/*

# 复制项目文件
COPY . .

# 安装 Python 依赖
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir nonebot2 nonebot-adapter-onebot nonebot-plugin-apscheduler httpx aiosqlite pillow duckduckgo_search

# 创建非 root 用户
RUN useradd -m -u 1000 arteta && chown -R arteta:arteta /app
USER arteta

EXPOSE 8088

CMD ["python", "bot.py"]
