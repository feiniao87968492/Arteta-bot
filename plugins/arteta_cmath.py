# plugins/arteta_cmath.py
import nonebot
from nonebot import on_command
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, MessageSegment
import httpx
import io
import re
from nonebot.exception import FinishedException

# --- 核心战术：启用系统级 LaTeX 渲染引擎 ---
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# 强制开启 usetex 模式
plt.rcParams.update({
    "text.usetex": True,
    "text.latex.preamble": (
        r"\usepackage{CJKutf8}"
        r"\usepackage{amsmath}"
        r"\usepackage{amssymb}"
        r"\usepackage{underscore}" # 处理下划线防止崩溃
    ),
    "font.family": "serif",
})

# --- 1. 获取全局配置 ---
driver = nonebot.get_driver()
try:
    config = driver.config.model_dump()
except AttributeError:
    config = driver.config.dict()

DEEPSEEK_API_KEY = str(config.get("deepseek_api_key", "")).strip('"\'')

# --- 2. 终极理科绘图引擎 (LaTeX 原生版) ---
# 注：cmath/物理/数学/计算 指令已合并到 arteta_chat.py 的 /算法 指令中
def generate_math_board(text: str) -> bytes:
    # 预处理：统一符号
    text = text.replace("$$", "$")
    # 去除 Markdown 的加粗，因为 LaTeX 的 CJK 环境对 \textbf 较敏感，直接用原生字体更稳
    text = text.replace("**", "") 
    
    # 针对 LaTeX 的转义：处理 & 符号，防止其被误认为 LaTeX 列分隔符
    text = text.replace("&", r"\&")

    # 创建一个加长版的画布，适应长篇推导
    fig = plt.figure(figsize=(12, 18), dpi=150)
    fig.patch.set_facecolor('#F8FAFC')

    # 构造 LaTeX 正文：严格保证 CJK -> minipage -> 文本 -> minipage -> CJK 的闭合顺序
    latex_body = (
        r"\begin{CJK*}{UTF8}{gbsn}"
        r"\Large "  # 设置大号字
        r"\begin{minipage}{0.9\textwidth}"
        r"\raggedright "  # 保持中文排版左对齐，避免奇怪的拉伸
        + text +
        r"\end{minipage}"
        r"\end{CJK*}"
    )

    try:
        # 1. 渲染标题
        title_latex = r"\begin{CJK*}{UTF8}{gbsn}\huge \textbf{ARSENAL FC | SCIENTIFIC ANALYSIS}\end{CJK*}"
        fig.text(0.5, 0.96, title_latex, ha='center', va='center', color='#DB0007')
        
        # 2. 绘制装饰红线
        line = plt.Line2D((0.05, 0.95), (0.94, 0.94), color='#DB0007', linewidth=3)
        fig.add_artist(line)

        # 3. 渲染正文
        fig.text(0.05, 0.92, latex_body, color='#1E293B', va='top', ha='left')
        
    except Exception as e:
        plt.close(fig)
        # 将底层 LaTeX 报错捕获并抛出，方便调试
        raise ValueError(f"LaTeX 引擎排版失败: {str(e)}")
    
    plt.axis('off')
    buf = io.BytesIO()
    # 增加边距，防止边缘切断
    plt.savefig(buf, format='png', bbox_inches='tight', pad_inches=0.6, facecolor=fig.get_facecolor())
    plt.close(fig)
    
    return buf.getvalue()

# --- 3. LaTeX 渲染引擎 (保留供后续复用) ---
# 问答核心逻辑已迁移至 arteta_chat.py handle_algo