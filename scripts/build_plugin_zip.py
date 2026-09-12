"""构建与 GitHub zipball 同布局的插件安装包(给 AstrBot WebUI 上传安装用)。

用法: python3 scripts/build_plugin_zip.py
产出: dist/astrbot_plugin_groupportrait-main.zip
布局: 顶层目录 astrbot_plugin_groupportrait-main/(与 GitHub 分支 zip 一致,AstrBot 安装器可解析)。
"""
import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PREFIX = "astrbot_plugin_groupportrait-main/"
OUT_DIR = os.path.join(REPO_ROOT, "dist")
OUT_ZIP = os.path.join(OUT_DIR, "astrbot_plugin_groupportrait-main.zip")


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    if os.path.exists(OUT_ZIP):
        os.remove(OUT_ZIP)
    subprocess.run(
        [
            "git",
            "archive",
            f"--prefix={PREFIX}",
            "-o",
            OUT_ZIP,
            "HEAD",
        ],
        cwd=REPO_ROOT,
        check=True,
    )
    size = os.path.getsize(OUT_ZIP)
    print(f"OK: {OUT_ZIP} ({size} bytes)")
    print("AstrBot WebUI → 插件 → 上传安装 → 选此 zip 即可。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
