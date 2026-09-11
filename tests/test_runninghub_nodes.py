"""RunningHub 客户端单测:节点映射拼装 + 脚本化全链路(不联网)。"""
import os
import tempfile

import helpers as H  # noqa: F401
from core.runninghub import RunningHubClient, RunningHubError


def client(**kw):
    kw.setdefault("poll_interval", 0.001)
    kw.setdefault("timeout_s", 2)
    return RunningHubClient("testkey", "testwf", **kw)


def test_build_node_info_krea2_map():
    c = client()
    ni = c.build_node_info("场景X", "文字, 水印", ["a.png", "b.png"],
                           seed=42, ratio="16:9 (Landscape)", megapixels=1)
    assert {"nodeId": "19", "fieldName": "value", "fieldValue": "场景X"} in ni
    assert {"nodeId": "36", "fieldName": "value", "fieldValue": "文字, 水印"} in ni
    imgs = [e for e in ni if e["fieldName"] == "image"]
    assert [(e["nodeId"], e["fieldValue"]) for e in imgs] == [("2", "a.png"), ("34", "b.png")]
    assert {"nodeId": "10", "fieldName": "noise_seed", "fieldValue": "42"} in ni
    assert {"nodeId": "40", "fieldName": "aspect_ratio", "fieldValue": "16:9 (Landscape)"} in ni
    assert {"nodeId": "40", "fieldName": "megapixels", "fieldValue": "1"} in ni


def test_build_node_info_optional_fields_omitted():
    ni = client().build_node_info("只有提示词")
    assert all(e["fieldName"] != "image" for e in ni)
    assert len(ni) == 1


def test_ref_overflow_rejected():
    try:
        client().build_node_info("p", ref_names=["1", "2", "3", "4"])
        assert False, "4 张应超出 3 节点"
    except RunningHubError:
        pass


def test_custom_node_map():
    c = client(node_map={"refs": {"nodes": ["7", "8", "9", "10"], "field": "image"}})
    assert c.ref_node_ids == ["7", "8", "9", "10"]


class ScriptedRH(RunningHubClient):
    """脚本化网络层:create/outputs 假应答,上传/下载落本地。"""

    def __init__(self, outputs=None, poll_interval=0.001, timeout_s=2):
        super().__init__("k", "wf", poll_interval=poll_interval, timeout_s=timeout_s)
        self.outputs = outputs or [{"code": 0, "data": [{"fileUrl": "http://x/a.png"}]}]
        self.uploaded, self.posts = [], []

    def _upload(self, path, timeout=120):
        self.uploaded.append(path)
        return "up_" + os.path.basename(path)

    def _post(self, path, payload, timeout=60):
        self.posts.append((path, payload))
        if path.endswith("/create"):
            return {"code": 0, "data": {"taskId": "T1"}}
        return self.outputs.pop(0)

    def download(self, url, out_dir, prefix="groupportrait"):
        return H.write_png(os.path.join(out_dir, "got.png"))


def test_generate_images_full_chain():
    with tempfile.TemporaryDirectory() as tmp:
        rh = ScriptedRH()
        ref1, ref2 = H.write_png(os.path.join(tmp, "r1.png")), H.write_png(os.path.join(tmp, "r2.png"))
        paths = rh.generate_images("场景", "负面", [ref1, ref2], tmp, None, "16:9 (Landscape)", "1")
        assert paths and os.path.isfile(paths[0])
        assert rh.uploaded == [ref1, ref2]
        assert rh.last_task_id == "T1"
        create_path, create_payload = next(p for p in rh.posts if p[0].endswith("/create"))
        assert create_path == "/task/openapi/create"
        assert create_payload["workflowId"] == "wf"
        assert create_payload["apiKey"] == "k"
        nil = create_payload["nodeInfoList"]
        assert nil[0] == {"nodeId": "19", "fieldName": "value", "fieldValue": "场景"}
        assert sum(1 for e in nil if e["fieldName"] == "image") == 2


def test_poll_failed_805():
    rh = ScriptedRH(outputs=[{"code": 805, "msg": "GPU 炸了"}])
    try:
        rh.generate_images("p", out_dir=tempfile.mkdtemp())
        assert False
    except RunningHubError as e:
        assert "失败" in str(e) and "T1" in str(e)


def test_poll_unexpected_code():
    rh = ScriptedRH(outputs=[{"code": 999, "msg": "离谱"}])
    try:
        rh.generate_images("p", out_dir=tempfile.mkdtemp())
        assert False
    except RunningHubError as e:
        assert "999" in str(e)


def test_poll_timeout():
    rh = ScriptedRH(outputs=None, poll_interval=0.001, timeout_s=0.05)
    rh.outputs = [{"code": 804, "msg": "运行中"}] * 10000
    try:
        rh.generate_images("p", out_dir=tempfile.mkdtemp())
        assert False
    except RunningHubError as e:
        assert "超时" in str(e)


def test_create_failure():
    rh = ScriptedRH()
    rh.posts = []
    rh._post_original = rh._post

    def fail_create(path, payload, timeout=60):
        return {"code": -1, "msg": "余额不足"}

    rh._post = fail_create
    try:
        rh.create_task([])
        assert False
    except RunningHubError as e:
        assert "余额不足" in str(e)
