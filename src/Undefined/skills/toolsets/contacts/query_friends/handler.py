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


def _match_friend(
    keyword: str,
    remark: str,
    nickname: str,
    exact: bool,
) -> tuple[int, str] | None:
    """尝试匹配一个好友，返回 (优先级, 命中字段) 或 None

    优先级越小越好。exact=True 时仅做精确匹配。
    """
    kw_lower = keyword.lower()

    # --- 精确匹配 ---
    if remark and remark.lower() == kw_lower:
        return _PRIORITY_EXACT, "备注"
    if nickname and nickname.lower() == kw_lower:
        return _PRIORITY_EXACT, "昵称"

    if exact:
        return None

    # --- 子串匹配 ---
    if remark and kw_lower in remark.lower():
        return _PRIORITY_SUBSTR, "备注"
    if nickname and kw_lower in nickname.lower():
        return _PRIORITY_SUBSTR, "昵称"

    # --- 拼音匹配 ---
    kw_full_py, kw_initials_py = _get_pinyin_forms(keyword)
    for name, field in [(remark, "备注"), (nickname, "昵称")]:
        if not name:
            continue
        full_py, initials_py = _get_pinyin_forms(name)
        if (
            kw_lower in full_py  # 拼音输入匹配全拼
            or kw_lower == initials_py  # 拼音输入匹配首字母
            or kw_full_py in full_py  # 中文关键词全拼匹配
            or kw_initials_py in initials_py  # 中文关键词首字母匹配
        ):
            return _PRIORITY_PINYIN, f"{field}拼音"

    # --- 编辑距离容错 ---
    for name, field in [(remark, "备注"), (nickname, "昵称")]:
        if not name:
            continue
        threshold = max(1, len(name) // 3)
        dist = _levenshtein(kw_lower, name.lower())
        if dist <= threshold:
            return _PRIORITY_EDIT_DIST, f"{field}近似"

    return None


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """查询好友列表"""
    request_id = str(context.get("request_id", "-"))
    keyword = str(args.get("keyword", "")).strip()
    exact = bool(args.get("exact", False))
    raw_count = args.get("count", 20)

    if raw_count in (None, ""):
        raw_count = 20

    try:
        count = int(raw_count)
    except (TypeError, ValueError):
        return "参数类型错误：count 必须是整数"

    if count <= 0:
        return "参数范围错误：count 必须大于 0"

    onebot_client = context.get("onebot_client")
    if not onebot_client:
        return "好友查询功能不可用（OneBot 客户端未设置）"

    try:
        friend_list: list[dict[str, Any]] = await onebot_client.get_friend_list()

        if not friend_list:
            return "未能获取好友列表，可能是权限不足或网络问题"

        # 无关键词：返回全部（受count限制）
        if not keyword:
            total = len(friend_list)
            friend_list = friend_list[:count]

            parts = [f"【好友列表】共 {total} 位好友"]
            for i, friend in enumerate(friend_list, 1):
                user_id = friend.get("user_id")
                nickname = friend.get("nickname", "")
                remark = friend.get("remark", "")

                display = remark if remark else nickname
                extra = (
                    f"(昵称: {nickname}) "
                    if remark and nickname and remark != nickname
                    else ""
                )
                parts.append(f"{i}. {display} {extra}(QQ: {user_id})")

            if total > count:
                parts.append(f"... 等共 {total} 位好友")

            return "\n".join(parts)

        # 有关键词：匹配并收集结果
        hits: list[tuple[int, dict[str, Any], str]] = []
        for friend in friend_list:
            remark = friend.get("remark", "")
            nickname = friend.get("nickname", "")
            result = _match_friend(keyword, remark, nickname, exact)
            if result:
                priority, hit_field = result
                hits.append((priority, friend, hit_field))

        # 按优先级排序
        hits.sort(key=lambda x: x[0])
        hits = hits[:count]

        if not hits:
            mode = "精确" if exact else "模糊"
            return f"未找到{mode}匹配「{keyword}」的好友"

        mode = "精确" if exact else "模糊"
        parts = [f"【好友查找】{mode}搜索「{keyword}」| 找到 {len(hits)} 人"]

        for i, (_, friend, hit_field) in enumerate(hits, 1):
            user_id = friend.get("user_id")
            nickname = friend.get("nickname", "")
            remark = friend.get("remark", "")

            display = remark if remark else nickname
            extra = (
                f"(昵称: {nickname}) "
                if remark and nickname and remark != nickname
                else ""
            )
            parts.append(f"{i}. {display} {extra}(QQ: {user_id}) — 匹配: {hit_field}")

        return "\n".join(parts)

    except Exception as e:
        logger.exception(
            "好友查询失败: keyword=%s request_id=%s err=%s",
            keyword,
            request_id,
            e,
        )
        return "查询失败：好友查询服务暂时不可用，请稍后重试"
