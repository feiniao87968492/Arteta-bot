# plugins/arteta_standings.py
import nonebot
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, MessageSegment
import httpx
import json
import re
from datetime import datetime
from plugins.arteta_render import text_to_tactical_board

# --- 1. 获取全局配置 ---
driver = nonebot.get_driver()
try:
    config = driver.config.model_dump()
except AttributeError:
    config = driver.config.dict()

FOOTBALL_API_TOKEN = str(config.get("football_api_token", "da24063a4040404c89250b601f8994a2")).strip('"\'')
DEEPSEEK_API_KEY = str(config.get("deepseek_api_key", "")).strip('"\'')
ARSENAL_ID = 57

# --- 2. 注册指令 ---
standings_cmd = on_command("英超局势", aliases={"积分榜", "英超排名", "局势"}, priority=5, block=True)

# --- 3. 核心逻辑：获取数据并请求 AI ---
@standings_cmd.handle()
async def handle_standings(bot: Bot, event: MessageEvent):
    await bot.send(event, "稍等，我正在调取最新的英超积分榜并分析各路诸侯的局势...")

    headers = {"X-Auth-Token": FOOTBALL_API_TOKEN}
    current_time = datetime.now().strftime('%Y年%m月%d日')
    
    try:
        async with httpx.AsyncClient(verify=False, timeout=15.0) as client:
            res_pl = await client.get("https://api.football-data.org/v4/competitions/PL/standings", headers=headers)
            
            if res_pl.status_code != 200:
                await standings_cmd.finish("情报部门（API）失去联系，无法获取当前积分榜。")
                return
                
            table = res_pl.json()['standings'][0]['table']
    except Exception as e:
        await standings_cmd.finish(f"情报获取失败：{str(e)}")
        return

    # 1. 组装发给 AI 的完整纯数据 (供其思考)
    ai_data_str = "【当前完整积分榜数据】：\n"
    for t in table:
        ai_data_str += f"第{t['position']}名: {t['team']['shortName']}, 积分:{t['points']}, 净胜球:{t['goalDifference']}\n"

    # 2. 组装给球迷看的精美可视化文本 (直接展示在前排)
    display_text = f"[red]📊 英超实时积分榜 (截至 {current_time})[/red]\n\n"

    for t in table:
        pos = t['position']
        color_tag = "red" if t['team']['id'] == ARSENAL_ID else "blue"
        # 按区域分组显示
        if pos == 1:
            display_text += "[blue]【争冠 / 欧战区】[/blue]\n"
        elif pos == 7:
            display_text += "\n[blue]【中游球队】[/blue]\n"
        elif pos == 18:
            display_text += "\n[blue]【残酷的降级区】[/blue]\n"

        display_text += f"[{color_tag}]{t['position']}. {t['team']['shortName']} | {t['points']}分 (场{t['playedGames']}/净{t['goalDifference']})[/{color_tag}]\n"
        
    # 关键球队排名
    KEY_TEAM_IDS = {57: "阿森纳", 64: "利物浦", 61: "切尔西", 65: "曼城", 66: "曼联"}
    key_rankings = {}
    for t in table:
        tid = t['team']['id']
        if tid in KEY_TEAM_IDS:
            key_rankings[KEY_TEAM_IDS[tid]] = {'pos': t['position'], 'pts': t['points'], 'gd': t['goalDifference']}

    display_text += "[red]【关键球队排名】[/red]\n"
    for name, info in sorted(key_rankings.items(), key=lambda x: x[1]['pos']):
        color_tag = "red" if name == "阿森纳" else "blue"
        display_text += f"[{color_tag}]{name}: 第{info['pos']}名 | {info['pts']}分 (净胜球{info['gd']})[/{color_tag}]\n"

    display_text += "\n---\n\n"

    # 3. 呼叫大模型进行战局分析
    ai_prompt = (
        "你现在是阿森纳主教练米克尔·阿尔特塔。站在更衣室里，拿着上面这份最新的积分榜向全队做局势分析。"
        "任务要求：\n"
        "1. 点评【争冠局势】：谁在领跑，谁咬得很紧，分差如何，阿森纳机会怎么样。\n"
        "2. 点评【争四/欧冠资格】：哪几支球队在为了前四死磕。\n"
        "3. 点评【保级泥潭】：快速指出哪几支球队深陷降级区面临毁灭边缘。\n"
        "4. 必须提到利物浦、切尔西、曼城、曼联这四支球队的具体排名和表现。\n"
        "绝对纪律：\n"
        "1. 严禁使用任何列表符号（如 *、-、1. 2. 3.）。不要分条列点，用激情的自然段落串联起来！\n"
        '2. 严禁使用小标题。不要输出"争冠局势分析："这种机械的废话。\n'
        "3. 控制在500字以内，语气必须极其严肃、充满激情和危机感！"
    )

    try:
        async with httpx.AsyncClient(timeout=80.0) as client:
            resp = await client.post("https://api.deepseek.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "deepseek-v4-flash", 
                    "messages": [
                        {"role": "system", "content": ai_prompt},
                        {"role": "user", "content": ai_data_str}
                    ],
                    "temperature": 0.7
                }
            )
            
            if resp.status_code == 200:
                analysis = resp.json()["choices"][0]["message"]["content"]
                # 拼接：上方是绝对准确的积分榜数据，下方是主教练的激情演讲
                final_text = display_text + analysis
                
                # 画图并发送
                img_bytes = text_to_tactical_board(final_text)
                await standings_cmd.finish(MessageSegment.image(img_bytes))
            else:
                await standings_cmd.finish(f"阿尔特塔正在气头上，拒绝发言 (API 状态码 {resp.status_code})。")
    except Exception as e:
        await standings_cmd.finish(f"更衣室通讯中断：{str(e)}")