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


def _match_group(
    keyword: str,
    group_name: str,
    exact: bool,
) -> tuple[int, str] | None:
    """尝试匹配一个群聊，返回 (优先级, 命中字段) 或 None

    优先级越小越好。exact=True 时仅做精确匹配。
    """
    if not group_name:
        return None

    kw_lower = keyword.lower()

    # --- 精确匹配 ---
    if group_name.lower() == kw_lower:
        return _PRIORITY_EXACT, "群名称"

    if exact:
        return None

    # --- 子串匹配 ---
    if kw_lower in group_name.lower():
        return _PRIORITY_SUBSTR, "群名称"

    # --- 拼音匹配 ---
    kw_full_py, kw_initials_py = _get_pinyin_forms(keyword)
    full_py, initials_py = _get_pinyin_forms(group_name)
    if (
        kw_lower in full_py  # 拼音输入匹配全拼
        or kw_lower == initials_py  # 拼音输入匹配首字母
        or kw_full_py in full_py  # 中文关键词全拼匹配
        or kw_initials_py in initials_py  # 中文关键词首字母匹配
    ):
        return _PRIORITY_PINYIN, "群名称拼音"

    # --- 编辑距离容错 ---
    threshold = max(1, len(group_name) // 3)
    dist = _levenshtein(kw_lower, group_name.lower())
    if dist <= threshold:
        return _PRIORITY_EDIT_DIST, "群名称近似"

    return None


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """查询群聊列表"""
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
        return "群聊查询功能不可用（OneBot 客户端未设置）"

    try:
        group_list: list[dict[str, Any]] = await onebot_client.get_group_list()

        if not group_list:
            return "未能获取群聊列表，可能是权限不足或网络问题"

        # 无关键词：返回全部（受count限制）
        if not keyword:
            total = len(group_list)
            group_list = group_list[:count]

            parts = [f"【群聊列表】共 {total} 个群"]
            for i, group in enumerate(group_list, 1):
                group_id = group.get("group_id")
                group_name = group.get("group_name", "")
                member_count = group.get("member_count", 0)
                parts.append(f"{i}. {group_name} ({group_id}) [{member_count}人]")

            if total > count:
                parts.append(f"... 等共 {total} 个群")

            return "\n".join(parts)

        # 有关键词：匹配并收集结果
        hits: list[tuple[int, dict[str, Any], str]] = []
        for group in group_list:
            group_name = group.get("group_name", "")
            result = _match_group(keyword, group_name, exact)
            if result:
                priority, hit_field = result
                hits.append((priority, group, hit_field))

        # 按优先级排序
        hits.sort(key=lambda x: x[0])
        hits = hits[:count]

        if not hits:
            mode = "精确" if exact else "模糊"
            return f"未找到{mode}匹配「{keyword}」的群聊"

        mode = "精确" if exact else "模糊"
        parts = [f"【群聊查找】{mode}搜索「{keyword}」| 找到 {len(hits)} 个群"]

        for i, (_, group, hit_field) in enumerate(hits, 1):
            group_id = group.get("group_id")
            group_name = group.get("group_name", "")
            member_count = group.get("member_count", 0)
            parts.append(
                f"{i}. {group_name} ({group_id}) [{member_count}人] — 匹配: {hit_field}"
            )

        return "\n".join(parts)

    except Exception as e:
        logger.exception(
            "群聊查询失败: keyword=%s request_id=%s err=%s",
            keyword,
            request_id,
            e,
        )
        return "查询失败：群聊查询服务暂时不可用，请稍后重试"
