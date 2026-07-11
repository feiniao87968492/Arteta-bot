"""DEPRECATED: standalone Premier League standings command.

The old `英超局势` / `积分榜` command used football-data.org directly and
registered a dedicated NoneBot matcher at import time. Real-time football
questions now flow through the main Arteta agent and its GrokSearch-backed web
tools, so this module intentionally does not register any command handlers.
"""

DEPRECATED = True
