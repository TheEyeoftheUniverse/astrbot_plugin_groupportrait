"""复现:真实 AstrBot v4.28.0 安装器对目标仓库的 GitHub 导入安装。

走 inspect_repository —— WebUI「从 GitHub 导入」在装包前的元数据预检,
报错文案与主开发者所见同源。
"""
import asyncio
import sys
import traceback

sys.path.insert(0, "/tmp/astrbot-v4280")

TARGET = "https://github.com/TheEyeoftheUniverse/astrbot_plugin_groupportrait"
CONTROL = "https://github.com/Soulter/helloworld/tree/master"


async def main():
    from astrbot.core.star.updater import _PluginUpdater

    updater = _PluginUpdater()

    print("=" * 60)
    print("[1] 目标仓库(私有) 匿名 GitHub 导入预检:")
    try:
        result = await updater.inspect_repository(TARGET)
        print(f"    意外成功: {result}")
    except Exception as e:
        print(f"    异常类型: {type(e).__name__}")
        print(f"    报错原文: {e}")

    print("=" * 60)
    print("[2] 对照组(公开插件仓库) 同一安装器:")
    try:
        result = await updater.inspect_repository(CONTROL)
        print(f"    成功: name={result.get('name')!r} version={result.get('version')!r}")
    except Exception as e:
        print(f"    异常类型: {type(e).__name__}")
        print(f"    报错原文: {e}")
        traceback.print_exc()

    print("=" * 60)
    print("[3] 目标仓库 git clone 通道(非 github.com 域名才走 git,此处仅证明匿名 clone 不可行):")
    from astrbot.core.repository import parse_repository_url

    ref = parse_repository_url(TARGET)
    print(f"    transport 判定 = {ref.transport!r}  (archive=匿名HTTP抓取, git=git clone)")


asyncio.run(main())
