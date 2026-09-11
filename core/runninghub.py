"""RunningHub webapp 生图客户端(插件内自实现,API 形态对齐 ~/.hermes/scripts/runninghub_krea2.py)。

链路:上传参考图 → create 任务(nodeInfoList 覆盖节点字段) → 轮询 outputs → 下载成图。
状态码:0=完成 804=运行中 813=排队中 805=失败。
节点映射全部来自配置(DEFAULT_NODE_MAP 为 Krea2 多图参考编辑占位工作流,D8),
换正式工作流时只改配置不改代码。
"""
import json
import logging
import mimetypes
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

logger = logging.getLogger("groupportrait.runninghub")

CODE_DONE, CODE_RUNNING, CODE_QUEUED, CODE_FAILED = 0, 804, 813, 805

DEFAULT_NODE_MAP = {
    "prompt": {"node": "19", "field": "value"},
    "negative": {"node": "36", "field": "value"},
    "refs": {"nodes": ["2", "34", "35"], "field": "image"},
    "seed": {"node": "10", "field": "noise_seed"},
    "aspect": {"node": "40", "ratio_field": "aspect_ratio", "mp_field": "megapixels"},
}


class RunningHubError(Exception):
    pass


class RunningHubClient:
    def __init__(self, api_key, webapp_id, base_url="https://www.runninghub.ai",
                 instance="standard", node_map=None, poll_interval=5.0, timeout_s=300.0):
        if not api_key:
            raise RunningHubError("RunningHub api_key 未配置(配置项/env RUNNINGHUB_API_KEY/key_file 皆未找到)")
        if not webapp_id:
            raise RunningHubError("RunningHub webapp_id 未配置")
        self.api_key = api_key
        self.webapp_id = str(webapp_id)
        self.base_url = base_url.rstrip("/")
        self.instance = instance
        self.node_map = {**DEFAULT_NODE_MAP, **(node_map or {})}
        self.poll_interval = poll_interval
        self.timeout_s = timeout_s
        self.last_task_id = None

    @property
    def ref_node_ids(self):
        return list(self.node_map["refs"]["nodes"])

    # ---------- HTTP 底座(测试可覆写) ----------

    def _post(self, path, payload, timeout=60):
        req = urllib.request.Request(self.base_url + path,
                                     data=json.dumps(payload).encode("utf-8"), method="POST")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                return json.loads(e.read().decode("utf-8"))
            except Exception:
                return {"code": e.code, "msg": str(e)}

    def _upload(self, path, timeout=120):
        """本地图片 → RunningHub input 资源,返回 fileName。"""
        if not os.path.isfile(path):
            raise RunningHubError(f"参考图不存在: {path}")
        boundary = uuid.uuid4().hex
        filename = os.path.basename(path)
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as f:
            content = f.read()

        def field(name, value):
            return (f"--{boundary}\r\n".encode()
                    + f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
                    + value.encode("utf-8") + b"\r\n")

        body = field("apiKey", self.api_key) + field("fileType", "input")
        body += (f"--{boundary}\r\n".encode()
                 + f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode()
                 + f"Content-Type: {ctype}\r\n\r\n".encode() + content + b"\r\n")
        body += f"--{boundary}--\r\n".encode()
        req = urllib.request.Request(self.base_url + "/task/openapi/upload", data=body, method="POST")
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        req.add_header("Authorization", f"Bearer {self.api_key}")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            res = json.loads(r.read().decode("utf-8"))
        if res.get("code") != 0:
            raise RunningHubError(f"参考图上传失败: {res.get('msg')}")
        return res["data"]["fileName"]

    # ---------- 任务编排(纯逻辑与 IO 分离,便于单测) ----------

    def build_node_info(self, prompt, negative="", ref_names=(), seed=None, ratio=None, megapixels=None):
        """按节点映射拼 nodeInfoList(纯函数,可单测)。"""
        nm = self.node_map
        nil = [{"nodeId": nm["prompt"]["node"], "fieldName": nm["prompt"]["field"], "fieldValue": prompt}]
        if negative:
            nil.append({"nodeId": nm["negative"]["node"], "fieldName": nm["negative"]["field"],
                        "fieldValue": negative})
        slots = self.ref_node_ids
        if len(ref_names) > len(slots):
            raise RunningHubError(f"参考图 {len(ref_names)} 张超出工作流参考节点数 {len(slots)}")
        for node_id, name in zip(slots, ref_names):
            nil.append({"nodeId": node_id, "fieldName": nm["refs"]["field"], "fieldValue": name})
        if seed is not None:
            nil.append({"nodeId": nm["seed"]["node"], "fieldName": nm["seed"]["field"], "fieldValue": str(seed)})
        if ratio:
            nil.append({"nodeId": nm["aspect"]["node"], "fieldName": nm["aspect"]["ratio_field"],
                        "fieldValue": ratio})
        if megapixels:
            nil.append({"nodeId": nm["aspect"]["node"], "fieldName": nm["aspect"]["mp_field"],
                        "fieldValue": str(megapixels)})
        return nil

    def create_task(self, node_info):
        payload = {"apiKey": self.api_key, "workflowId": self.webapp_id,
                   "instanceType": self.instance, "nodeInfoList": node_info}
        res = self._post("/task/openapi/create", payload)
        if res.get("code") != 0:
            raise RunningHubError(f"任务提交失败({res.get('code')}): {res.get('msg')}")
        task_id = (res.get("data") or {}).get("taskId")
        if not task_id:
            raise RunningHubError(f"任务提交未返回 taskId: {res}")
        self.last_task_id = task_id
        logger.info("RunningHub 任务已提交 webappId=%s taskId=%s", self.webapp_id, task_id)
        return task_id

    def poll_outputs(self, task_id):
        """轮询至完成,返回成图 URL 列表;失败/超时抛 RunningHubError。"""
        t0 = time.time()
        while True:
            if time.time() - t0 > self.timeout_s:
                raise RunningHubError(f"生图超时(>{int(self.timeout_s)}s),taskId={task_id}")
            time.sleep(self.poll_interval)
            q = self._post("/task/openapi/outputs", {"apiKey": self.api_key, "taskId": task_id})
            code = q.get("code")
            if code == CODE_DONE:
                urls = []
                for item in q.get("data") or []:
                    url = item.get("fileUrl") or item.get("url")
                    if url:
                        urls.append(url)
                if not urls:
                    raise RunningHubError(f"任务完成但没有产出图: {q}")
                logger.info("RunningHub 任务完成 taskId=%s 耗时 %.0fs", task_id, time.time() - t0)
                return urls
            if code == CODE_FAILED:
                raise RunningHubError(f"生图任务失败: {q.get('msg')} (taskId={task_id})")
            if code in (CODE_RUNNING, CODE_QUEUED):
                continue
            raise RunningHubError(f"轮询异常 code={code}: {q.get('msg')} (taskId={task_id})")

    def download(self, url, out_dir, prefix="groupportrait"):
        os.makedirs(out_dir, exist_ok=True)
        ext = os.path.splitext(urllib.parse.urlparse(url).path)[1] or ".png"
        path = os.path.join(out_dir, f"{prefix}{uuid.uuid4().hex[:8]}{ext}")
        data = urllib.request.urlopen(urllib.request.Request(url), timeout=180).read()
        with open(path, "wb") as f:
            f.write(data)
        return path

    def generate_images(self, prompt, negative="", ref_paths=(), out_dir=".",
                        seed=None, ratio=None, megapixels=None, prefix="groupportrait_"):
        """完整链路:上传 → 建 → 轮询 → 下载,返回本地成图路径列表。"""
        names = []
        for p in ref_paths:
            names.append(self._upload(p))
            logger.info("参考图已上传: %s", p)
        node_info = self.build_node_info(prompt, negative, names, seed, ratio, megapixels)
        task_id = self.create_task(node_info)
        urls = self.poll_outputs(task_id)
        return [self.download(u, out_dir, prefix) for u in urls]
