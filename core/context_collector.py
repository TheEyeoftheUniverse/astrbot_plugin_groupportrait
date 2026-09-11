"""群聊上下文采集(正本 §2):OneBot 历史接口优先,运行期滚动缓存兜底。

消息形态整理:纯文本保留;图片记为「[图片]」占位;合并转发按一条摘要处理。
另维护每 (群, QQ) 最近发出的图片 URL(供『先发图再紧跟指令』的绑定路径回溯)。
"""
import time
from collections import defaultdict, deque


class ContextCollector:
    def __init__(self, cache_len=200, recent_images=5):
        self._cache = defaultdict(lambda: deque(maxlen=cache_len))
        self._images = defaultdict(lambda: deque(maxlen=recent_images))

    def observe(self, group_id, qq, nickname, text, ts=None, image_urls=()):
        """运行期收到群消息时追加(由 main.py 的事件监听喂入)。"""
        ts = ts if ts is not None else time.time()
        text = (text or "").strip()
        if text:
            self._cache[str(group_id)].append({
                "qq": str(qq), "nickname": nickname or str(qq), "text": text, "ts": ts,
            })
        for u in image_urls or ():
            if isinstance(u, str) and u:
                self._images[(str(group_id), str(qq))].append((ts, u))

    def recent_messages(self, group_id, n):
        msgs = list(self._cache[str(group_id)])
        return msgs[-n:] if n and n < len(msgs) else msgs

    def last_image(self, group_id, qq, ttl_s):
        """该用户在本群最近发出的图片 URL,超出 ttl 返回 None。"""
        dq = self._images.get((str(group_id), str(qq)))
        if not dq:
            return None
        ts, url = dq[-1]
        if ttl_s and time.time() - ts > ttl_s:
            return None
        return url

    async def fetch_recent(self, group_id, n, bot=None):
        """返回 (messages, source);历史接口不可用时静默降级缓存。"""
        if bot is not None:
            try:
                raw = await bot.call_action("get_group_msg_history", group_id=int(group_id), count=int(n))
                msgs = self.normalize_onebot((raw or {}).get("messages") or [])
                if msgs:
                    return msgs, "onebot"
            except Exception:
                pass
        return self.recent_messages(group_id, n), "cache"

    @staticmethod
    def normalize_onebot(raw_msgs):
        """OneBot 历史消息 → 统一 {qq, nickname, text, ts};字段缺失容错(协议端差异)。"""
        out = []
        for m in raw_msgs or ():
            if not isinstance(m, dict):
                continue
            sender = m.get("sender") or {}
            qq = str(sender.get("user_id", ""))
            nick = sender.get("card") or sender.get("nickname") or qq
            parts = []
            for seg in m.get("message") or ():
                if not isinstance(seg, dict):
                    continue
                st, sd = seg.get("type"), seg.get("data") or {}
                if st == "text":
                    parts.append(sd.get("text", ""))
                elif st == "image":
                    parts.append("[图片]")
                elif st in ("forward", "node"):
                    parts.append("[合并转发]")
            text = "".join(parts).strip()
            if text and qq:
                out.append({"qq": qq, "nickname": nick, "text": text, "ts": m.get("time")})
        return out
