"""直连生图 API(B 通道)单测:请求构造 + 脚本化全链路 + 通道分发(不联网,全 mock HTTP)。"""
import asyncio
import base64
import importlib
import os
import tempfile

import helpers as H  # noqa: F401  注入 stub 路径
from astrbot.api.event import filter as stub_filter
from core.direct_api import DirectAPIError, DirectImageClient
from core.runninghub import RunningHubClient

plugin_main = importlib.import_module("astrbot_plugin_groupportrait.main")

TINY_PNG_B64 = base64.b64encode(H.tiny_png()).decode()


def client(**kw):
    kw.setdefault("timeout_s", 5)
    return DirectImageClient("https://api.test/v1", "sk-test", kw.pop("model", "gpt-image-x"), **kw)


class ScriptedDirect(DirectImageClient):
    """脚本化网络层:三种 HTTP 动作与下载全落本地记录,响应可编程。"""

    def __init__(self, response=None, **kw):
        super().__init__("https://api.test/v1", "sk-test", kw.pop("model", "gpt-image-x"), **kw)
        self.response = response if response is not None else {"data": [{"b64_json": TINY_PNG_B64}]}
        self.json_posts, self.multipart_posts, self.gets, self.downloads = [], [], [], []

    def _post_json(self, path, payload, timeout=None):
        self.json_posts.append((path, payload))
        return self.response

    def _post_multipart(self, path, fields, files, timeout=None):
        self.multipart_posts.append((path, fields, files))
        return self.response

    def _get_json(self, path, timeout=60):
        self.gets.append(path)
        return self.response

    def download(self, url, out_dir, prefix="groupportrait_"):
        self.downloads.append(url)
        os.makedirs(out_dir, exist_ok=True)
        return H.write_png(os.path.join(out_dir, "got.png"))


# ---------- 请求构造(纯逻辑) ----------

def test_build_generations_payload_shape():
    p = client(size="1536x1024").build_generations_payload("场景X")
    assert p == {"model": "gpt-image-x", "prompt": "场景X", "n": 1, "size": "1536x1024"}
    assert "seed" not in p and "negative" not in p  # OpenAI images 形状无此二参


def test_build_prompt_merge_negative():
    assert client().build_prompt("场景", "文字") == "场景"  # 默认丢弃负面词
    merged = client(merge_negative=True).build_prompt("场景", "文字, 水印")
    assert merged == "场景\nNegative prompt: 文字, 水印"


def test_build_edits_parts_field_names():
    fields, files = client(size="1024x1024").build_edits_parts("场景", ["a.png", "b.png"])
    assert ("model", "gpt-image-x") in fields and ("prompt", "场景") in fields
    assert ("n", "1") in fields and ("size", "1024x1024") in fields
    assert [f for f, _ in files] == ["image[]", "image[]"]  # 多图用 image[]
    assert [p for _, p in files] == ["a.png", "b.png"]
    _, files1 = client().build_edits_parts("场景", ["a.png"])
    assert [f for f, _ in files1] == ["image"]  # 单图用 image


def test_ref_node_ids_cap():
    assert client(max_refs=4).ref_node_ids == ["0", "1", "2", "3"]  # pipeline 只取 len


# ---------- 全链路(脚本化 HTTP) ----------

def test_generations_full_chain_no_refs():
    with tempfile.TemporaryDirectory() as tmp:
        c = ScriptedDirect(size="1536x1024")
        paths = c.generate_images("场景X", "文字", [], tmp, seed=7, ratio="16:9", megapixels="1")
        assert paths and os.path.isfile(paths[0])
        assert c.multipart_posts == [] and c.downloads == []  # 无参考图 → 只走文生图
        path, payload = c.json_posts[0]
        assert path == "/images/generations"
        assert payload["model"] == "gpt-image-x" and payload["prompt"] == "场景X"
        assert payload["n"] == 1 and payload["size"] == "1536x1024"


def test_generations_url_response_downloaded():
    with tempfile.TemporaryDirectory() as tmp:
        c = ScriptedDirect(response={"data": [{"url": "http://x/a.png"}]})
        paths = c.generate_images("场景", out_dir=tmp)
        assert c.downloads == ["http://x/a.png"] and os.path.isfile(paths[0])


def test_edits_full_chain_with_refs():
    with tempfile.TemporaryDirectory() as tmp:
        ref1, ref2 = H.write_png(os.path.join(tmp, "r1.png")), H.write_png(os.path.join(tmp, "r2.png"))
        c = ScriptedDirect(response={"data": [{"url": "http://x/out.png"}]})
        paths = c.generate_images("场景X", "文字", [ref1, ref2], os.path.join(tmp, "out"))
        assert paths and os.path.isfile(paths[0])
        assert c.json_posts == []  # 有参考图 → 只走 edits
        path, fields, files = c.multipart_posts[0]
        assert path == "/images/edits"
        assert ("model", "gpt-image-x") in fields and ("n", "1") in fields
        assert [p for _, p in files] == [ref1, ref2]


def test_edits_b64_response_written():
    with tempfile.TemporaryDirectory() as tmp:
        ref = H.write_png(os.path.join(tmp, "r.png"))
        c = ScriptedDirect()  # 默认 b64_json 响应
        paths = c.generate_images("场景", out_dir=tmp, ref_paths=[ref])
        with open(paths[0], "rb") as f:
            assert f.read() == H.tiny_png()


def test_model_required_at_generate():
    with tempfile.TemporaryDirectory() as tmp:
        c = ScriptedDirect(model="")
        try:
            c.generate_images("场景", out_dir=tmp)
            assert False, "未选模型应拒绝生图"
        except DirectAPIError as e:
            assert "model 未选择" in str(e)
        assert c.json_posts == [] and c.multipart_posts == []  # 拒在请求前


def test_error_payload_raises():
    with tempfile.TemporaryDirectory() as tmp:
        c = ScriptedDirect(response={"error": {"message": "quota exceeded"}})
        try:
            c.generate_images("场景", out_dir=tmp)
            assert False
        except DirectAPIError as e:
            assert "quota exceeded" in str(e)


def test_empty_data_raises():
    with tempfile.TemporaryDirectory() as tmp:
        c = ScriptedDirect(response={"data": []})
        try:
            c.generate_images("场景", out_dir=tmp)
            assert False
        except DirectAPIError:
            pass


# ---------- 模型列表 ----------

def test_list_models_openai_shape():
    c = ScriptedDirect(response={"object": "list", "data": [{"id": "m2"}, {"id": "m1"}]})
    assert c.list_models() == ["m2", "m1"]
    assert c.gets == ["/models"]


def test_parse_models_fallback_shapes():
    assert DirectImageClient.parse_models(["a", "b"]) == ["a", "b"]
    assert DirectImageClient.parse_models({"models": ["x"]}) == ["x"]
    assert DirectImageClient.parse_models({"data": ["y", {"id": "z"}]}) == ["y", "z"]
    try:
        DirectImageClient.parse_models({"foo": 1})
        assert False
    except DirectAPIError:
        pass


# ---------- 装配层通道分发(插件级) ----------
# 插件经命名空间包加载,其 core.* 与测试直连的 core.* 是两份模块对象,
# isinstance/except 必须用插件命名空间的类。
from astrbot_plugin_groupportrait.core.direct_api import (  # noqa: E402
    DirectAPIError as PDirectAPIError,
    DirectImageClient as PDirectImageClient)
from astrbot_plugin_groupportrait.core.runninghub import (  # noqa: E402
    RunningHubClient as PRunningHubClient)


def _inst(config):
    return plugin_main.GroupPortraitPlugin(plugin_main.Context(), config=config)


def test_channel_dispatch_default_is_runninghub():
    inst = _inst({"rh_api_key": "k", "rh_webapp_id": "wf"})
    assert isinstance(inst._build_imager(), PRunningHubClient)  # 默认 A 通道,老用户零改动


def test_channel_dispatch_direct_and_wiring():
    inst = _inst({"channel": "direct", "direct_base_url": "https://api.test/v1",
                  "direct_api_key": "sk-1", "direct_model": "m-1",
                  "direct_size": "1024x1024", "direct_max_refs": 3})
    im = inst._build_imager()
    assert isinstance(im, PDirectImageClient)
    assert im.model == "m-1" and im.size == "1024x1024" and im.max_refs == 3
    assert len(im.ref_node_ids) == 3


def test_channel_dispatch_direct_missing_base_url():
    inst = _inst({"channel": "direct", "direct_api_key": "sk-1"})
    try:
        inst._build_imager()
        assert False, "缺 base_url 应装配失败"
    except PDirectAPIError:
        pass


def test_direct_key_chain_env_fallback():
    old = (os.environ.pop("DIRECT_IMAGE_API_KEY", None), os.environ.pop("OPENAI_API_KEY", None))
    try:
        inst = _inst({"channel": "direct", "direct_base_url": "https://api.test/v1"})
        os.environ["OPENAI_API_KEY"] = "openai-key"
        assert inst._resolve_direct_key() == "openai-key"
        os.environ["DIRECT_IMAGE_API_KEY"] = "direct-key"
        assert inst._resolve_direct_key() == "direct-key"  # 专属 env 优先
        inst2 = _inst({"channel": "direct", "direct_base_url": "https://api.test/v1",
                       "direct_api_key": "cfg-key"})
        assert inst2._resolve_direct_key() == "cfg-key"  # 配置最优先
    finally:
        for name, v in zip(("DIRECT_IMAGE_API_KEY", "OPENAI_API_KEY"), old):
            if v is not None:
                os.environ[name] = v
            else:
                os.environ.pop(name, None)


def test_model_override_persists_and_wins():
    inst = _inst({"channel": "direct", "direct_base_url": "https://api.test/v1",
                  "direct_api_key": "sk", "direct_model": "from-config"})
    inst._write_model_override("picked-via-command")
    try:
        assert inst._build_imager().model == "picked-via-command"  # 命令选择覆盖配置
        assert inst._read_model_override() == "picked-via-command"
    finally:
        os.unlink(inst._overrides_path())
    assert inst._build_imager().model == "from-config"  # 删除后回退配置


def test_channel_commands_registered():
    cls = plugin_main.GroupPortraitPlugin
    for name in ("image_channel_status", "image_channel_models"):
        fn = getattr(cls, name)
        assert getattr(fn, "_is_command", False), f"{name} 未注册为命令"
        assert fn._permission == (stub_filter.PermissionType.ADMIN,)


def test_models_command_lists_and_picks():
    inst = _inst({"channel": "direct", "direct_base_url": "https://api.test/v1",
                  "direct_api_key": "sk"})
    scripted = ScriptedDirect(response={"data": [{"id": "m-a"}, {"id": "m-b"}]})
    inst._build_imager = lambda: scripted  # 实例级替换,不触网

    async def flow():
        ev1 = H.FakeEvent(text="/生图模型", role="admin")
        async for _ in inst.image_channel_models(ev1):
            pass
        ev2 = H.FakeEvent(text="/生图模型 2", role="admin")
        async for _ in inst.image_channel_models(ev2):
            pass
        return ev1, ev2

    ev1, ev2 = asyncio.run(flow())
    listing = ev1.replies[-1][1]
    assert "1. m-a" in listing and "2. m-b" in listing and "m-c" not in listing
    assert "已选" in ev2.replies[-1][1] and "m-b" in ev2.replies[-1][1]
    assert inst._read_model_override() == "m-b"  # 选中已持久化
    os.unlink(inst._overrides_path())


def test_models_command_rejected_on_runninghub_channel():
    inst = _inst({"rh_api_key": "k", "rh_webapp_id": "wf"})

    async def flow():
        ev = H.FakeEvent(text="/生图模型", role="admin")
        async for _ in inst.image_channel_models(ev):
            pass
        return ev

    ev = asyncio.run(flow())
    assert "RunningHub" in ev.replies[-1][1]  # A 通道下明确提示不可用
