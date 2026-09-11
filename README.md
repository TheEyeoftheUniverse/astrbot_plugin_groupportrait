# 群像 astrbot_plugin_groupportrait

玩家把立绘发到群里绑定 QQ 号,管理员一条 `/群像`:插件读取最近群聊 → LLM 构图(选场景/选出场角色/自动挑绑定玩家的立绘作参考图) → RunningHub 工作流生图 → 回发群里。

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

## 配置(key 链与占位工作流)

`_conf_schema.json` 全量面板。RunningHub key 解析顺序(任何一处命中即可,**不要求明文入库**):

1. 插件配置 `rh_api_key`
2. 环境变量 `RUNNINGHUB_API_KEY`
3. 兜底文件 `rh_key_file`(默认 `~/.hermes/scripts/runninghub_krea2.json`,复用现成 hermes 基建)

占位工作流(D8):默认接 Krea2 多图参考编辑工作流(webappId `2095419953062121474`,节点 19 提示词 / 36 负面 / 2,34,35 参考图 / 10 种子 / 40 比例),全部节点映射做成配置;正式工作流建好后只改配置不改代码。入画人数 = min(`max_characters`(D9 默认 4), 参考图节点数)。

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
