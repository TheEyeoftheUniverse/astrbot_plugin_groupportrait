"""直连生图 API 客户端(B 通道,OpenAI images API 形状,插件内自实现)。

链路:有参考图走 POST {base}/images/edits(图生图,multipart),无参考图走
POST {base}/images/generations(文生图,JSON);GET {base}/models 拉模型列表。
与 RunningHubClient 同鸭子接口(generate_images / ref_node_ids / timeout_s),
pipeline 无需感知通道差异,分发在装配层完成。
响应兼容两种返回:url(下载)与 b64_json(解码落盘)。
"""
import base64
import json
import logging
import mimetypes
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid

logger = logging.getLogger("groupportrait.direct_api")


class DirectAPIError(Exception):
    pass


class DirectImageClient:
    def __init__(self, base_url, api_key, model, timeout_s=300.0, size="",
                 merge_negative=False, max_refs=4):
        if not base_url:
            raise DirectAPIError("直连通道 base_url 未配置")
        if not api_key:
            raise DirectAPIError("直连通道 api_key 未配置(配置项 / env DIRECT_IMAGE_API_KEY / OPENAI_API_KEY)")
        # model 允许空构造(/生图模型 拉列表时还没选),真正生图时再校验
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_s = timeout_s
        self.size = str(size or "").strip()
        self.merge_negative = bool(merge_negative)
        self.max_refs = max(int(max_refs), 0)
        self.channel_name = "直连API"

    @property
    def ref_node_ids(self):
        """pipeline 以 len() 算入画上限;此处为配置的参考图张数上限。"""
        return [str(i) for i in range(self.max_refs)]

    # ---------- HTTP 底座(测试可覆写) ----------

    def _headers(self):
        return {"Authorization": f"Bearer {self.api_key}"}

    def _read_error(self, e):
        try:
            body = e.read().decode("utf-8")
        except Exception:
            return f"HTTP {e.code}"
        try:
            msg = json.loads(body).get("error", {})
            return f"HTTP {e.code}: {msg.get('message') if isinstance(msg, dict) else msg or body}"
        except Exception:
            return f"HTTP {e.code}: {body[:200]}"

    def _get_json(self, path, timeout=60):
        req = urllib.request.Request(self.base_url + path, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise DirectAPIError(f"GET {path} 失败: {self._read_error(e)}") from e
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise DirectAPIError(f"GET {path} 失败: {e}") from e

    def _post_json(self, path, payload, timeout=None):
        req = urllib.request.Request(self.base_url + path,
                                     data=json.dumps(payload).encode("utf-8"), method="POST")
        req.add_header("Content-Type", "application/json")
        for k, v in self._headers().items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout_s) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise DirectAPIError(f"POST {path} 失败: {self._read_error(e)}") from e
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise DirectAPIError(f"POST {path} 失败: {e}") from e

    def _post_multipart(self, path, fields, files, timeout=None):
        """fields: [(name, str)];files: [(field_name, path)];与 RunningHub _upload 同手搓边界。"""
        boundary = uuid.uuid4().hex
        body = b""
        for name, value in fields:
            body += (f"--{boundary}\r\n".encode()
                     + f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
                     + str(value).encode("utf-8") + b"\r\n")
        for field_name, path_ in files:
            if not os.path.isfile(path_):
                raise DirectAPIError(f"参考图不存在: {path_}")
            filename = os.path.basename(path_)
            ctype = mimetypes.guess_type(path_)[0] or "application/octet-stream"
            with open(path_, "rb") as f:
                content = f.read()
            body += (f"--{boundary}\r\n".encode()
                     + f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'.encode()
                     + f"Content-Type: {ctype}\r\n\r\n".encode() + content + b"\r\n")
        body += f"--{boundary}--\r\n".encode()
        req = urllib.request.Request(self.base_url + path, data=body, method="POST")
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        for k, v in self._headers().items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout_s) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise DirectAPIError(f"POST {path} 失败: {self._read_error(e)}") from e
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise DirectAPIError(f"POST {path} 失败: {e}") from e

    # ---------- 模型列表 ----------

    @staticmethod
    def parse_models(res):
        """宽容解析:OpenAI 形状 {"data":[{"id":..}]} / 纯 id 列表 / {"models":[..]}。"""
        items = None
        if isinstance(res, dict):
            items = res.get("data")
            if items is None:
                items = res.get("models")
        elif isinstance(res, list):
            items = res
        if items is None:
            raise DirectAPIError(f"模型列表响应形状不认识: {str(res)[:200]}")
        ids = []
        for it in items:
            mid = it.get("id") if isinstance(it, dict) else it
            mid = str(mid or "").strip()
            if mid:
                ids.append(mid)
        return ids

    def list_models(self):
        res = self._get_json("/models")
        return self.parse_models(res)

    # ---------- 请求构造(纯函数,可单测) ----------

    def build_prompt(self, prompt, negative=""):
        """OpenAI images 形状无 negative 参数;按配置决定是否并入提示词尾部。"""
        if negative and self.merge_negative:
            return f"{prompt}\nNegative prompt: {negative}"
        return prompt

    def build_generations_payload(self, prompt):
        payload = {"model": self.model, "prompt": prompt, "n": 1}
        if self.size:
            payload["size"] = self.size
        return payload

    def build_edits_parts(self, prompt, ref_paths):
        """返回 (文本字段, 文件字段);单图用 image,多图用 image[](OpenAI gpt-image-1 形状)。"""
        fields = [("model", self.model), ("prompt", prompt), ("n", "1")]
        if self.size:
            fields.append(("size", self.size))
        field_name = "image" if len(ref_paths) == 1 else "image[]"
        return fields, [(field_name, p) for p in ref_paths]

    # ---------- 响应解析 ----------

    def parse_images(self, res):
        """响应 data[] 里逐项取 url 或 b64_json;都没有则报错。"""
        data = (res or {}).get("data") if isinstance(res, dict) else None
        if not isinstance(data, list) or not data:
            raise DirectAPIError(f"生图响应无 data: {str(res)[:200]}")
        out = []
        for item in data:
            if not isinstance(item, dict):
                continue
            if item.get("url"):
                out.append(("url", item["url"]))
            elif item.get("b64_json"):
                out.append(("b64", item["b64_json"]))
        if not out:
            raise DirectAPIError(f"生图响应没有 url/b64_json: {str(res)[:200]}")
        return out

    def download(self, url, out_dir, prefix="groupportrait_"):
        os.makedirs(out_dir, exist_ok=True)
        ext = os.path.splitext(urllib.parse.urlparse(url).path)[1] or ".png"
        path = os.path.join(out_dir, f"{prefix}{uuid.uuid4().hex[:8]}{ext}")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=180) as r:
            data = r.read()
        with open(path, "wb") as f:
            f.write(data)
        return path

    # ---------- 完整链路(与 RunningHubClient.generate_images 同签名) ----------

    def generate_images(self, prompt, negative="", ref_paths=(), out_dir=".",
                        seed=None, ratio=None, megapixels=None, prefix="groupportrait_"):
        if not self.model:
            raise DirectAPIError("直连通道 model 未选择(配置 direct_model 或 /生图模型 选择)")
        if seed is not None:
            logger.debug("直连通道忽略 seed(OpenAI images 形状无该参数): %s", seed)
        text = self.build_prompt(prompt, negative)
        if ref_paths:
            fields, files = self.build_edits_parts(text, list(ref_paths))
            logger.info("直连通道图生图 model=%s refs=%s", self.model, len(files))
            res = self._post_multipart("/images/edits", fields, files)
        else:
            logger.info("直连通道文生图 model=%s", self.model)
            res = self._post_json("/images/generations", self.build_generations_payload(text))
        if isinstance(res, dict) and res.get("error"):
            err = res["error"]
            msg = err.get("message") if isinstance(err, dict) else err
            raise DirectAPIError(f"生图请求被拒: {msg}")
        paths = []
        for kind, val in self.parse_images(res):
            if kind == "url":
                paths.append(self.download(val, out_dir, prefix))
            else:
                os.makedirs(out_dir, exist_ok=True)
                path = os.path.join(out_dir, f"{prefix}{uuid.uuid4().hex[:8]}.png")
                with open(path, "wb") as f:
                    f.write(base64.b64decode(val))
                paths.append(path)
        if not paths:
            raise DirectAPIError("生图完成但没有产出图")
        return paths
