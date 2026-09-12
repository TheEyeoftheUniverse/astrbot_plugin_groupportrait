"""群像流水线:上下文 → LLM 构图 → 参考图解析 → 按通道生图 → 成图落盘。

/群像 一条命令背后的完整链路;llm/rh 均为注入依赖(鸭子接口),dry-run 时可整体 mock。
同一群同时只允许一幅在画(生成中重复触发直接拒绝,正本 §5)。
"""
import asyncio
import logging
import os
import time

from .binding_store import BindingStore
from .composer import build_user_prompt, compose, fill_template, render_messages, render_players
from .context_collector import ContextCollector

logger = logging.getLogger("groupportrait.pipeline")

FALLBACK_TIMEOUT_S = 300.0


class PipelineError(Exception):
    """可向群内直报的流水线错误。"""


class BusyError(PipelineError):
    pass


class GroupPortraitPipeline:
    def __init__(self, store, collector, llm=None, rh=None, out_dir="outputs",
                 system_template="", context_n=50, max_characters=4,
                 temperature=None, ratio=None, megapixels=None, seed=None):
        self.store = store
        self.collector = collector
        self.llm = llm
        self.rh = rh
        self.out_dir = out_dir
        self.system_template = system_template
        self.context_n = context_n
        self.max_characters = max_characters
        self.temperature = temperature
        self.ratio = ratio
        self.megapixels = megapixels
        self.seed = seed
        self._busy = {}

    def busy_remaining(self, group_id):
        t0 = self._busy.get(str(group_id))
        if t0 is None:
            return None
        est = float(getattr(self.rh, "timeout_s", FALLBACK_TIMEOUT_S) or FALLBACK_TIMEOUT_S)
        return max(0.0, est - (time.time() - t0))

    async def run(self, group_id, bot=None):
        g = str(group_id)
        if self._busy.get(g) is not None:
            rem = self.busy_remaining(g)
            raise BusyError(f"上一幅群像还在画(预计还要 {max(1, int(rem)) if rem is not None else '?'} 秒),"
                            "画完前不接受重复触发")
        self._busy[g] = time.time()
        try:
            return await self._run(g, bot)
        finally:
            self._busy.pop(g, None)

    async def _run(self, g, bot):
        if self.llm is None:
            raise PipelineError("宿主未接 LLM provider,构图大脑不可用")
        if self.rh is None:
            raise PipelineError("生图通道未配置(检查 channel 与对应通道的 api_key 等装配项)")
        # 1. 上下文
        messages, src = await self.collector.fetch_recent(g, self.context_n, bot)
        if not messages:
            raise PipelineError("取不到最近群聊消息(历史接口不可用且本地缓存为空)")
        entries = self.store.all()
        if not entries:
            raise PipelineError("本群还没有人绑定立绘:群友先发一张图,紧跟着发 /立绘绑定 即可")
        # 2. 玩家清单(含活跃度)
        counts = {}
        for m in messages:
            counts[m["qq"]] = counts.get(m["qq"], 0) + 1
        players_by_qq = {}
        for qq, entry in entries.items():
            files = entry.get("files") or []
            idx = entry.get("primary", 0)
            ref_id = files[idx] if idx < len(files) else (files[0] if files else "")
            players_by_qq[qq] = {"nickname": entry.get("nickname") or qq, "ref_id": ref_id,
                                 "active": counts.get(qq, 0)}
        # 3. 构图(入画上限同时受 D9 人数与工作流参考图节点数约束)
        cap = min(self.max_characters, len(getattr(self.rh, "ref_node_ids", []) or [1]))
        system_prompt = fill_template(self.system_template, max_characters=cap)
        user_prompt = build_user_prompt(render_messages(messages), render_players(players_by_qq), cap)
        composition = await compose(self.llm, system_prompt, user_prompt, players_by_qq, cap,
                                    temperature=self.temperature)
        # 4. 参考图解析(去重,按 characters 顺序)
        ref_paths, seen = [], set()
        nicknames = []
        for c in composition["characters"]:
            nicknames.append(c["nickname"])
            p = self.store.path_of(c["qq"])
            if p and c["qq"] not in seen:
                seen.add(c["qq"])
                ref_paths.append(p)
        if not ref_paths:
            raise PipelineError("构图选出的角色没有任何已绑定立绘,无法出图")
        # 5. 生图(阻塞 IO 放线程,不卡事件循环)
        os.makedirs(self.out_dir, exist_ok=True)
        try:
            paths = await asyncio.to_thread(
                self.rh.generate_images, composition["scene"], composition["negative"],
                ref_paths, self.out_dir, self.seed, self.ratio, self.megapixels)
        except Exception as e:
            raise PipelineError(f"{getattr(self.rh, 'channel_name', 'RunningHub')} 生图失败:{e}") from e
        # 6. 回执内容
        bits = []
        if composition.get("note"):
            bits.append(composition["note"])
        bits.append("参与角色:" + "、".join(nicknames))
        scene = composition["scene"]
        bits.append(scene if len(scene) <= 120 else scene[:120] + "…")
        logger.info("群像完成 group=%s source=%s refs=%s out=%s", g, src, len(ref_paths), paths[0])
        return {"image_path": paths[0], "caption": "\n".join(bits),
                "composition": composition, "context_source": src, "ref_paths": ref_paths}
