"""终验:真实 AstrBot v4.28.0(venv 发行版本体) 走 WebUI 上传安装同款代码路径
PluginManager.install_plugin_from_file,对真·GitHub zipball 真装+真加载。
"""
import asyncio
import os
import sys
import tempfile

os.environ["ASTRBOT_ROOT"] = tempfile.mkdtemp(prefix="astrbot_root_")
os.chdir(os.environ["ASTRBOT_ROOT"])
sys.path.insert(0, os.getcwd())  # 真启动时 AstrBot 根在 sys.path,插件按 data.plugins.<名> 导入

ZIP = "/tmp/astrbot_repro/astrbot_plugin_groupportrait-main.zip"


async def main():
    from importlib.metadata import version as _v
    VERSION = _v("astrbot")
    from astrbot.core.star.star_manager import PluginManager
    from astrbot.core.star.star import star_map, star_registry

    print(f"AstrBot 版本: {VERSION}")

    class StubContext:
        """PluginManager 只做属性挂载(_star_manager/StarTools._context),桩即可。"""

        def get_all_stars(self):
            from astrbot.core.star.star import star_registry

            return list(star_registry)

        def get_registered_star(self, dir_name: str):
            from astrbot.core.star.star import star_map, star_registry

            for m in star_registry:
                if m and getattr(m, "root_dir_name", None) == dir_name:
                    return star_map.get(m.module_path)
            return None

    pm = PluginManager(StubContext(), None)
    os.makedirs(pm.plugin_store_path, exist_ok=True)  # 正式启动时框架自建,这里补齐

    print(f"安装前插件数: {len(star_map)}")
    result = await pm.install_plugin_from_file(ZIP)
    print(f"install_plugin_from_file 返回: {result!r}"[:400])

    print("=" * 60)
    hit = None
    for m in star_registry:
        if m and getattr(m, "name", "") == "astrbot_plugin_groupportrait":
            hit = m
    if hit is None:
        print("!!! 插件列表中未找到 astrbot_plugin_groupportrait")
        sys.exit(1)

    print("插件已在 AstrBot 插件列表中出现且成功加载:")
    print(f"  name        = {hit.name}")
    print(f"  version     = {hit.version}")
    print(f"  author      = {hit.author}")
    print(f"  desc        = {hit.desc[:60]}...")
    print(f"  activated   = {hit.activated}")
    print(f"  root_dir    = {hit.root_dir_name}")
    handlers = getattr(hit, "star_handler_fullnames", None) or []
    print(f"  注册处理器数 = {len(list(handlers))}")

    # 落盘结构核验
    store = pm.plugin_store_path
    installed_dir = os.path.join(store, "astrbot_plugin_groupportrait")
    names = sorted(os.listdir(installed_dir))
    print(f"  安装目录内容 = {names}")
    assert "metadata.yaml" in names, "metadata.yaml 未落盘"
    assert "main.py" in names, "main.py 未落盘"
    print("=" * 60)
    print("终验结论: 真装成功 + 列表可见 + 加载成功 (v4.28.0 真实代码路径)")


asyncio.run(main())
