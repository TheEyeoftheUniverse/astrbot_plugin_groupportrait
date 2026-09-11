"""LLM 构图(正本 §3):群聊上下文 + 绑定玩家清单 → 结构化构图 JSON。

输出契约:{scene, characters[{qq,nickname,action,expression}], selected_refs, negative}
解析失败重试一次;negative 强制兜底「文字/水印/签名」(D9 画面禁文字)。
"""
import json
import re
import time

DEFAULT_NEGATIVE = "文字, 水印, 签名, logo, 低质量, 模糊"


class ComposeError(Exception):
    pass


def render_messages(messages):
    """消息 → 编号时间线文本(昵称 + QQ + 内容 + 时间)。"""
    lines = []
    for i, m in enumerate(messages, 1):
        ts = m.get("ts")
        clock = time.strftime("%H:%M", time.localtime(ts)) if isinstance(ts, (int, float)) else "--:--"
        lines.append(f"{i}. [{clock}] {m.get('nickname')}({m.get('qq')}): {m.get('text')}")
    return "\n".join(lines)


def render_players(players_by_qq):
    """绑定玩家清单(含活跃度标注,辅助 LLM 挑最近活跃者)。"""
    lines = []
    for qq, p in players_by_qq.items():
        lines.append(f"- {p['nickname']}({qq}) 立绘标识:{p['ref_id']} 最近发言:{p.get('active', 0)} 条")
    return "\n".join(lines)


def build_user_prompt(messages_text, players_text, max_characters):
    return (
        f"以下是本群最近的群聊记录:\n{messages_text}\n\n"
        f"以下是已绑定立绘的玩家(立绘标识即参考图编号):\n{players_text}\n\n"
        f"请据此输出构图 JSON:入画不超过 {max_characters} 人,"
        f"优先挑选最近活跃且已绑定立绘的玩家。"
    )


def fill_template(template, **kw):
    """模板占位符替换(用 {{key}} 形式,避免与 JSON 花括号冲突)。"""
    out = template
    for k, v in kw.items():
        out = out.replace("{{" + k + "}}", str(v))
    return out


def extract_json(text):
    """从 LLM 输出中抠出 JSON(容忍 markdown 代码块与前后废话)。"""
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.S)
    if m:
        text = m.group(1).strip()
    i, j = text.find("{"), text.rfind("}")
    if i < 0 or j <= i:
        raise ComposeError("LLM 输出中找不到 JSON 对象")
    try:
        return json.loads(text[i:j + 1])
    except ValueError as e:
        raise ComposeError(f"JSON 解析失败: {e}") from e


def validate_composition(data, players_by_qq, max_characters):
    """校验并归一构图:超员截断、绑定解析、negative 兜底。"""
    if not isinstance(data, dict):
        raise ComposeError("构图不是 JSON 对象")
    scene = str(data.get("scene") or "").strip()
    if not scene:
        raise ComposeError("缺少 scene 场景描述")
    chars = data.get("characters") or []
    if not isinstance(chars, list):
        raise ComposeError("characters 不是数组")
    note = None
    if len(chars) > max_characters:
        note = f"入画 {len(chars)} 人超出上限,已按序截断为 {max_characters} 人"
        chars = chars[:max_characters]
    characters, selected_refs = [], []
    for c in chars:
        if not isinstance(c, dict):
            continue
        qq = str(c.get("qq", "")).strip()
        if not qq:
            continue
        p = players_by_qq.get(qq)
        ref_id = p["ref_id"] if p else ""
        characters.append({
            "qq": qq,
            "nickname": str(c.get("nickname") or (p["nickname"] if p else qq)),
            "action": str(c.get("action", "")).strip(),
            "expression": str(c.get("expression", "")).strip(),
            "ref_id": ref_id,
        })
        selected_refs.append(ref_id)
    if not characters:
        raise ComposeError("characters 为空,无人入画")
    negative = str(data.get("negative") or "").strip() or DEFAULT_NEGATIVE
    for kw in ("文字", "水印", "签名"):
        if kw not in negative:
            negative += f", {kw}"
    return {"scene": scene, "characters": characters, "selected_refs": selected_refs,
            "negative": negative, "note": note}


async def call_llm(llm, system_prompt, user_prompt, temperature=None):
    """AstrBot provider 体系(D4):text_chat 调用,对返回形态做鸭子兼容。"""
    kwargs = {"prompt": user_prompt, "system_prompt": system_prompt, "contexts": []}
    if temperature is not None:
        kwargs["temperature"] = temperature
    try:
        resp = await llm.text_chat(**kwargs)
    except TypeError:
        # 旧版 provider 不认 temperature
        kwargs.pop("temperature", None)
        resp = await llm.text_chat(**kwargs)
    if isinstance(resp, str):
        return resp
    for attr in ("completion_text", "text", "result"):
        v = getattr(resp, attr, None)
        if isinstance(v, str) and v.strip():
            return v
    raise ComposeError("LLM 返回为空")


async def compose(llm, system_prompt, user_prompt, players_by_qq, max_characters,
                  temperature=None, attempts=2):
    """构图主入口:调用 → 解析 → 校验,失败重试一次,仍失败抛 ComposeError。"""
    prompt = user_prompt
    last_err = None
    for _ in range(attempts):
        raw = await call_llm(llm, system_prompt, prompt, temperature)
        try:
            return validate_composition(extract_json(raw), players_by_qq, max_characters)
        except ComposeError as e:
            last_err = e
            prompt = user_prompt + (f"\n\n注意:上一次输出不合法({e}),"
                                    "请严格只输出一个符合契约的 JSON 对象,不要任何多余文字。")
    raise ComposeError(f"构图解析失败(重试 {attempts} 次仍未通过): {last_err}")
