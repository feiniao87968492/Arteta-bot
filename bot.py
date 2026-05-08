# bot.py (外层启动入口)
import nonebot
from nonebot.adapters.onebot.v11 import Adapter

nonebot.init()
driver = nonebot.get_driver()
driver.register_adapter(Adapter) # 注册通信协议

# 核心战术：加载 plugins 文件夹下的所有助理教练（插件）
nonebot.load_plugins("plugins")

if __name__ == "__main__":
    nonebot.run()