"""绑定族命令链路测试(经 main.py 适配层,stub 宿主)。"""
import asyncio
import importlib
import os
import tempfile

import helpers as H  # noqa: F401  注入 stub 路径
from astrbot.api.message_components import At, Image, Reply  # stub
from core.binding_store import BindingStore
from core.context_collector import ContextCollector

# main.py 用包内相对导入(AstrBot 按包加载插件),测试同构:命名空间包导入
plugin_main = importlib.import_module("astrbot_plugin_groupportrait.main")


def make_plugin(tmp):
    inst = plugin_main.GroupPortraitPlugin(plugin_main.Context(), config={})
    inst.store = BindingStore(tmp)
    inst.collector = ContextCollector()
    # 测试隔离:流水线指向同一 store/collector
    inst.pipeline.store = inst.store
    inst.pipeline.collector = inst.collector
    return inst


def drive(agen):
    async def go():
        outs = []
        async for r in agen:
            outs.append(r)
        return outs
    return asyncio.run(go())


def test_bind_via_recent_image_cache(tmp_path=None):
    with tempfile.TemporaryDirectory() as tmp:
        inst = make_plugin(tmp)
        pic = H.write_png(os.path.join(tmp, "阿明的图.png"))
        # 用户先发了图(监听器会喂进缓存)
        inst.collector.observe("2001", "1001", "阿明", "看我的立绘", image_urls=[pic])
        ev = H.FakeEvent(text="/立绘绑定")
        drive(inst.bind_portrait(ev))
        assert any(t == "plain" and "绑定成功" in r for t, r in ev.replies), ev.replies
        assert inst.store.get("1001")["nickname"] == "阿明"
        assert inst.store.path_of("1001").endswith("1001.png")


def test_bind_with_inline_image_component():
    with tempfile.TemporaryDirectory() as tmp:
        inst = make_plugin(tmp)
        pic = H.write_png(os.path.join(tmp, "inline.png"))
        ev = H.FakeEvent(comps=[Image(url=pic)], text="/立绘换绑")
        drive(inst.rebind_portrait(ev))
        assert any("绑定失败" not in r for t, r in ev.replies if t == "plain")
        assert inst.store.get("1001") is not None


def test_bind_reply_quote_via_onebot():
    with tempfile.TemporaryDirectory() as tmp:
        inst = make_plugin(tmp)
        pic = H.write_png(os.path.join(tmp, "quoted.png"))
        ev = H.FakeEvent(comps=[Reply(id=777)], text="/立绘绑定")
        ev.bot = H.FakeBot(msg_by_id={"777": {"message": [{"type": "image", "data": {"url": pic}}]}})
        drive(inst.bind_portrait(ev))
        assert any("来源:引用消息图片" in r for t, r in ev.replies if t == "plain")


def test_bind_no_image_found():
    with tempfile.TemporaryDirectory() as tmp:
        inst = make_plugin(tmp)
        ev = H.FakeEvent(text="/立绘绑定")
        drive(inst.bind_portrait(ev))
        assert any("没找到要绑定的图片" in r for t, r in ev.replies if t == "plain")
        assert inst.store.all() == {}


def test_admin_bind_and_clear_with_at():
    with tempfile.TemporaryDirectory() as tmp:
        inst = make_plugin(tmp)
        pic = H.write_png(os.path.join(tmp, "target.png"))
        ev = H.FakeEvent(sender_id="9999", nickname="管理员", role="admin",
                         comps=[At("1002"), Image(url=pic)], text="/立绘代绑 @1002")
        drive(inst.admin_bind(ev))
        assert inst.store.get("1002") is not None
        ev2 = H.FakeEvent(sender_id="9999", nickname="管理员", role="admin",
                          comps=[At("1002")], text="/立绘清绑 @1002")
        drive(inst.admin_unbind(ev2))
        assert inst.store.get("1002") is None
        assert any("已清除" in r for t, r in ev2.replies if t == "plain")


def test_unbind_and_view():
    with tempfile.TemporaryDirectory() as tmp:
        inst = make_plugin(tmp)
        inst.store.bind("1001", H.tiny_png(), nickname="阿明")
        ev = H.FakeEvent(text="/立绘查看")
        drive(inst.view_portrait(ev))
        chains = [r for t, r in ev.replies if t == "chain"]
        assert chains and "Image" in chains[0] and "Plain" in chains[0]
        ev2 = H.FakeEvent(text="/立绘解绑")
        drive(inst.unbind_portrait(ev2))
        assert inst.store.get("1001") is None
        assert any("已解除" in r for t, r in ev2.replies if t == "plain")


def test_listener_feeds_collector():
    with tempfile.TemporaryDirectory() as tmp:
        inst = make_plugin(tmp)
        pic = H.write_png(os.path.join(tmp, "l.png"))
        ev = H.FakeEvent(comps=[Image(url=pic)], text="看看这张图")
        asyncio.run(inst.on_group_message(ev))
        msgs = inst.collector.recent_messages("2001", 10)
        assert msgs and msgs[-1]["text"] == "看看这张图"
        assert inst.collector.last_image("2001", "1001", 60) == pic


def test_group_portrait_private_chat_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        inst = make_plugin(tmp)
        ev = H.FakeEvent(group_id="", text="/群像")
        drive(inst.group_portrait(ev))
        assert any("群聊" in r for t, r in ev.replies if t == "plain")
