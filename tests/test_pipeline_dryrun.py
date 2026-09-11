"""/群像 命令链路 dry-run(验收③):mock LLM + mock 生图,端到端走通。"""
import asyncio
import json
import os
import tempfile
import time

import helpers as H  # noqa: F401
from core.binding_store import BindingStore
from core.context_collector import ContextCollector
from core.pipeline import BusyError, GroupPortraitPipeline, PipelineError


def make_pipe(tmp, llm, rh):
    store = BindingStore(tmp)
    png = H.write_png(os.path.join(tmp, "ref.png"))
    data = open(png, "rb").read()
    store.bind("1001", data, nickname="阿明")
    store.bind("1002", data, nickname="小红")
    col = ContextCollector()
    col.observe("2001", "1001", "阿明", "今晚谁上线?")
    col.observe("2001", "1002", "小红", "带我一个!")
    with open(H.TEMPLATE_PATH, encoding="utf-8") as f:
        tpl = f.read()
    return GroupPortraitPipeline(store=store, collector=col, llm=llm, rh=rh,
                                 out_dir=os.path.join(tmp, "out"), system_template=tpl,
                                 context_n=50, max_characters=4,
                                 ratio="16:9 (Landscape)", megapixels="1")


def test_dryrun_success():
    with tempfile.TemporaryDirectory() as tmp:
        llm, rh = H.FakeLLM([H.composition_json()]), H.FakeRH()
        pipe = make_pipe(tmp, llm, rh)
        result = asyncio.run(pipe.run("2001"))
        # 出图落盘 + 回执内容
        assert os.path.isfile(result["image_path"])
        assert "阿明" in result["caption"] and "小红" in result["caption"]
        # 生图调用参数:参考图/负面/比例透传
        call = rh.calls[0]
        assert len(call["refs"]) == 2 and "文字" in call["negative"]
        assert "16:9" in (call["ratio"] or "")
        # 模板占位符已填:cap = min(D9 4人, 工作流3参考图) = 3
        sp = llm.prompts[0]["system_prompt"]
        assert "{{max_characters}}" not in sp and "3 人" in sp
        # 构图输入含活跃度标注与玩家清单
        up = llm.prompts[0]["prompt"]
        assert "1001.png" in up and "开黑" not in up or "今晚谁上线" in up
        assert result["context_source"] == "cache"


def test_llm_bad_then_good_retry():
    with tempfile.TemporaryDirectory() as tmp:
        llm = H.FakeLLM(["这不是JSON", H.composition_json()])
        pipe = make_pipe(tmp, llm, H.FakeRH())
        result = asyncio.run(pipe.run("2001"))
        assert os.path.isfile(result["image_path"])
        assert len(llm.prompts) == 2
        assert "上一次输出不合法" in llm.prompts[1]["prompt"]


def test_busy_rejects_duplicate_trigger():
    with tempfile.TemporaryDirectory() as tmp:
        pipe = make_pipe(tmp, H.FakeLLM([H.composition_json()]), H.FakeRH())
        pipe._busy["2001"] = time.time()
        try:
            asyncio.run(pipe.run("2001"))
            assert False, "生成中应拒绝重复触发"
        except BusyError as e:
            assert "还在画" in str(e)


def test_no_binding_error():
    with tempfile.TemporaryDirectory() as tmp:
        store = BindingStore(tmp)  # 空
        col = ContextCollector()
        col.observe("2001", "1001", "阿明", "hi")
        with open(H.TEMPLATE_PATH, encoding="utf-8") as f:
            tpl = f.read()
        pipe = GroupPortraitPipeline(store=store, collector=col, llm=H.FakeLLM([]),
                                     rh=H.FakeRH(), system_template=tpl)
        try:
            asyncio.run(pipe.run("2001"))
            assert False
        except PipelineError as e:
            assert "立绘绑定" in str(e)


def test_no_context_error():
    with tempfile.TemporaryDirectory() as tmp:
        store = BindingStore(tmp)
        store.bind("1001", H.tiny_png(), nickname="阿明")
        pipe = GroupPortraitPipeline(store=store, collector=ContextCollector(),
                                     llm=H.FakeLLM([]), rh=H.FakeRH(),
                                     system_template="x")
        try:
            asyncio.run(pipe.run("2001"))
            assert False
        except PipelineError as e:
            assert "群聊消息" in str(e)


def test_onebot_history_preferred_over_cache():
    with tempfile.TemporaryDirectory() as tmp:
        store = BindingStore(tmp)
        store.bind("1001", H.tiny_png(), nickname="阿明")
        col = ContextCollector()  # 缓存空 → 必须走 OneBot 历史
        history = [{"sender": {"user_id": 1001, "card": "阿明card", "nickname": "阿明"},
                    "time": 1750000000,
                    "message": [{"type": "text", "data": {"text": "开黑吗"}},
                                {"type": "image", "data": {"url": "http://x/1.png"}}]}]
        bot = H.FakeBot(history=history)
        msgs, src = asyncio.run(col.fetch_recent("2001", 50, bot))
        assert src == "onebot" and msgs[0]["text"] == "开黑吗[图片]"
        assert msgs[0]["nickname"] == "阿明card"  # 群名片优先
        with open(H.TEMPLATE_PATH, encoding="utf-8") as f:
            tpl = f.read()
        llm, rh = H.FakeLLM([H.composition_json()]), H.FakeRH()
        pipe = GroupPortraitPipeline(store=store, collector=col, llm=llm, rh=rh,
                                     out_dir=os.path.join(tmp, "out"), system_template=tpl)
        result = asyncio.run(pipe.run("2001", bot=bot))
        assert result["context_source"] == "onebot"
        assert ("get_group_msg_history", {"group_id": 2001, "count": 50}) in bot.calls


def test_onebot_failure_falls_back_to_cache():
    class DeadBot:
        async def call_action(self, action, **kw):
            raise RuntimeError("协议端不在线")

    with tempfile.TemporaryDirectory() as tmp:
        store = BindingStore(tmp)
        store.bind("1001", H.tiny_png(), nickname="阿明")
        col = ContextCollector()
        col.observe("2001", "1001", "阿明", "缓存兜底消息")
        with open(H.TEMPLATE_PATH, encoding="utf-8") as f:
            tpl = f.read()
        pipe = GroupPortraitPipeline(store=store, collector=col,
                                     llm=H.FakeLLM([H.composition_json()]), rh=H.FakeRH(),
                                     out_dir=os.path.join(tmp, "out"), system_template=tpl)
        result = asyncio.run(pipe.run("2001", bot=DeadBot()))
        assert result["context_source"] == "cache"


def test_cap_truncation_with_unbound_players():
    with tempfile.TemporaryDirectory() as tmp:
        chars = (("1001", "阿明", "a", "b"), ("1002", "小红", "a", "b"),
                 ("1099", "路人甲", "a", "b"), ("1098", "路人乙", "a", "b"),
                 ("1097", "路人丙", "a", "b"))
        llm = H.FakeLLM([json.dumps({"scene": "s", "characters": [
            {"qq": q, "nickname": n, "action": a, "expression": e} for q, n, a, e in chars],
            "negative": ""}, ensure_ascii=False)])
        pipe = make_pipe(tmp, llm, H.FakeRH())
        result = asyncio.run(pipe.run("2001"))
        comp = result["composition"]
        assert len(comp["characters"]) == 3  # cap = min(4, 3)
        assert "截断" in (comp["note"] or "")
        assert len(result["ref_paths"]) == 2  # 只有 1001/1002 有立绘
