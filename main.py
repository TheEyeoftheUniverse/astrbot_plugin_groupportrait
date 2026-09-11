"""群像——AstrBot 群聊立绘插画插件。

玩家发图 + /立绘绑定 把自定形象绑定到 QQ 号;管理员 /群像 触发:
读最近群聊 → LLM 构图(选场景/选人/挑参考图) → RunningHub 工作流生图 → 回发群里。
本文件只做 AstrBot 适配(命令面/消息组件/发送),核心逻辑在 core/(可独立单测)。

第二阶段 SillyTavern 扩展移植(TODO,本期不实施):
见 docs-agent/待落地需求/群像AstrBot插件_20260910.md「第二阶段」与
templates/compose_system_prompt.md 尾部备注。
"""
import json
import os
import time
import urllib.request

import astrbot.api.message_components as Comp
from astrbot.api import logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register

from .core.binding_store import BindingError, BindingStore
from .core.context_collector import ContextCollector
from .core.pipeline import GroupPortraitPipeline, PipelineError
from .core.runninghub import RunningHubClient

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
BUNDLED_TEMPLATE = os.path.join(PLUGIN_DIR, "templates", "compose_system_prompt.md")


def _runtime_dir() -> str:
    """优先 AstrBot 插件数据目录(StarTools),不可用退回插件目录下 data_runtime/。"""
    try:
        from astrbot.api.star import StarTools
        d = StarTools.get_data_dir("groupportrait")
        return str(d)
    except Exception:
        d = os.path.join(PLUGIN_DIR, "data_runtime")
        os.makedirs(d, exist_ok=True)
        return d


def _read_image_bytes(src: str) -> bytes:
    """图片来源 → bytes:支持 http(s) URL / file:// / 本地路径。"""
    src = str(src)
    if src.startswith(("http://", "https://")):
        req = urllib.request.Request(src, headers={"User-Agent": "Mozilla/5.0"})
        return urllib.request.urlopen(req, timeout=60).read()
    path = src[7:] if src.startswith("file://") else src
    with open(path, "rb") as f:
        return f.read()


# ---------- 消息组件鸭子扫描(AstrBot 组件类型不硬依赖,便于 stub 冒烟) ----------

def _components(event):
    mo = getattr(event, "message_obj", None)
    return list(getattr(mo, "message", None) or [])


def _is_named(comp, name):
    return type(comp).__name__.lower() == name.lower()


def _find_image_sources(event):
    """当前消息链里的图片(优先 url,退 file 字段)。"""
    out = []
    for c in _components(event):
        if _is_named(c, "Image"):
            src = getattr(c, "url", None) or getattr(c, "file", None)
            if src:
                out.append(src)
    return out


def _find_at_qq(event):
    for c in _components(event):
        if _is_named(c, "At"):
            q = getattr(c, "qq", None)
            if q:
                return str(q)
    return None


def _find_reply_id(event):
    """引用消息 id:Reply 组件 → OneBot raw_message.reply / source。"""
    for c in _components(event):
        if _is_named(c, "Reply"):
            rid = getattr(c, "id", None) or getattr(c, "message_id", None)
            if rid:
                return rid
    raw = getattr(getattr(event, "message_obj", None), "raw_message", None)
    if isinstance(raw, dict):
        if raw.get("reply"):
            return raw["reply"]
        src = raw.get("source")
        if isinstance(src, dict) and src.get("message_id"):
            return src["message_id"]
    return None


@register("astrbot_plugin_groupportrait", "TheEyeoftheUniverse",
          "群像:玩家绑定立绘,管理员 /群像 一键把最近群聊画成多人插画", "1.0.0")
class GroupPortraitPlugin(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        self.config = config or {}
        self.data_dir = _runtime_dir()
        self.store = BindingStore(self.data_dir,
                                  max_bytes=int(self._cfg("max_image_mb", 10)) * 1024 * 1024)
        self.collector = ContextCollector()
        self.pipeline = GroupPortraitPipeline(
            store=self.store, collector=self.collector,
            out_dir=os.path.join(self.data_dir, "outputs"),
            system_template=self._load_template(),
            context_n=int(self._cfg("context_n", 50)),
            max_characters=int(self._cfg("max_characters", 4)),
            temperature=self._cfg("llm_temperature", None),
            ratio=self._cfg("aspect_ratio", "") or None,
            megapixels=self._cfg("megapixels", "") or None,
        )
        self._last_run = {}  # group → ts(/群像 冷却,D6 预留,默认关)

    # ---------- 配置与装配 ----------

    def _cfg(self, key, default=None):
        return self.config.get(key, default)

    def _load_template(self):
        path = os.path.expanduser(self._cfg("compose_template", "") or BUNDLED_TEMPLATE)
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except OSError:
            logger.warning("群像:构图模板不可读(%s),退回内置模板", path)
            with open(BUNDLED_TEMPLATE, "r", encoding="utf-8") as f:
                return f.read()

    def _resolve_api_key(self):
        """key 链:配置项 → env RUNNINGHUB_API_KEY → key_file(复用 hermes 现成基建)。"""
        key = str(self._cfg("rh_api_key", "") or "").strip()
        if key:
            return key
        key = os.environ.get("RUNNINGHUB_API_KEY", "").strip()
        if key:
            return key
        key_file = os.path.expanduser(str(self._cfg("rh_key_file", "")
                                          or "~/.hermes/scripts/runninghub_krea2.json"))
        try:
            with open(key_file, "r", encoding="utf-8") as f:
                return str(json.load(f).get("apiKey") or "").strip()
        except (OSError, ValueError):
            return ""

    def _build_rh(self):
        return RunningHubClient(
            api_key=self._resolve_api_key(),
            webapp_id=self._cfg("rh_webapp_id", ""),
            base_url=str(self._cfg("rh_base_url", "https://www.runninghub.ai")),
            instance=str(self._cfg("rh_instance", "standard")),
            node_map={
                "prompt": {"node": str(self._cfg("node_prompt", "19")),
                           "field": str(self._cfg("node_prompt_field", "value"))},
                "negative": {"node": str(self._cfg("node_negative", "36")),
                             "field": str(self._cfg("node_negative_field", "value"))},
                "refs": {"nodes": [s.strip() for s in str(self._cfg("node_refs", "2,34,35")).split(",")
                                   if s.strip()],
                         "field": str(self._cfg("node_ref_field", "image"))},
                "seed": {"node": str(self._cfg("node_seed", "10")),
                         "field": str(self._cfg("node_seed_field", "noise_seed"))},
                "aspect": {"node": str(self._cfg("node_aspect", "40")),
                           "ratio_field": "aspect_ratio", "mp_field": "megapixels"},
            },
            poll_interval=float(self._cfg("rh_poll_interval", 5)),
            timeout_s=float(self._cfg("rh_timeout", 300)),
        )

    def _get_provider(self):
        try:
            return self.context.get_using_provider()
        except Exception:
            return None

    @staticmethod
    def _is_admin(event) -> bool:
        """兼容枚举与字符串(AstrBot RoleType.ADMIN value 为 'admin')。"""
        role = getattr(event, "role", None)
        if role is None:
            return False
        return "admin" in str(getattr(role, "value", role)).lower()

    # ---------- 消息监听:滚动缓存 + 最近发图记录 ----------

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_group_message(self, event: AstrMessageEvent):
        try:
            gid = event.get_group_id()
            if not gid:
                return
            # 本地缓存路径与 http(s) 都记(读取失败在绑定取图时兜底报错)
            urls = [str(u) for u in _find_image_sources(event)]
            self.collector.observe(str(gid), str(event.get_sender_id() or ""),
                                   event.get_sender_name() or "", event.get_message_str() or "",
                                   image_urls=urls)
        except Exception:
            logger.debug("群像:消息缓存失败", exc_info=True)

    # ---------- /群像(D11:仅管理员) ----------

    @filter.command("群像")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def group_portrait(self, event: AstrMessageEvent):
        gid = str(event.get_group_id() or "")
        if not gid:
            yield event.plain_result("群像请在群聊里触发")
            return
        whitelist = [s.strip() for s in str(self._cfg("group_whitelist", "")).split(",") if s.strip()]
        if whitelist and gid not in whitelist:
            yield event.plain_result("本群未开通群像功能")
            return
        cooldown_s = float(self._cfg("cooldown_min", 0)) * 60
        if cooldown_s > 0:
            last = self._last_run.get(gid)
            if last and time.time() - last < cooldown_s:
                yield event.plain_result(f"群像冷却中,约 {int((cooldown_s - (time.time() - last)) / 60) + 1} 分钟后再试")
                return
        n = int(self._cfg("context_n", 50))
        players = self.store.all()
        names = "、".join((e.get("nickname") or q) for q, e in players.items()) or "暂无"
        yield event.plain_result(f"收到,正在画最近 {n} 条群聊的群像…(已绑定立绘:{names})")
        self._last_run[gid] = time.time()
        self.pipeline.llm = self._get_provider()
        self.pipeline.rh = self._build_rh()
        try:
            result = await self.pipeline.run(gid, bot=getattr(event, "bot", None))
        except PipelineError as e:
            yield event.plain_result(f"群像生成失败:{e}")
            return
        except Exception as e:
            logger.exception("群像:未预期错误")
            yield event.plain_result(f"群像生成失败(未预期错误):{e}")
            return
        yield event.chain_result([Comp.Image.fromFileSystem(result["image_path"]),
                                  Comp.Plain("\n" + result["caption"])])

    # ---------- 立绘绑定族(D5:群内自助 + 管理员代管) ----------

    async def _resolve_bind_image(self, event, qq) -> tuple:
        """取图顺序:随指令图片 → 引用消息图片 → 最近发图缓存(窗口内)。"""
        for src in _find_image_sources(event):
            try:
                return _read_image_bytes(src), "随指令图片"
            except Exception:
                continue
        rid = _find_reply_id(event)
        bot = getattr(event, "bot", None)
        if rid is not None and bot is not None:
            try:
                raw = await bot.call_action("get_msg", message_id=int(rid))
                for seg in (raw or {}).get("message") or []:
                    if isinstance(seg, dict) and seg.get("type") == "image":
                        sd = seg.get("data") or {}
                        url = sd.get("url") or sd.get("file")
                        if url:
                            return _read_image_bytes(str(url)), "引用消息图片"
            except Exception:
                pass
        ttl = float(self._cfg("bind_image_ttl_min", 10)) * 60
        url = self.collector.last_image(event.get_group_id(), qq, ttl)
        if url:
            try:
                return _read_image_bytes(url), "最近发出的图片"
            except Exception:
                pass
        raise BindingError("没找到要绑定的图片:请回复一张图片发本指令,或先发图再紧跟着发本指令")

    async def _do_bind(self, event, target_qq=None):
        """绑定/换绑共用(换绑=覆盖,正本 D5);target_qq 为空即绑定自己。"""
        actor = str(event.get_sender_id() or "")
        target = str(target_qq or actor)
        if not target:
            yield event.plain_result("取不到 QQ 号,绑定失败")
            return
        nick = (event.get_sender_name() or "") if target == actor else target
        try:
            data, note = await self._resolve_bind_image(event, target)
            existed = self.store.get(target) is not None
            fname = self.store.bind(target, data, nickname=nick, source=note)
        except BindingError as e:
            yield event.plain_result(f"立绘绑定失败:{e}")
            return
        except Exception as e:
            logger.exception("群像:绑定取图失败")
            yield event.plain_result(f"立绘绑定失败:图片拉取不到({e});可以直接先发图,再紧跟本指令重试")
            return
        verb = "换绑更新" if existed else "绑定成功"
        yield event.plain_result(f"立绘{verb}:{target} 的立绘已归档({fname},来源:{note});用 /立绘查看 可确认")

    @filter.command("立绘绑定")
    async def bind_portrait(self, event: AstrMessageEvent):
        async for r in self._do_bind(event, None):
            yield r

    @filter.command("立绘换绑")
    async def rebind_portrait(self, event: AstrMessageEvent):
        async for r in self._do_bind(event, None):
            yield r

    @filter.command("立绘解绑")
    async def unbind_portrait(self, event: AstrMessageEvent):
        qq = str(event.get_sender_id() or "")
        ok = self.store.unbind(qq)
        yield event.plain_result("已解除你的立绘绑定" if ok else "你还没有绑定立绘")

    @filter.command("立绘代绑")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def admin_bind(self, event: AstrMessageEvent):
        target = _find_at_qq(event)
        if not target:
            yield event.plain_result("用法:带上图片(或回复图片)+ /立绘代绑 @某人")
            return
        async for r in self._do_bind(event, target):
            yield r

    @filter.command("立绘清绑")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def admin_unbind(self, event: AstrMessageEvent):
        target = _find_at_qq(event)
        if not target:
            yield event.plain_result("用法:/立绘清绑 @某人")
            return
        ok = self.store.unbind(target)
        yield event.plain_result(f"已清除 {target} 的立绘绑定" if ok else f"{target} 本来就没有绑定立绘")

    @filter.command("立绘查看")
    async def view_portrait(self, event: AstrMessageEvent):
        target = _find_at_qq(event) or str(event.get_sender_id() or "")
        entry = self.store.get(target)
        if not entry:
            yield event.plain_result(f"{target} 还没有绑定立绘(发一张图,紧跟着 /立绘绑定 即可)")
            return
        comps = []
        path = self.store.path_of(target)
        if path:
            comps.append(Comp.Image.fromFileSystem(path))
        ts = entry.get("updated_at")
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if isinstance(ts, (int, float)) else "?"
        comps.append(Comp.Plain(f"\n{entry.get('nickname') or target}({target}) 的立绘,更新于 {when}(v1 一人一张)"))
        yield event.chain_result(comps)

    async def terminate(self):
        pass
