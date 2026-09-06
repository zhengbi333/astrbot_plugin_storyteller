"""衣柜与穿搭：Bot 的衣柜（有上限）+ 当前穿搭。

设计要点（独立实现，不与外部插件雷同）：
- 衣柜是 Bot 的衣物库（有数量上限），由 LLM 生成时确定、之后可改写；
- 当前穿搭由 LLM 根据天气/场合/心情/人格从衣柜里选，可读写；
- 提供接口供 LLM 工具读取与修改衣柜、穿搭。
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

_WARDROBE_FILE = "wardrobe.json"
_CLOSET_LIMIT = 70


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def default_wardrobe() -> dict[str, Any]:
    return {
        "closet": [],
        "outfit": {"items": [], "note": "", "updated_at": ""},
    }


class WardrobeStore:
    """衣柜与穿搭的读写。"""

    def __init__(self, data_dir: Path):
        self._file = Path(data_dir) / _WARDROBE_FILE
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        data = default_wardrobe()
        try:
            if self._file.exists():
                raw = json.loads(self._file.read_text(encoding="utf-8-sig"))
                if isinstance(raw, dict):
                    if isinstance(raw.get("closet"), list):
                        data["closet"] = raw["closet"]
                    if isinstance(raw.get("outfit"), dict):
                        data["outfit"] = raw["outfit"]
        except Exception:
            pass
        # 0.151 迁移：旧数据 important=bool 视为自动重要（important_auto）；manual 独立可取消
        for item in data.get("closet", []):
            if isinstance(item, dict) and "important_auto" not in item:
                item["important_auto"] = bool(item.get("important"))
            elif isinstance(item, dict):
                item["important_auto"] = bool(item.get("important_auto"))
        return data

    def _save(self) -> None:
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            self._file.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def load(self) -> dict[str, Any]:
        closet = []
        for item in self._data.get("closet", []):
            if not isinstance(item, dict):
                continue
            auto = bool(item.get("important_auto"))
            manual = bool(item.get("manual"))
            closet.append(
                {
                    **item,
                    "important_auto": auto,
                    "manual": manual,
                    "important": auto or manual,  # 兼容旧前端/读取
                }
            )
        return {
            "closet": closet,
            "outfit": dict(self._data.get("outfit", {})),
        }

    def closet_items(self) -> list[dict[str, Any]]:
        return self.load().get("closet", [])

    def current_outfit(self) -> dict[str, Any]:
        return dict(self._data.get("outfit", {}))

    def add_item(self, name: str, category: str = "", note: str = "") -> dict[str, Any]:
        name = (name or "").strip()
        if not name:
            raise ValueError("衣物名不能为空")
        closet = self._data.setdefault("closet", [])
        if any(i.get("name") == name for i in closet):
            raise ValueError("衣柜里已有这件衣物")
        if len(closet) >= _CLOSET_LIMIT:
            raise ValueError(f"衣柜已满（上限 {_CLOSET_LIMIT} 件），请先清理")
        closet.append(
            {
                "id": uuid.uuid4().hex[:8],
                "name": name[:60],
                "category": (category or "").strip()[:40],
                "note": (note or "").strip()[:120],
                # 用户/对话添加的衣物视为自动重要（蓝线，置换保留，只能手动删除）
                "important_auto": True,
                "manual": False,
            }
        )
        self._save()
        return self.load()

    def add_items(self, items: list[dict[str, Any]], *, important: bool = False) -> dict[str, Any]:
        """批量新增（生成预览「应用」用）：容量校验，满则抛错（不部分写入）。"""
        closet = self._data.setdefault("closet", [])
        incoming: list[dict[str, Any]] = []
        for it in items if isinstance(items, list) else []:
            if not isinstance(it, dict):
                continue
            name = str(it.get("name") or "").strip()[:60]
            if not name or any(i.get("name") == name for i in closet) or any(
                i.get("name") == name for i in incoming
            ):
                continue
            incoming.append(
                {
                    "id": str(it.get("id") or uuid.uuid4().hex[:8])[:20],
                    "name": name,
                    "category": str(it.get("category") or "").strip()[:40],
                    "note": str(it.get("note") or "").strip()[:120],
                    "important_auto": bool(important),
                    "manual": False,
                }
            )
        if len(closet) + len(incoming) > _CLOSET_LIMIT:
            raise ValueError(f"衣柜已满（上限 {_CLOSET_LIMIT} 件），请先清理后再应用")
        closet.extend(incoming)
        self._save()
        return self.load()

    def mark_item(self, item_id: str, manual: bool) -> dict[str, Any]:
        """手动「重要」标记（0.151）：manual=True 橙色边线；manual=False 取消（重要仅剩自动来源）。"""
        closet = self._data.setdefault("closet", [])
        for item in closet:
            if str(item.get("id") or "") == str(item_id or ""):
                item["manual"] = bool(manual)
                self._save()
                break
        return self.load()

    def mark_names(self, names: list[str]) -> dict[str, Any]:
        """按名称批量标记自动重要（0.151：用户夸奖当前穿搭的衣物/对话提及）。"""
        wanted = {str(n or "").strip() for n in (names or [])} - {""}
        closet = self._data.setdefault("closet", [])
        changed = False
        for item in closet:
            if str(item.get("name") or "").strip() in wanted and not item.get("important_auto"):
                item["important_auto"] = True
                changed = True
        if changed:
            self._save()
        return self.load()

    def remove_item(self, name: str) -> dict[str, Any]:
        self._data["closet"] = [
            i for i in self._data.get("closet", []) if i.get("name") != name
        ]
        self._save()
        return self.load()

    def set_outfit(self, items: list[str], note: str = "") -> dict[str, Any]:
        self._data["outfit"] = {
            "items": [str(x).strip()[:60] for x in (items or []) if str(x).strip()][:8],
            "note": (note or "").strip()[:200],
            "updated_at": _now(),
        }
        self._save()
        return self.load()

    def _is_kept(self, item: dict[str, Any]) -> bool:
        return bool(item.get("important_auto")) or bool(item.get("manual"))

    def set_closet(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        """整体替换衣柜（生成穿搭时确定衣物）——0.151：重要（important_auto/manual）衣物保留，只替换普通衣物。"""
        normalized: list[dict[str, Any]] = []
        for it in items if isinstance(items, list) else []:
            if isinstance(it, dict) and str(it.get("name") or "").strip():
                normalized.append(
                    {
                        "id": str(it.get("id") or uuid.uuid4().hex[:8])[:20],
                        "name": str(it.get("name") or "").strip()[:60],
                        "category": str(it.get("category") or "").strip()[:40],
                        "note": str(it.get("note") or "").strip()[:120],
                        "important_auto": False,
                        "manual": False,
                    }
                )
        kept = [i for i in self._data.get("closet", []) if self._is_kept(i)]
        room = max(0, _CLOSET_LIMIT - len(kept))
        merged = kept + normalized[:room]
        self._data["closet"] = merged
        self._save()
        return self.load()

    def replace_all(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        """一键置换衣柜：清空非重要衣物后加入新生成件（重要衣物保留，只能手动删除）。"""
        kept = [i for i in self._data.get("closet", []) if self._is_kept(i)]
        room = max(0, _CLOSET_LIMIT - len(kept))
        normalized: list[dict[str, Any]] = []
        for it in items if isinstance(items, list) else []:
            if not isinstance(it, dict):
                continue
            name = str(it.get("name") or "").strip()[:60]
            if not name or any(i.get("name") == name for i in kept) or any(
                i.get("name") == name for i in normalized
            ):
                continue
            normalized.append(
                {
                    "id": str(it.get("id") or uuid.uuid4().hex[:8])[:20],
                    "name": name,
                    "category": str(it.get("category") or "").strip()[:40],
                    "note": str(it.get("note") or "").strip()[:120],
                    "important_auto": False,
                    "manual": False,
                }
            )
        self._data["closet"] = kept + normalized[:room]
        self._save()
        return self.load()


def build_wardrobe_anchor(outfit: Any) -> str:
    """把当前穿搭渲染成注入文本（仅素材，不照搬）。

    - 无穿搭：返回空串（模板里 {穿搭} 替换为空）；
    - 有穿搭：给一句「我这时穿什么」，并注明这只是语气/场合参考，不要主动晒。
    """
    if not isinstance(outfit, dict):
        return ""
    items = [str(x).strip() for x in (outfit.get("items") or []) if str(x).strip()]
    if not items:
        return ""
    note = str(outfit.get("note") or "").strip()
    line = "【当前穿搭】\n" + f"你现在穿着：{'、'.join(items[:6])}。\n"
    if note:
        line += f"（今天这样穿的理由：{note[:100]}）\n"
    line += (
        "这天然影响你的语气和气质（比如随手甩一下衣角这种小动作），"
        "但不要主动提穿搭或炫耀，除非对方问起；更不要把穿搭写成已经真实发生的事。"
    )
    return line


# ---------------------------------------------------------------- 一键生成（穿搭 / 衣柜）

def build_wardrobe_generate_prompt(
    *,
    persona_desc: str = "",
    persona_injection: str = "",
    weather: str = "",
    presence: str = "",
    closet: list[Any] | None = None,
    mode: str = "outfit",
    closet_count: int = 0,
) -> str:
    """构造「根据衣柜选今天的穿搭」或「生成衣柜」的提示词。

    mode="outfit"：从现有衣柜里选 2~5 件，输出 {"items": [...], "note": "理由"}；
    mode="closet"：生成一整个衣柜（closet_count 指定件数，0=默认 10~25 件），输出 {"closet": [...]}。
    0.151：注入角色人格注入体（性别/身份/性格——衣物必须贴合，男生不生成裙装等女性化衣物）、
    语气风格、天气、状态；现有衣柜仅作「避免同款」参考（后端还会做相似度去重）。
    """
    closet_lines = ""
    if closet:
        closet_lines = "、".join(
            f"{c.get('name', '')}（{c.get('category', '')}）" for c in closet[:30] if isinstance(c, dict)
        )
    if mode == "outfit":
        lines = [
            "请为这个角色决定今天穿什么。只输出一个 JSON 对象，不要任何解释或代码块标记：",
            '{"items": ["衣服名", "鞋", "配饰"], "note": "今天这样穿的理由"}',
            "要求：",
            "1. items 必须从下面给出的衣柜里选 2~5 件，用衣服的原名；",
            "2. 结合天气、场合、心情、人格选，理由要像真人随口一句话；",
            "3. 衣柜里没有合适时就选最贴近的；不要凭空造出衣柜里没有的衣服。",
        ]
        if closet_lines:
            lines.append(f"她的衣柜：{closet_lines}")
    else:
        n_text = f"{closet_count}件" if closet_count and closet_count > 0 else "10~25 件"
        lines = [
            "请为这个角色生成一个衣柜。只输出一个 JSON 对象，不要任何解释或代码块标记：",
            '{"closet": [{"name": "衣服/鞋/配饰名", "category": "类别", "note": "一句话备注"}]}',
            "要求：",
            f"1. 本次生成 {n_text}，风格与款式**必须贴合角色的性别、身份、性格与生活场景**——"
            "角色是男生就给男生的日常衣着（T恤/衬衫/卫衣/牛仔裤/运动鞋等男士单品），"
            "绝不要出现裙装、连衣裙、丝袜等女性化单品，除非人物设定明确是女生；",
            "2. category 用短词（上衣/外套/裤装/鞋履/包/配饰等）；note 一句玩笑或备注；",
            "3. **与现有衣柜明显不同款**：不要重复/微调现有清单里的款式，"
            "名称与风格要有区分度（比如有了白T恤就来黑卫衣而不是再来一件白T恤）；",
        ]
        if closet_lines:
            lines.append(f"现有衣柜（仅作避重参考，不要照着生成）：{closet_lines}")
        lines.append("4. 全部输出为「新增」的衣物，不要包含任何现有衣柜里的同名/同款。")
    if persona_injection:
        lines.append(f"★ 人物设定（身份/性别/性格/世界观，服装必须与之符合）：{persona_injection.strip()[:1200]}")
    if persona_desc:
        lines.append(f"角色/气质：{persona_desc.strip()}")
    if weather:
        lines.append(f"今天天气：{weather}")
    if presence:
        lines.append(f"她此刻的状态：{presence}")
    return "\n".join(lines)


def parse_wardrobe(text: str) -> dict[str, Any] | None:
    """解析 LLM 返回的穿搭/衣柜 JSON（0.150：宽松容错 + 失败记录原始输出）。"""
    from .json_util import parse_json_lenient_logged

    value = parse_json_lenient_logged(text, "衣柜生成结果")
    return value if isinstance(value, dict) else None
