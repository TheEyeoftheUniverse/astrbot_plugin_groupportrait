# grillme-群像-AstrBot插件 实现记录

## 安装修复轮（2026-09-12）

打回理由：主开发者在 AstrBot 安装失败——「未在 GitHub 仓库根目录找到 metadata.yaml 或 metadata.yml」。

### 根因结论（已实证，非猜测）

**metadata.yaml 与仓库结构完全正常（UTF-8 无 BOM，name/desc/version/author/repo 五字段齐全），唯一根因 = GitHub 仓库是私有的（`isPrivate: true`）。**

机理：AstrBot（v4.28.0 实测，源码核对）对 github.com 插件仓库一律走「匿名 archive 通道」——`transport='archive'`，先 `raw.githubusercontent.com/<repo>/<默认分支>/metadata.yaml|yml` 预检，再 codeload zip 下载，全程无凭据支持。私有仓库下匿名请求全部 404，安装器对非 200 一律 continue，两个文件名都失败后抛 `ValueError: 未在仓库根目录找到 metadata.yaml 或 metadata.yml。`——把「无权限」误报成「文件缺失」。匿名 clone 也被拒（`GIT_TERMINAL_PROMPT=0` 下 `unable to get password from user`），git 通道仅对非 github.com 域名开放。

### 复现与验证（真实安装器，非纸面推演）

环境：`/tmp/astrbot-venv`（`pip install astrbot==4.28.0` 发行版本体）。

1. **复现**：`_PluginUpdater.inspect_repository()` 对本仓库 URL → raw 双 404 → 报错原文与主开发者所见同源。对照组公开仓库 `Soulter/helloworld`（master）→ raw 200 → 预检过，差异只在可见性。
2. **真装终验**：gh 认证拉真·GitHub zipball → v4.28.0 真实 `PluginManager.install_plugin_from_file`（= WebUI 上传安装同一代码路径）→ 解压/嵌套根解析/元数据校验/依赖检查全过 → 插件加载成功（`Plugin astrbot_plugin_groupportrait (v1.0.0) by TheEyeoftheUniverse`）→ 列表可见 `activated=True`，中文 desc 完整读取。
3. **回环**：`scripts/build_plugin_zip.py`（git archive，GitHub 同布局顶层目录）出的 zip 再走一遍真实安装器 → 全绿。
4. 插件自身测试套件 47/47 PASS（含 `test_command_surface_registered`）。

证据与脚本：插件仓库 `docs-agent/evidence/安装修复轮/`（复现/终验日志 + 探测矩阵 + 两个可重跑脚本）。

### 修复与待办

- **仓库内容零改动即可装**；本轮回前 commit 只有：README 增「安装」节（两条通道+根因提示）、`scripts/build_plugin_zip.py`、`.gitignore` 加 `dist/`。metadata 未动（中文 desc 保留），既有功能文件零删改。
- **GitHub 侧动作（二选一，需协调者/主开发者拍板执行）**：
  - 方案 A（生态标准）：仓库转 public → WebUI GitHub 导入直接可用。**前置**：先剥离 git 跟踪中的 `docs-agent/`（需求案 + RunningHub provenance 含内部路径/webappId/key_file 路径，转公开即外泄）。
  - 方案 B（保持私有）：`python3 scripts/build_plugin_zip.py` 出包 → zip 挂 gitea release 附件（token 门控，同 APK 分发惯例）→ WebUI「上传安装」（已实测全绿）。
- 红线遵守：未 push（本地 commit）；未碰 docs-agent 既有内容；conf schema 未动。
