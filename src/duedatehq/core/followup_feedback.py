from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


FollowupSignal = Literal["correction", "missing_info", "drill_down", "none"]


@dataclass(frozen=True, slots=True)
class FollowupClassification:
    signal: FollowupSignal
    reason: str


def classify_followup(last_turn: dict | None, user_input: str) -> FollowupClassification:
    if not last_turn:
        return FollowupClassification("none", "no previous turn")

    lowered = user_input.strip().casefold()
    if not lowered:
        return FollowupClassification("none", "empty input")

    if _contains_any(
        lowered,
        [
            "不对",
            "不是这个",
            "不是这",
            "你理解错了",
            "理解错了",
            "说错了",
            "搞错了",
            "错了",
            "不应该",
            "不要这个",
            "不是我要的",
            "wrong",
            "not that",
            "that's not right",
            "not what i meant",
            "you misunderstood",
            "incorrect",
        ],
    ):
        return FollowupClassification("correction", "explicit correction phrase")

    if _looks_like_missing_info_request(lowered):
        return FollowupClassification("missing_info", "question asks for missing context or source")

    if _contains_any(
        lowered,
        [
            "展开",
            "详细",
            "更多",
            "继续",
            "看一下",
            "show me",
            "tell me more",
            "more detail",
            "drill down",
        ],
    ):
        return FollowupClassification("drill_down", "asks to inspect further")

    return FollowupClassification("none", "new intent or neutral continuation")


def _looks_like_missing_info_request(lowered: str) -> bool:
    question_tokens = [
        "为什么",
        "为何",
        "怎么",
        "什么",
        "谁",
        "哪",
        "缺",
        "少",
        "why",
        "what",
        "who",
        "when",
        "where",
        "missing",
        "source",
        "history",
    ]
    field_tokens = [
        "来源",
        "历史",
        "变更",
        "原因",
        "文件",
        "资料",
        "字段",
        "日期",
        "客户",
        "状态",
        "缺什么",
        "谁改",
        "source",
        "history",
        "changed",
        "missing",
        "documents",
        "field",
        "date",
        "status",
        "client",
    ]
    return _contains_any(lowered, question_tokens) and _contains_any(lowered, field_tokens)


def _contains_any(text: str, tokens: list[str]) -> bool:
    return any(token in text for token in tokens)
