# plugins/arteta_swear.py
import json
import os
from pathlib import Path
from datetime import datetime
import nonebot
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, MessageEvent

# --- 1. 战术档案库配置 (本地数据持久化) ---
# 在机器人根目录自动创建一个 data 文件夹用来存数据
DATA_DIR = Path("data")
SWEARS_FILE = Path(os.environ.get("ARTETA_SWEARS_FILE", str(DATA_DIR / "arteta_swears.json")))
SWEARS_FILE.parent.mkdir(parents=True, exist_ok=True)

def load_swears() -> dict:
    """读取更衣室誓言档案"""
    if not SWEARS_FILE.exists():
        return {}
    try:
        with open(SWEARS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {}

def save_swears(data: dict):
    """把誓言死死钉在战术板上"""
    with open(SWEARS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# --- 2. 注册指令 ---
swear_cmd = on_command("发誓", aliases={"我要发誓", "立帖为证", "备忘录"}, priority=5, block=True)
check_swear_cmd = on_command("我的誓言", aliases={"誓言记录", "查看备忘录", "查誓言"}, priority=5, block=True)

# --- 3. 核心逻辑：记录誓言 ---
@swear_cmd.handle()
async def handle_swear(bot: Bot, event: MessageEvent):
    # 提取用户发誓的具体内容
    content = event.get_message().extract_plain_text().strip()

    # 去除可能携带的命令前缀
    for cmd in ["发誓", "我要发誓", "立帖为证", "备忘录"]:
        if content.startswith(cmd):
            content = content[len(cmd):].strip()
            break

    if not content:
        await swear_cmd.finish("（阿尔特塔皱起眉头）你想发什么誓？大声点！把你的目标清晰地写出来！\n格式：发誓 [你的目标]")
        return

    user_id = str(event.user_id)
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 清除誓言：输入 /clear 或 /CLEAR
    if content.upper() == "/CLEAR":
        all_swears = load_swears()
        if user_id not in all_swears or not all_swears[user_id]:
            await swear_cmd.finish("（阿尔特塔摊手）你根本就没有誓言，谈什么清除？别浪费训练时间，去跑两圈！")
            return
        del all_swears[user_id]
        save_swears(all_swears)
        await swear_cmd.finish(
            f"（阿尔特塔把你的那页从战术笔记上撕了下来，揉成团扔进垃圾桶）\n"
            f"行，你过去的承诺一笔勾销。但我警告你——我的更衣室里不需要懦夫！"
        )
        return

    # 读取、更新、保存
    all_swears = load_swears()
    if user_id not in all_swears:
        all_swears[user_id] = []

    all_swears[user_id].append({
        "time": current_time,
        "content": content
    })

    save_swears(all_swears)

    # 教练的激情回应
    reply = (
        f"（阿尔特塔死死盯着你的眼睛）\n"
        f"很好！我已经把这句话钉在科尔尼基地的黑板上了：\n"
        f"「{content}」\n\n"
        f"记住你今天（{current_time}）做出的承诺。如果做不到，下场比赛你就给我去预备队坐板凳！听到没有？！"
    )
    await swear_cmd.finish(reply)

# --- 4. 核心逻辑：查阅誓言 ---
@check_swear_cmd.handle()
async def handle_check_swear(bot: Bot, event: MessageEvent):
    user_id = str(event.user_id)
    all_swears = load_swears()

    if user_id not in all_swears or not all_swears[user_id]:
        await check_swear_cmd.finish("（翻开战术笔记）这里面根本没有你的名字！你还没有对这支球队、对我做出过任何承诺！现在就去给我定个目标！")
        return

    user_swears = all_swears[user_id]
    
    reply = "（阿尔特塔把战术笔记拍在你胸口）看看你小子都吹过什么牛：\n" + "-" * 20 + "\n"
    
    # 遍历该用户的所有誓言并格式化输出
    for idx, swear in enumerate(user_swears, 1):
        reply += f"[{idx}] {swear['time']}\n目标：{swear['content']}\n\n"
        
    reply += "-" * 20 + "\n告诉我，你都做到了吗？！没做到的今晚加练两小时！"
    
    await check_swear_cmd.finish(reply)