from typing import Any, Dict
import logging

from pypinyin import lazy_pinyin, Style

logger = logging.getLogger(__name__)

# 匹配优先级
_PRIORITY_EXACT = 0
_PRIORITY_SUBSTR = 1
_PRIORITY_PINYIN = 2
_PRIORITY_EDIT_DIST = 3


def _levenshtein(a: str, b: str) -> int:
    """计算两个字符串的 Levenshtein 编辑距离"""
    if len(a) < len(b):
        return _levenshtein(b, a)
    if not b:
        return len(a)

    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            cost = 0 if ca == cb else 1
            curr.append(min(curr[j] + 1, prev[j + 1] + 1, prev[j] + cost))
        prev = curr
    return prev[-1]


def _get_pinyin_forms(text: str) -> tuple[str, str]:
    """返回 (全拼, 首字母) 的小写形式"""
    full = "".join(lazy_pinyin(text, style=Style.NORMAL))
    initials = "".join(lazy_pinyin(text, style=Style.FIRST_LETTER))
    return full.lower(), initials.lower()


def _match_member(
    keyword: str,
    card: str,
    nickname: str,
    exact: bool,
) -> tuple[int, str] | None:
    """尝试匹配一个成员，返回 (优先级, 命中字段) 或 None

    优先级越小越好。exact=True 时仅做精确匹配。
    """
    kw_lower = keyword.lower()

    # --- 精确匹配 ---
    if card and card.lower() == kw_lower:
        return _PRIORITY_EXACT, "群昵称"
    if nickname and nickname.lower() == kw_lower:
        return _PRIORITY_EXACT, "QQ昵称"

    if exact:
        return None

    # --- 子串匹配 ---
    if card and kw_lower in card.lower():
        return _PRIORITY_SUBSTR, "群昵称"
    if nickname and kw_lower in nickname.lower():
        return _PRIORITY_SUBSTR, "QQ昵称"

    # --- 拼音匹配 ---
    kw_full_py, kw_initials_py = _get_pinyin_forms(keyword)
    for name, field in [(card, "群昵称"), (nickname, "QQ昵称")]:
        if not name:
            continue
        full_py, initials_py = _get_pinyin_forms(name)
        if (
            kw_lower in full_py  # 拼音输入匹配全拼（如 "luolan" in "ziluolan"）
            or kw_lower == initials_py  # 拼音输入匹配首字母（如 "zll" == "zll"）
            or kw_full_py
            in full_py  # 中文关键词全拼匹配（如 "洛兰"→"luolan" in "ziluolan"）
            or kw_initials_py
            in initials_py  # 中文关键词首字母匹配（如 "洛兰"→"ll" in "zll"）
        ):
            return _PRIORITY_PINYIN, f"{field}拼音"

    # --- 编辑距离容错 ---
    for name, field in [(card, "群昵称"), (nickname, "QQ昵称")]:
        if not name:
            continue
        threshold = max(1, len(name) // 3)
        dist = _levenshtein(kw_lower, name.lower())
        if dist <= threshold:
            return _PRIORITY_EDIT_DIST, f"{field}近似"

    return None


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """在群内按昵称查找群成员"""
    request_id = str(context.get("request_id", "-"))
    group_id = args.get("group_id") or context.get("group_id")
    keyword = str(args.get("nickname", "")).strip()
    exact = bool(args.get("exact", False))
    raw_count = args.get("count", 10)
    if raw_count in (None, ""):
        raw_count = 10

    try:
        count = int(raw_count)
    except (TypeError, ValueError):
        return "参数类型错误：count 必须是整数"

    if count <= 0:
        return "参数范围错误：count 必须大于 0"

    if not keyword:
        return "请提供要搜索的昵称关键词"

    if group_id is None:
        return "请提供群号（group_id 参数），或者在群聊中调用"

    try:
        group_id = int(group_id)
    except (ValueError, TypeError):
        return "参数类型错误：group_id 必须是整数"

    onebot_client = context.get("onebot_client")
    if not onebot_client:
        return "群成员查找功能不可用（OneBot 客户端未设置）"

    try:
        member_list: list[dict[str, Any]] = await onebot_client.get_group_member_list(
            group_id
        )

        if not member_list:
            return f"未能获取到群 {group_id} 的成员列表，可能群号不正确或机器人不在该群"

        # 匹配并收集结果: (priority, member, hit_field)
        hits: list[tuple[int, dict[str, Any], str]] = []
        for member in member_list:
            card = member.get("card", "")
            nickname = member.get("nickname", "")
            result = _match_member(keyword, card, nickname, exact)
            if result:
                priority, hit_field = result
                hits.append((priority, member, hit_field))

        # 按优先级排序
        hits.sort(key=lambda x: x[0])
        hits = hits[:count]

        if not hits:
            mode = "精确" if exact else "模糊"
            return f"在群 {group_id} 中未找到昵称{mode}匹配「{keyword}」的成员"

        role_map = {"owner": "群主", "admin": "管理员", "member": "成员"}
        mode = "精确" if exact else "模糊"
        parts = [
            f"【群成员查找】群 {group_id} | {mode}搜索「{keyword}」| 找到 {len(hits)} 人"
        ]

        for i, (_, member, hit_field) in enumerate(hits, 1):
            uid = member.get("user_id")
            card = member.get("card", "")
            nickname = member.get("nickname", "")
            role = member.get("role", "member")

            display = card if card else nickname
            extra = (
                f"(昵称: {nickname}) " if card and nickname and card != nickname else ""
            )
            role_zh = role_map.get(role, role)
            parts.append(
                f"{i}. {display} {extra}(QQ: {uid}) [{role_zh}] — 匹配: {hit_field}"
            )

        return "\n".join(parts)

    except Exception as e:
        logger.exception(
            "群成员查找失败: group=%s keyword=%s request_id=%s err=%s",
            group_id,
            keyword,
            request_id,
            e,
        )
        return "查找失败：群成员查找服务暂时不可用，请稍后重试"
