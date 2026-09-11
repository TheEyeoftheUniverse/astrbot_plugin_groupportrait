"""LLM 构图单测:JSON 抠取/校验截断/重试契约(正本 §3)。"""
import asyncio

import helpers as H  # noqa: F401
from core.composer import (ComposeError, build_user_prompt, call_llm, compose,
                           extract_json, fill_template, render_messages, render_players,
                           validate_composition)

PLAYERS = {
    "1001": {"nickname": "阿明", "ref_id": "1001.png", "active": 12},
    "1002": {"nickname": "小红", "ref_id": "1002.png", "active": 8},
}


def test_extract_json_tolerates_fences_and_preamble():
    raw = "好的,以下是构图:\n```json\n" + H.composition_json() + "\n```\n以上。"
    data = extract_json(raw)
    assert data["scene"] == "深夜网吧开黑"
    assert extract_json(H.composition_json())["scene"] == "深夜网吧开黑"


def test_extract_json_failure():
    for bad in ("", "完全没有花括号", "```json\n[1,2]\n```"):
        try:
            extract_json(bad)
            assert False, f"应解析失败: {bad!r}"
        except ComposeError:
            pass


def test_validate_cap_truncation_and_negative():
    chars = tuple((str(1000 + i), f"玩家{i}", "动作", "表情") for i in range(1, 6))
    data = __import__("json").loads(H.composition_json(chars=chars))
    out = validate_composition(data, PLAYERS, max_characters=3)
    assert len(out["characters"]) == 3
    assert "截断" in out["note"]
    # 只有 1001/1002 已绑定 → ref_id 有值;其余为空
    assert out["characters"][0]["ref_id"] == "1001.png"
    assert out["characters"][2]["ref_id"] == ""
    for kw in ("文字", "水印", "签名"):
        assert kw in out["negative"]


def test_validate_scene_required():
    data = __import__("json").loads('{"scene": "", "characters": []}')
    try:
        validate_composition(data, PLAYERS, 4)
        assert False
    except ComposeError as e:
        assert "scene" in str(e)


def test_render_helpers():
    msgs = [{"nickname": "阿明", "qq": "1001", "text": "开黑吗", "ts": 1750000000}]
    text = render_messages(msgs)
    assert "阿明(1001)" in text and "开黑吗" in text
    players_text = render_players(PLAYERS)
    assert "1001.png" in players_text and "12 条" in players_text
    user = build_user_prompt(text, players_text, 3)
    assert "不超过 3 人" in user


def test_fill_template():
    out = fill_template("上限 {{max_characters}} 人,{{max_characters}} 为占位", max_characters=3)
    assert "{{" not in out and out.count("3") >= 2


def test_call_llm_duck_shapes():
    class Obj:
        completion_text = H.composition_json()

        async def text_chat(self, **kw):
            return self

    assert asyncio.run(call_llm(Obj(), "s", "u")) == H.composition_json()
    assert asyncio.run(call_llm(H.FakeLLM([H.composition_json()]), "s", "u"))


def test_compose_retry_then_success():
    llm = H.FakeLLM(["抱歉我不会 JSON", H.composition_json()])
    out = asyncio.run(compose(llm, "sys", "user", PLAYERS, 3))
    assert out["scene"] == "深夜网吧开黑"
    assert len(llm.prompts) == 2
    assert "上一次输出不合法" in llm.prompts[1]["prompt"]


def test_compose_retry_exhausted():
    llm = H.FakeLLM(["不是JSON", "还是不是JSON"])
    try:
        asyncio.run(compose(llm, "sys", "user", PLAYERS, 3))
        assert False
    except ComposeError as e:
        assert "2 次" in str(e)
    assert len(llm.prompts) == 2
