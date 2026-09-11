"""插件加载冒烟(验收①):import 无语法错 + 注册面完整 + key 链装配。"""
import importlib
import json
import os
import tempfile

import helpers as H  # noqa: F401  注入 stub 路径
from astrbot.api.event import filter as stub_filter

# main.py 用包内相对导入(AstrBot 按包加载插件),测试同构:命名空间包导入
plugin_main = importlib.import_module("astrbot_plugin_groupportrait.main")


def test_package_registered():
    cls = plugin_main.GroupPortraitPlugin
    assert cls._registered[0] == "astrbot_plugin_groupportrait"


def test_command_surface_registered():
    cls = plugin_main.GroupPortraitPlugin
    for name in ("group_portrait", "bind_portrait", "rebind_portrait", "unbind_portrait",
                 "admin_bind", "admin_unbind", "view_portrait"):
        fn = getattr(cls, name)
        assert getattr(fn, "_is_command", False), f"{name} 未注册为命令"
    assert cls.group_portrait._permission == (stub_filter.PermissionType.ADMIN,)
    assert cls.admin_bind._permission == (stub_filter.PermissionType.ADMIN,)
    assert getattr(cls.on_group_message, "_event_message_type", None)


def test_instantiation_smoke():
    inst = plugin_main.GroupPortraitPlugin(plugin_main.Context(), config={})
    assert os.path.isdir(inst.data_dir)
    assert "{{max_characters}}" in inst.pipeline.system_template
    assert inst.pipeline.max_characters == 4


def test_api_key_chain():
    old_env = os.environ.pop("RUNNINGHUB_API_KEY", None)
    try:
        inst = plugin_main.GroupPortraitPlugin(plugin_main.Context(), config={})
        # 链尾 key_file:本机存在(hermes 基建)则非空,不存在则空串,均不得抛
        assert isinstance(inst._resolve_api_key(), str)
        # env 兜底
        os.environ["RUNNINGHUB_API_KEY"] = "envkey123"
        assert inst._resolve_api_key() == "envkey123"
        # 配置最优先
        inst2 = plugin_main.GroupPortraitPlugin(plugin_main.Context(), config={"rh_api_key": "cfgkey"})
        assert inst2._resolve_api_key() == "cfgkey"
        os.environ.pop("RUNNINGHUB_API_KEY")
        # key_file 兜底文件
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            json.dump({"apiKey": "filekey456"}, f)
        inst3 = plugin_main.GroupPortraitPlugin(plugin_main.Context(), config={"rh_key_file": path})
        assert inst3._resolve_api_key() == "filekey456"
        os.unlink(path)
    finally:
        if old_env is not None:
            os.environ["RUNNINGHUB_API_KEY"] = old_env
        else:
            os.environ.pop("RUNNINGHUB_API_KEY", None)


def test_build_rh_node_map_from_config():
    inst = plugin_main.GroupPortraitPlugin(plugin_main.Context(), config={
        "rh_api_key": "k", "rh_webapp_id": "wf1",
        "node_refs": "5,6,7,8",
    })
    rh = inst._build_rh()
    assert rh.ref_node_ids == ["5", "6", "7", "8"]
    assert rh.node_map["prompt"] == {"node": "19", "field": "value"}
    assert rh.node_map["seed"] == {"node": "10", "field": "noise_seed"}
    assert rh.api_key == "k" and rh.webapp_id == "wf1"


def test_terminate_runs():
    inst = plugin_main.GroupPortraitPlugin(plugin_main.Context(), config={})
    asyncio_run = __import__("asyncio").run
    asyncio_run(inst.terminate())
