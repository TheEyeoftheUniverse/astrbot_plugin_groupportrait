"""测试夹具:stub 路径注入 + 假事件/假机器人/假 LLM/假生图后端。"""
import json
import os
import struct
import sys
import zlib

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_HERE, "astrbot_stub"))  # astrbot stub 包
sys.path.insert(0, _REPO)                                # 仓库根(core / templates)
sys.path.insert(0, os.path.dirname(_REPO))               # 仓库父目录:以命名空间包导入插件(对齐 AstrBot 包加载)

from astrbot.api.star import StarTools  # noqa: E402  (stub)

TEMPLATE_PATH = os.path.join(_REPO, "templates", "compose_system_prompt.md")


def tiny_png():
    """1x1 合法 png。"""
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\x00\x00")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def write_png(path):
    with open(path, "wb") as f:
        f.write(tiny_png())
    return path


class FakeSender:
    def __init__(self, user_id, nickname):
        self.user_id = user_id
        self.nickname = nickname


class FakeMessageObj:
    def __init__(self, comps, sender):
        self.message = comps
        self.sender = sender
        self.raw_message = {}


class FakeEvent:
    """鸭子版 AstrMessageEvent:记录所有回复,供断言。"""

    def __init__(self, sender_id="1001", nickname="阿明", group_id="2001",
                 text="", comps=None, role="member"):
        self.message_obj = FakeMessageObj(comps or [], FakeSender(sender_id, nickname))
        self.role = role
        self.bot = None
        self._gid = group_id
        self._text = text
        self.replies = []

    def get_group_id(self):
        return self._gid

    def get_sender_id(self):
        return self.message_obj.sender.user_id

    def get_sender_name(self):
        return self.message_obj.sender.nickname

    def get_message_str(self):
        return self._text

    def plain_result(self, t):
        self.replies.append(("plain", t))
        return {"type": "plain", "text": t}

    def chain_result(self, comps):
        self.replies.append(("chain", [type(c).__name__ for c in comps]))
        return {"type": "chain", "comps": comps}


class FakeBot:
    """OneBot 协议端假件:get_group_msg_history / get_msg。"""

    def __init__(self, history=None, msg_by_id=None):
        self.history = history or []
        self.msg_by_id = msg_by_id or {}
        self.calls = []

    async def call_action(self, action, **kw):
        self.calls.append((action, kw))
        if action == "get_group_msg_history":
            return {"messages": self.history}
        if action == "get_msg":
            return self.msg_by_id.get(str(kw.get("message_id")), {})
        return {}


class FakeLLM:
    """按脚本依次返回;text_chat 形态对齐 AstrBot provider。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []

    async def text_chat(self, **kw):
        self.prompts.append(kw)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class FakeRH:
    """生图后端假件:与 RunningHubClient 同鸭子接口,写 1x1 png 假图。"""

    timeout_s = 300
    ref_node_ids = ["2", "34", "35"]

    def __init__(self):
        self.calls = []

    def generate_images(self, prompt, negative="", ref_paths=(), out_dir=".",
                        seed=None, ratio=None, megapixels=None, prefix="g_"):
        self.calls.append({"prompt": prompt, "negative": negative, "refs": list(ref_paths),
                           "out_dir": out_dir, "seed": seed, "ratio": ratio, "mp": megapixels})
        os.makedirs(out_dir, exist_ok=True)
        return [write_png(os.path.join(out_dir, f"{prefix}0.png"))]


def composition_json(scene="深夜网吧开黑",
                     chars=(("1001", "阿明", "喊麦", "亢奋"), ("1002", "小红", "举杯", "兴奋")),
                     negative="文字, 水印, 签名"):
    return json.dumps({"scene": scene,
                       "characters": [{"qq": q, "nickname": n, "action": a, "expression": e}
                                      for q, n, a, e in chars],
                       "negative": negative}, ensure_ascii=False)


def fresh_data_dir(name="gp"):
    d = os.path.join(StarTools.get_data_dir("groupportrait"), name)
    os.makedirs(d, exist_ok=True)
    return d
