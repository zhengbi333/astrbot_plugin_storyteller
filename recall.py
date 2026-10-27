"""撤回：发现自己上一条说得不合适，在时限内把它撤回来。

为什么值得做：人说错话会「啊不对，我重说」，机器人只会硬顶着。这是"像人"的一部分。

安全设计（默认关）：
- 只在**对方明确指出理解错了 / 你说错话了**时才撤回，不做"自己觉得不好"的模糊判断
  （那种判断很容易把正常发言撤掉，比不撤更糟）；
- 只撤**自己刚发的最后一条**，且必须在 OneBot 的 2 分钟时限内；
- 一个会话一次只留最近一条可撤记录；
- 撤回失败一律静默（不影响正常回复）。

触发词刻意保守：宁可少撤，不可乱撤。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

# OneBot 撤回时限（秒）。官方是 2 分钟，留 5 秒余量。
RECALL_WINDOW = 115

# 只有当对方的话**明确指向"你说错了/理解错了"**才撤。
TRIGGERS: tuple[str, ...] = (
    "不是这个意思",
    "我不是这个意思",
    "我说的是",
    "你理解错了",
    "你误会了",
    "你说错了",
    "你说的不对",
    "答非所问",
    "没听懂我",
    "重新回答",
    "撤回",
)

# 这些词一出现就**不要**撤（可能只是普通对话里带到了上面的词）
BLOCKERS: tuple[str, ...] = (
    "不用撤回",
    "别撤回",
    "算了",
)


class RecallError(Exception):
    """撤回失败（内部用，外部静默）。"""


@dataclass
class SentRecord:
    message_id: str
    text: str
    at: float = field(default_factory=time.time)

    def expired(self, window: float = RECALL_WINDOW) -> bool:
        return (time.time() - self.at) > window


@dataclass
class RecallBook:
    """每个会话最近一条自己发的消息（用来撤回）。"""

    records: dict[str, SentRecord] = field(default_factory=dict)

    def remember(self, session: str, message_id: str, text: str) -> None:
        key = str(session or "")
        mid = str(message_id or "").strip()
        if not key or not mid:
            return
        self.records[key] = SentRecord(message_id=mid, text=str(text or ""))

    def take(self, session: str) -> SentRecord | None:
        """取出并清掉（撤回只做一次）。"""
        return self.records.pop(str(session or ""), None)

    def peek(self, session: str) -> SentRecord | None:
        return self.records.get(str(session or ""))


def should_recall(new_text: str) -> str:
    """对方这句话是不是在说「你理解错了/你说错了」。返回触发词，空串表示不撤。"""
    body = str(new_text or "").strip()
    if not body:
        return ""
    for blocked in BLOCKERS:
        if blocked in body:
            return ""
    for word in TRIGGERS:
        if word in body:
            return word
    return ""


def plan(session: str, new_text: str, book: RecallBook) -> SentRecord | None:
    """判断要不要撤、撤哪条。返回待撤记录或 None。"""
    if not should_recall(new_text):
        return None
    record = book.peek(session)
    if record is None:
        return None
    if record.expired():
        book.take(session)
        return None
    return record


def message_id_of(sent: object) -> str:
    """从 AstrBot 的发送结果里尽量抠出 message_id。"""
    for attr in ("message_id", "id"):
        value = getattr(sent, attr, None)
        if value:
            return str(value)
    # 有些版本返回 dict / list
    if isinstance(sent, dict):
        for key in ("message_id", "id"):
            if sent.get(key):
                return str(sent[key])
    if isinstance(sent, (list, tuple)) and sent:
        return message_id_of(sent[0])
    return ""


async def recall(bot: object, message_id: str) -> bool:
    """调 OneBot 的 delete_msg。失败抛 RecallError（调用方静默处理）。"""
    mid = str(message_id or "").strip()
    if not mid:
        raise RecallError("没有 message_id")
    call = getattr(bot, "call_action", None)
    if not callable(call):
        raise RecallError("当前 Bot 不支持 call_action（可能不是 OneBot）")
    try:
        await call("delete_msg", message_id=mid)
    except Exception as exc:
        raise RecallError(f"delete_msg 失败：{type(exc).__name__}: {exc}") from exc
    return True
