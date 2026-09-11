#!/usr/bin/env python3
"""真跑 1 张 RunningHub 小样(验收④:只烧 1 张,批量留给用户)。

用法:
  python3 scripts/dev_sample.py
  python3 scripts/dev_sample.py --ref ~/some.png --prompt "..." --out /tmp/sample
key 链:--api-key > env RUNNINGHUB_API_KEY > --key-file(默认 ~/.hermes/scripts/runninghub_krea2.json)
"""
import argparse
import hashlib
import json
import os
import struct
import sys
import time
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.runninghub import RunningHubClient, RunningHubError  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def make_test_png(path, size=256):
    """程序化生成渐变测试参考图(不依赖 PIL)。"""
    raw = bytearray()
    for y in range(size):
        raw.append(0)
        for x in range(size):
            raw += bytes((x * 255 // size, y * 255 // size, 128))

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
                + chunk(b"IEND", b""))
    return path


def resolve_key(args):
    if args.api_key:
        return args.api_key, "--api-key"
    key = os.environ.get("RUNNINGHUB_API_KEY", "").strip()
    if key:
        return key, "env RUNNINGHUB_API_KEY"
    key_file = os.path.expanduser(args.key_file)
    with open(key_file, "r", encoding="utf-8") as f:
        k = json.load(f).get("apiKey")
    if k:
        return k, f"key_file {key_file}"
    sys.exit("[错误] 三处都没找到 RunningHub key")


def main():
    ap = argparse.ArgumentParser(description="群像:真跑 1 张 RunningHub 小样")
    ap.add_argument("--prompt",
                    default="以参考图中的角色为主角,画一幅群像插画:几个朋友深夜在霓虹灯下的网吧里开黑,"
                            "屏幕光打在脸上,插画风格,画面无文字")
    ap.add_argument("--negative", default="文字, 水印, 签名, logo, 低质量")
    ap.add_argument("--ref", default="", help="参考图路径(缺省程序化生成 256px 渐变图)")
    ap.add_argument("--out", default=os.path.join(REPO, "docs-agent", "evidence", "群像-RunningHub小样"))
    ap.add_argument("--webapp-id", default="2095419953062121474", help="占位工作流(D8:Krea2 多图参考编辑)")
    ap.add_argument("--base-url", default="https://www.runninghub.ai")
    ap.add_argument("--ratio", default="16:9 (Widescreen)")
    ap.add_argument("--mp", default="1")
    ap.add_argument("--api-key", default="")
    ap.add_argument("--key-file", default="~/.hermes/scripts/runninghub_krea2.json")
    ap.add_argument("--poll-interval", type=float, default=5)
    ap.add_argument("--timeout", type=float, default=300)
    args = ap.parse_args()

    key, key_src = resolve_key(args)
    os.makedirs(args.out, exist_ok=True)
    if args.ref:
        ref = os.path.expanduser(args.ref)
    else:
        ref = make_test_png(os.path.join(args.out, f"test_ref_{int(time.time())}.png"))
    client = RunningHubClient(api_key=key, webapp_id=args.webapp_id, base_url=args.base_url,
                              poll_interval=args.poll_interval, timeout_s=args.timeout)
    print(f"[配置] key 来源:{key_src} | webapp {args.webapp_id} | base {args.base_url}")
    print(f"[参考图] {ref}")
    t0 = time.time()
    try:
        paths = client.generate_images(args.prompt, args.negative, [ref], args.out,
                                       None, args.ratio, args.mp, prefix="小样_")
    except RunningHubError as e:
        sys.exit(f"[失败] {e}(taskId={client.last_task_id})")
    elapsed = time.time() - t0
    prov = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "purpose": "验收④:RunningHub 真跑 1 张小样",
        "key_source": key_src,
        "webappId": args.webapp_id,
        "base_url": args.base_url,
        "taskId": client.last_task_id,
        "prompt": args.prompt,
        "negative": args.negative,
        "ref_image": ref,
        "ratio": args.ratio,
        "megapixels": args.mp,
        "elapsed_s": round(elapsed),
        "outputs": [],
    }
    for p in paths:
        with open(p, "rb") as f:
            prov["outputs"].append({"path": p, "sha256": hashlib.sha256(f.read()).hexdigest(),
                                    "bytes": os.path.getsize(p)})
    prov_path = os.path.join(args.out, f"provenance_{int(time.time())}.json")
    with open(prov_path, "w", encoding="utf-8") as f:
        json.dump(prov, f, ensure_ascii=False, indent=2)
    print(f"[完成] {elapsed:.0f}s taskId={client.last_task_id}")
    for p in paths:
        print(f"  成图: {p}")
    print(f"  留档: {prov_path}")


if __name__ == "__main__":
    main()
