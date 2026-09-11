"""立绘绑定存储:QQ 号 → 立绘文件(数据目录归档 + JSON 绑定表)。

D10:v1 一人一张;files 数组 + primary 指针预留多张差分扩展位。
图片规格:仅 png/jpg/webp(魔数校验),超大拒绝(阈值可配,默认 10MB),原图即参考图不裁剪。
"""
import json
import os
import time

ALLOWED_EXTS = ("png", "jpg", "jpeg", "webp")


class BindingError(Exception):
    """绑定流程中可向群内直报的错误。"""


def sniff_image_ext(data: bytes):
    """按魔数识别位图格式,返回规范扩展名(png/jpg/webp)或 None。"""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:2] == b"\xff\xd8":
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def tiny_png():
    """生成 1x1 合法 png(测试夹具用)。"""
    import struct
    import zlib

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\x00\x00")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


class BindingStore:
    def __init__(self, data_dir, max_bytes=10 * 1024 * 1024):
        self.data_dir = data_dir
        self.refs_dir = os.path.join(data_dir, "refs")
        os.makedirs(self.refs_dir, exist_ok=True)
        self.max_bytes = max_bytes
        self.table_path = os.path.join(data_dir, "bindings.json")
        self._table = self._load()

    def _load(self):
        try:
            with open(self.table_path, "r", encoding="utf-8") as f:
                table = json.load(f)
            return table if isinstance(table, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self):
        tmp = self.table_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._table, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.table_path)

    def bind(self, qq, image_bytes, nickname="", source=""):
        """绑定/覆盖(换绑同入口)。返回归档文件名。"""
        ext = sniff_image_ext(image_bytes)
        if ext is None:
            raise BindingError("仅接受 png/jpg/webp 位图,其他格式不支持")
        if len(image_bytes) > self.max_bytes:
            raise BindingError(f"图片超过 {self.max_bytes // (1024 * 1024)}MB 上限,请压缩后再绑")
        qq = str(qq)
        fname = f"{qq}.{ext}"
        with open(os.path.join(self.refs_dir, fname), "wb") as f:
            f.write(image_bytes)
        # 换绑后清理旧扩展名遗留文件
        for old in ALLOWED_EXTS:
            if old != ext:
                stale = os.path.join(self.refs_dir, f"{qq}.{old}")
                if os.path.isfile(stale):
                    os.remove(stale)
        now = time.time()
        prev = self._table.get(qq)
        self._table[qq] = {
            "files": [fname],
            "primary": 0,
            "nickname": nickname or (prev or {}).get("nickname", ""),
            "added_at": (prev or {}).get("added_at", now),
            "updated_at": now,
            "source": source,
        }
        self._save()
        return fname

    def unbind(self, qq):
        """解除绑定并删除归档文件。返回是否确有绑定。"""
        qq = str(qq)
        entry = self._table.pop(qq, None)
        if entry is None:
            return False
        for fname in entry.get("files", []):
            p = os.path.join(self.refs_dir, fname)
            if os.path.isfile(p):
                os.remove(p)
        self._save()
        return True

    def get(self, qq):
        return self._table.get(str(qq))

    def path_of(self, qq):
        """当前生效立绘的绝对路径;未绑定或文件丢失返回 None。"""
        entry = self.get(qq)
        if not entry:
            return None
        files = entry.get("files") or []
        idx = entry.get("primary", 0)
        if not files or idx >= len(files):
            return None
        p = os.path.join(self.refs_dir, files[idx])
        return p if os.path.isfile(p) else None

    def all(self):
        return dict(self._table)
