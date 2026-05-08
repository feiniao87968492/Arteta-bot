#!/usr/bin/env python3
"""
Arteta Bot - 阿里云 ECS 远程部署脚本
自动连接 ECS → 上传文件 → 安装环境 → 配置服务
"""
import os
import sys
import io
import getpass
import paramiko
from paramiko import SSHClient, AutoAddPolicy
from scp import SCPClient
import time

# Windows GBK 编码兼容
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ===== 配置 =====
ECS_HOST = "118.178.140.171"
ECS_PORT = 22
ECS_USER = "root"
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def print_step(msg):
    print(f"\n{'='*60}")
    print(f"  >> {msg}")
    print(f"{'='*60}")

def run_ssh(client, command, timeout=120):
    """执行 SSH 命令并打印输出"""
    print(f"  $ {command}")
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    exit_status = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    if out:
        for line in out.split("\n"):
            print(f"    {line}")
    if err and exit_status != 0:
        for line in err.split("\n"):
            print(f"    ERR: {line}")
    return exit_status, out, err

def upload_file(sftp, local_path, remote_path):
    """上传单个文件"""
    print(f"  Upload: {os.path.basename(local_path)} -> {remote_path}")
    sftp.put(local_path, remote_path)

def main():
    password = os.environ.get("ECS_PASSWORD") or getpass.getpass("请输入 ECS root 密码: ")

    print_step("连接 ECS")
    client = SSHClient()
    client.set_missing_host_key_policy(AutoAddPolicy())
    client.connect(ECS_HOST, port=ECS_PORT, username=ECS_USER, password=password, timeout=30)
    print("  [OK] SSH 连接成功")
    sftp = client.open_sftp()

    # ============================================
    # Step 1: 上传部署脚本
    # ============================================
    print_step("1/6 上传部署脚本")
    local_script = os.path.join(PROJECT_DIR, "deploy", "deploy_ecs.sh")
    remote_script = "/tmp/deploy_ecs.sh"
    upload_file(sftp, local_script, remote_script)
    run_ssh(client, f"chmod +x {remote_script}")

    # ============================================
    # Step 2: 运行部署脚本（装 Python/依赖/Supervisor）
    # ============================================
    print_step("2/6 执行系统初始化（安装 Python / Supervisor / 依赖）")
    exit_code, out, err = run_ssh(client, f"bash {remote_script}", timeout=300)
    if exit_code != 0:
        # 可能是 apt update 有些小错，继续
        print("  ⚠ 部署脚本有非零退出，继续执行...")

    # ============================================
    # Step 3: 上传机器人源码
    # ============================================
    print_step("3/6 上传机器人源码")
    # 先确保目录存在且有权限
    run_ssh(client, "mkdir -p /opt/arteta_bot/plugins /opt/arteta_bot/data /opt/arteta_bot/deploy")

    # 上传 bot.py
    upload_file(sftp, os.path.join(PROJECT_DIR, "bot.py"), "/opt/arteta_bot/bot.py")

    # 上传 plugins/
    plugins_dir = os.path.join(PROJECT_DIR, "plugins")
    for f in os.listdir(plugins_dir):
        if f.endswith(".py"):
            upload_file(sftp, os.path.join(plugins_dir, f), f"/opt/arteta_bot/plugins/{f}")

    # 上传 data/
    data_dir = os.path.join(PROJECT_DIR, "data")
    if os.path.exists(data_dir):
        for f in os.listdir(data_dir):
            local_f = os.path.join(data_dir, f)
            if os.path.isfile(local_f):
                upload_file(sftp, local_f, f"/opt/arteta_bot/data/{f}")

    # 上传字体文件（如有）
    for font in ["msyh.ttc", "msyhbd.ttc", "msyhl.ttc"]:
        font_path = os.path.join(PROJECT_DIR, font)
        if os.path.exists(font_path):
            upload_file(sftp, font_path, f"/opt/arteta_bot/{font}")

    # 设置权限
    run_ssh(client, "chown -R arteta:arteta /opt/arteta_bot")

    # ============================================
    # Step 4: 安装 Python 依赖
    # ============================================
    print_step("4/6 安装 Python 依赖")
    run_ssh(client, """
        cd /opt/arteta_bot && \
        ./venv/bin/pip install --upgrade pip && \
        ./venv/bin/pip install nonebot2 nonebot-adapter-onebot nonebot-plugin-apscheduler httpx aiosqlite pillow
    """, timeout=180)

    # ============================================
    # Step 5: 重启 Supervisor 启动机器人
    # ============================================
    print_step("5/6 启动机器人服务")
    run_ssh(client, "supervisorctl reread && supervisorctl update")
    run_ssh(client, "supervisorctl start arteta_bot")
    time.sleep(2)
    run_ssh(client, "supervisorctl status arteta_bot")

    # ============================================
    # Step 6: 安装 NapCat QQ（需要用户交互）
    # ============================================
    print_step("6/6 部署总结")
    print("""
  ┌─────────────────────────────────────────────┐
  │  部署完成！以下步骤需要手动完成：             │
  │                                             │
  │  1. SSH 登录 ECS：                          │
  │     ssh root@118.178.140.171               │
  │                                             │
  │  2. 安装 NapCat QQ（OneBot 协议层）：        │
  │     curl -o napcat.sh https://nclatest.znin.│
  │       net/NapNeko/NapCat-Installer/main/   │
  │       script/install.sh                    │
  │     sudo bash napcat.sh                    │
  │     （按提示扫码登录 QQ 号）                │
  │                                             │
  │  3. 配置 NapCat（编辑配置）：               │
  │     nano ~/napcat/config/onebot11.json     │
  │     改为：                                 │
  │     {                                       │
  │       "ws_server": {                        │
  │         "enable": true,                     │
  │         "host": "127.0.0.1",               │
  │         "port": 8088                        │
  │       }                                     │
  │     }                                       │
  │                                             │
  │  4. 检查机器人状态：                        │
  │     supervisorctl status arteta_bot         │
  │     supervisorctl tail -f arteta_bot        │
  │                                             │
  │  5. 日志文件：                              │
  │     /var/log/arteta_bot/error.log           │
  │     /var/log/arteta_bot/access.log          │
  │                                             │
  │  6. 数据库备份：                            │
  │     /opt/arteta_bot_backups/                │
  └─────────────────────────────────────────────┘
  """)

    sftp.close()
    client.close()
    print("  [OK] 远程部署完成！")

if __name__ == "__main__":
    # 检查 scp 模块
    try:
        from scp import SCPClient
    except ImportError:
        print("安装 scp 模块: pip install scp")
        os.system(f"{sys.executable} -m pip install scp")
        from scp import SCPClient
    main()
