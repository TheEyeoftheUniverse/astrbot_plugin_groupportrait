"""绑定存储单测(验收②:绑定数据流)。"""
import os
import tempfile

import helpers as H  # noqa: F401  先导入以注入 stub 路径
from core.binding_store import BindingError, BindingStore, sniff_image_ext, tiny_png

PNG = tiny_png()
JPG = b"\xff\xd8\xff\xe0" + b"junkdata" * 4
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"x" * 8


def test_sniff_ext():
    assert sniff_image_ext(PNG) == "png"
    assert sniff_image_ext(JPG) == "jpg"
    assert sniff_image_ext(WEBP) == "webp"
    assert sniff_image_ext(b"not an image at all") is None


def test_bind_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        store = BindingStore(tmp)
        fname = store.bind("1001", PNG, nickname="阿明", source="测试")
        assert fname == "1001.png"
        entry = store.get("1001")
        assert entry["files"] == ["1001.png"] and entry["primary"] == 0
        assert entry["nickname"] == "阿明"
        assert store.path_of("1001") == os.path.join(tmp, "refs", "1001.png")
        assert os.path.isfile(store.path_of("1001"))


def test_rebind_overwrites_and_cleans_old_ext():
    with tempfile.TemporaryDirectory() as tmp:
        store = BindingStore(tmp)
        added_at = store.bind("1001", PNG) and store.get("1001")["added_at"]
        fname = store.bind("1001", JPG)  # 换绑:png → jpg
        assert fname == "1001.jpg"
        assert store.path_of("1001").endswith("1001.jpg")
        assert not os.path.isfile(os.path.join(tmp, "refs", "1001.png"))
        assert store.get("1001")["added_at"] == added_at  # 首绑时间保留


def test_reject_non_image():
    with tempfile.TemporaryDirectory() as tmp:
        store = BindingStore(tmp)
        try:
            store.bind("1001", b"just text")
            assert False, "应拒绝非位图"
        except BindingError as e:
            assert "png/jpg/webp" in str(e)


def test_reject_oversize():
    with tempfile.TemporaryDirectory() as tmp:
        store = BindingStore(tmp, max_bytes=100)
        try:
            store.bind("1001", PNG + b"\x00" * 200)
            assert False, "应拒绝超限图片"
        except BindingError as e:
            assert "上限" in str(e)


def test_unbind():
    with tempfile.TemporaryDirectory() as tmp:
        store = BindingStore(tmp)
        store.bind("1001", PNG)
        assert store.unbind("1001") is True
        assert store.get("1001") is None
        assert store.path_of("1001") is None
        assert not os.path.isfile(os.path.join(tmp, "refs", "1001.png"))
        assert store.unbind("1001") is False


def test_missing_file_path_none():
    with tempfile.TemporaryDirectory() as tmp:
        store = BindingStore(tmp)
        store.bind("1001", PNG)
        os.remove(os.path.join(tmp, "refs", "1001.png"))
        assert store.path_of("1001") is None
