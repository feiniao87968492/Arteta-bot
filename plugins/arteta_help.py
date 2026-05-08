# plugins/arteta_help.py
import nonebot
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, MessageSegment
from plugins.arteta_render import text_to_tactical_board, html_to_image, needs_html_render

help_cmd = on_command("帮助", aliases={"help", "menu", "指令", "命令"}, priority=1, block=True)


@help_cmd.handle()
async def handle_help(bot: Bot, event: MessageEvent):
    help_text = (
        "[red]*━━ 阿森纳战术指令板 ━━*[/red]\n\n"
        "[blue]*--- 战术部署与实战 ---*[/blue]\n"
        "A/塔子/阿尔特塔 [内容]：跟阿尔特塔讨论战术、聊球、扯淡，任何话题都能扔过来。\n"
        "算法 [题目]：让阿尔特塔现场解题——算法、数学、物理难题通通放马过来。\n"
        "画图 [画面描述]：让 AI 根据你的描述画一张图。\n\n"
        "[blue]*--- 更衣室纪律与信任度考核 ---*[/blue]\n"
        "发誓 [内容]：把你的目标钉在墙上！立帖为证，做不到就去坐板凳！\n"
        "我的誓言：调出你的备忘录，教练组会无情地检查你是否完成了承诺。\n"
        "好感度：查看你自己的队内定位和当前的信任度数值。\n"
        "赞我/点赞我：给 QQ 名片点赞！普通球员每日 10 次，会员球员 50 次。\n"
        "档案 [@某人]：查看自己或队友的详细档案。\n"
        "盒 [@某位队友]：调出他的更衣室档案，看看他是不是在偷懒。\n\n"
        "[blue]*--- 赛场与情报 ---*[/blue]\n"
        "英超局势/积分榜/英超排名：查看最新英超积分榜和局势分析。\n"
        "刷新情报：更新足球情报数据。\n\n"
        "[blue]*--- 球队管理（仅限教练组）---*[/blue]\n"
        "下放/禁言/红牌 [@某人]：将违纪球员下放预备队（禁言）。\n\n"
        "— 以上，去训练吧。"
    )

    if needs_html_render(help_text):
        img_bytes = await html_to_image(help_text)
    else:
        img_bytes = text_to_tactical_board(help_text)

    await help_cmd.finish(MessageSegment.image(img_bytes))
