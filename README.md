# 群像 astrbot_plugin_groupportrait

玩家把立绘发到群里绑定 QQ 号,管理员一条 `/群像`:插件读取最近群聊 → LLM 构图(选场景/选出场角色/自动挑绑定玩家的立绘作参考图) → 按配置通道生图(A=RunningHub 工作流 / B=直连生图 API) → 回发群里。

需求正本:`docs-agent/待落地需求/群像AstrBot插件_20260910.md`(11 决策共识案)。

## 命令面

| 命令 | 权限 | 说明 |
|---|---|---|
| `/立绘绑定` | 所有人 | 回复一张图片发送,或**先发图再紧跟指令**(10 分钟窗口);绑定后即可被群像选中 |
| `/立绘换绑` | 所有人 | 覆盖已有立绘 |
| `/立绘解绑` | 所有人 | 解除绑定 |
| `/立绘查看 [@某人]` | 所有人 | 回显立绘与绑定状态 |
| `/立绘代绑 @某人` | 管理员 | 带图/回复图为他人绑定 |
| `/立绘清绑 @某人` | 管理员 | 移除他人绑定 |
| `/群像` | 管理员 | 触发全链路:上下文 → 构图 → 生图 → 发群;生成中重复触发直接拒绝 |
| `/生图通道` | 管理员 | 查看当前生图通道与 key/model 装配状态 |
| `/生图模型 [序号或名称]` | 管理员 | B 通道:拉取服务端 `/models` 模型列表;带参数则选中并持久化 |

## 安装（AstrBot ≥ v4.28 实测）

metadata.yaml 在仓库根目录（name/desc/version/author/repo 五字段），安装报「未找到 metadata.yaml」时**不是文件缺失**，而是 AstrBot 对 github.com 仓库只走匿名通道（raw 预检 + zip 下载），**私有仓库会整体 404 并误报此错**。两条安装通道任选：

1. **GitHub 导入（要求仓库公开）**：WebUI 插件页 → 从 GitHub 导入 → 填仓库地址。仓库转公开后即可用此通道；仓库内 `docs-agent/` 为内部工作文档，转公开前应先移出 git 跟踪。
2. **上传安装（私有仓库可用，v4.28 已实测通过）**：

   ```bash
   python3 scripts/build_plugin_zip.py   # 产出 dist/astrbot_plugin_groupportrait-main.zip（与 GitHub zipball 同布局）
   ```

   WebUI 插件页 → 上传安装 → 选该 zip。或由维护者把 zip 挂到 release 附件供下载后上传。

## 配置(key 链与占位工作流)

`_conf_schema.json` 全量面板。RunningHub key 解析顺序(任何一处命中即可,**不要求明文入库**):

1. 插件配置 `rh_api_key`
2. 环境变量 `RUNNINGHUB_API_KEY`
3. 兜底文件 `rh_key_file`(默认 `~/.hermes/scripts/runninghub_krea2.json`,复用现成 hermes 基建)

占位工作流(D8):默认接 Krea2 多图参考编辑工作流(webappId `2095419953062121474`,节点 19 提示词 / 36 负面 / 2,34,35 参考图 / 10 种子 / 40 比例),全部节点映射做成配置;正式工作流建好后只改配置不改代码。入画人数 = min(`max_characters`(D9 默认 4), 参考图节点数)。

### 生图通道(A | B 二选一,`channel` 配置,默认 A)

- **A `runninghub`(默认)**:RunningHub 工作流,仅开源模型;全部 `rh_*` / `node_*` 配置照旧,老用户零改动。
- **B `direct`**:直连 URL 生图 API,尽量兼容 OpenAI images API 形状——有参考图走 `POST {base}/images/edits`(图生图,multipart,单图字段 `image`、多图 `image[]`),无参考图走 `POST {base}/images/generations`(JSON);key 以 `Authorization: Bearer` 携带。配置 `channel=direct` + `direct_base_url`(如 `https://api.xxx.com/v1`)+ `direct_api_key`(回退 env `DIRECT_IMAGE_API_KEY` → `OPENAI_API_KEY`)。

B 通道模型选择:管理员 `/生图模型` 在线拉 `GET {base}/models` 列表呈现,再 `/生图模型 <序号或名称>` 选中(持久化到插件数据目录 `channel_overrides.json`,覆盖 `direct_model` 配置)。响应兼容 `url` 与 `b64_json` 两种返回。LLM 构图/选参考图逻辑两通道完全复用,仅生图执行段分发。

B 通道差异项:`direct_size` 默认 `1536x1024`(横幅,对齐 A 通道 16:9);OpenAI 形状无 negative/seed 参数,`direct_merge_negative=true` 时构图负面词以 `Negative prompt:` 并入提示词,`seed` 忽略;入画人数 = min(`max_characters`, `direct_max_refs`(默认 4))。

## 开发

```bash
python3 tests/run_all.py        # 全部单测 + /群像 dry-run + 插件冒烟(stub 宿主)
python3 -m compileall main.py core
python3 scripts/dev_sample.py   # 真跑 1 张 RunningHub 小样(验收④,只烧 1 张)
```

小样留档:`docs-agent/evidence/群像-RunningHub小样/`(成图 + provenance.json 含 taskId/SHA-256)。

## 结构

```
main.py        # AstrBot 适配层:命令面/消息组件鸭子扫描/发送
core/          # 纯逻辑(不 import astrbot):绑定存储/上下文采集/LLM 构图/RunningHub 客户端/流水线
templates/     # 构图系统提示词模板(双端共享资产,酒馆版直接复用)
tests/         # stub 宿主 + 单测 + dry-run + 冒烟;run_all.py 总入口
scripts/       # dev_sample.py 真跑小样
```

## TODO(第二阶段 · SillyTavern 扩展移植,本期不实施)

- 形态:ST 全局/UI 扩展(JS),复用 `templates/compose_system_prompt.md` 构图模板
- 上下文源:ST 聊天数组;角色绑定映射 ST persona/character 体系
- 生图:同一 RunningHub 适配逻辑移植(或走 ST 自带 Image Generation 扩展自定义源)
- 细节待 AstrBot 版验收后另开澄清轮(正本「第二阶段」节)
