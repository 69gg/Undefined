from __future__ import annotations

import logging
from typing import Any

import httpx

from Undefined.bilibili.wbi import build_signed_params, parse_cookie_string
from Undefined.config import get_config
from Undefined.skills.http_config import build_httpx_client_kwargs

logger = logging.getLogger(__name__)

_USER_INFO_WBI_ENDPOINT = "https://api.bilibili.com/x/space/wbi/acc/info"
_USER_INFO_LEGACY_ENDPOINT = "https://api.bilibili.com/x/space/acc/info"
_USER_RELATION_STAT_ENDPOINT = "https://api.bilibili.com/x/relation/stat"
_USER_CARD_ENDPOINT = "https://api.bilibili.com/x/web-interface/card"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
}


def _to_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    return str(value or "").strip()


def _to_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default

    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "是", "开", "开启"}:
        return True
    if text in {"0", "false", "no", "off", "否", "关", "关闭"}:
        return False
    return default


def _api_message(payload: dict[str, Any]) -> str:
    return _text(payload.get("message") or payload.get("msg") or "未知错误")


def _first_optional_int(*values: Any) -> int | None:
    for value in values:
        parsed = _to_optional_int(value)
        if parsed is not None:
            return parsed
    return None


async def _get_json(
    client: httpx.AsyncClient,
    *,
    url: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    response = await client.get(url, params=params)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError(f"接口返回格式异常: {url}")
    return payload


async def _request_user_info(
    client: httpx.AsyncClient,
    *,
    mid: int,
) -> tuple[dict[str, Any], str]:
    base_params = {"mid": mid}
    failures: list[dict[str, Any]] = []

    signed_params: dict[str, str] | None = None
    try:
        signed_params = await build_signed_params(client, base_params)
        payload = await _get_json(
            client,
            url=_USER_INFO_WBI_ENDPOINT,
            params=signed_params,
        )
        if _to_int(payload.get("code"), default=-1) == 0:
            return payload, "wbi"
        failures.append(payload)
    except Exception as exc:
        logger.warning("[BilibiliUserInfo] WBI 首次请求失败: %s", exc)

    try:
        refreshed_params = await build_signed_params(
            client,
            base_params,
            force_refresh=True,
        )
        if refreshed_params != signed_params:
            payload = await _get_json(
                client,
                url=_USER_INFO_WBI_ENDPOINT,
                params=refreshed_params,
            )
            if _to_int(payload.get("code"), default=-1) == 0:
                return payload, "wbi_refreshed"
            failures.append(payload)
    except Exception as exc:
        logger.warning("[BilibiliUserInfo] WBI 刷新重试失败: %s", exc)

    try:
        payload = await _get_json(
            client,
            url=_USER_INFO_LEGACY_ENDPOINT,
            params=base_params,
        )
        if _to_int(payload.get("code"), default=-1) == 0:
            return payload, "legacy"
        failures.append(payload)
    except Exception as exc:
        logger.warning("[BilibiliUserInfo] 旧接口回退失败: %s", exc)

    if failures:
        return failures[-1], "failed"
    return {"code": -1, "message": "请求失败，未获得有效响应"}, "failed"


async def _request_relation_stat(
    client: httpx.AsyncClient,
    *,
    mid: int,
) -> dict[str, Any] | None:
    try:
        payload = await _get_json(
            client,
            url=_USER_RELATION_STAT_ENDPOINT,
            params={"vmid": mid},
        )
    except Exception as exc:
        logger.debug("[BilibiliUserInfo] relation/stat 请求失败: %s", exc)
        return None

    if _to_int(payload.get("code"), default=-1) != 0:
        logger.debug(
            "[BilibiliUserInfo] relation/stat 返回失败 code=%s msg=%s",
            payload.get("code"),
            _api_message(payload),
        )
        return None

    data = payload.get("data")
    if isinstance(data, dict):
        return data
    return None


async def _request_user_card(
    client: httpx.AsyncClient,
    *,
    mid: int,
) -> dict[str, Any] | None:
    try:
        payload = await _get_json(
            client,
            url=_USER_CARD_ENDPOINT,
            params={"mid": mid, "photo": "true"},
        )
    except Exception as exc:
        logger.debug("[BilibiliUserInfo] card 请求失败: %s", exc)
        return None

    if _to_int(payload.get("code"), default=-1) != 0:
        logger.debug(
            "[BilibiliUserInfo] card 返回失败 code=%s msg=%s",
            payload.get("code"),
            _api_message(payload),
        )
        return None

    data = payload.get("data")
    if isinstance(data, dict):
        return data
    return None


def _format_api_error(payload: dict[str, Any], *, cookie_ready: bool) -> str:
    code = payload.get("code")
    message = _api_message(payload)
    lines = [f"B站用户查询失败: {message} (code={code})"]

    code_num = _to_int(code, default=0)
    if code_num in (-352, -412):
        lines.append("- 请求被风控拦截")
        if cookie_ready:
            lines.append("- 已检测到 Cookie，建议刷新最新完整 Cookie 后重试")
        else:
            lines.append("- 当前未配置 bilibili.cookie，建议填写完整浏览器 Cookie")
        lines.append("- 建议 Cookie 至少包含 SESSDATA + buvid3 + buvid4")
    elif code_num == -101:
        lines.append("- 账号未登录或 Cookie 已失效")

    return "\n".join(lines)


def _format_user_info(
    user_info_payload: dict[str, Any],
    *,
    relation_stat: dict[str, Any] | None,
    user_card: dict[str, Any] | None,
    detail_mode: str,
    include_live: bool,
    include_face: bool,
    include_space_link: bool,
) -> str:
    data_raw = user_info_payload.get("data")
    if not isinstance(data_raw, dict):
        return "B站用户信息返回为空。"

    data = data_raw
    card_obj = user_card.get("card") if isinstance(user_card, dict) else None
    if not isinstance(card_obj, dict):
        card_obj = {}

    mid = _text(data.get("mid") or card_obj.get("mid"))
    name = _text(data.get("name") or card_obj.get("name"))
    level = _first_optional_int(data.get("level"), card_obj.get("level"))
    sex = _text(data.get("sex") or card_obj.get("sex"))
    sign = _text(data.get("sign") or card_obj.get("sign") or data.get("desc"))
    face = _text(data.get("face") or card_obj.get("face"))

    official_desc = ""
    official = data.get("official")
    if isinstance(official, dict):
        official_desc = _text(official.get("title") or official.get("desc"))
    if not official_desc:
        official_verify = card_obj.get("official_verify")
        if isinstance(official_verify, dict):
            official_desc = _text(official_verify.get("desc"))

    follower = _first_optional_int(
        relation_stat.get("follower") if isinstance(relation_stat, dict) else None,
        user_card.get("follower") if isinstance(user_card, dict) else None,
        data.get("fans"),
        data.get("follower"),
        card_obj.get("fans"),
    )
    following = _first_optional_int(
        relation_stat.get("following") if isinstance(relation_stat, dict) else None,
        data.get("following"),
        data.get("friend"),
        card_obj.get("attention"),
        card_obj.get("friend"),
    )

    like_num = _first_optional_int(user_card.get("like_num") if user_card else None)
    archive_count = _first_optional_int(
        user_card.get("archive_count") if user_card else None
    )
    article_count = _first_optional_int(
        user_card.get("article_count") if user_card else None
    )

    vip_obj = data.get("vip")
    vip_label = ""
    if isinstance(vip_obj, dict):
        label_obj = vip_obj.get("label")
        if isinstance(label_obj, dict):
            vip_label = _text(label_obj.get("text"))
        if not vip_label:
            vip_type = _to_optional_int(vip_obj.get("type") or vip_obj.get("vipType"))
            if vip_type is not None:
                vip_label_map = {0: "非大会员", 1: "月大会员", 2: "年度及以上大会员"}
                vip_label = vip_label_map.get(vip_type, f"会员类型 {vip_type}")

    birthday = _text(data.get("birthday"))
    silence = _to_optional_int(data.get("silence"))
    top_photo = _text(data.get("top_photo"))

    live_room = data.get("live_room")
    room_id = ""
    room_title = ""
    live_status = None
    if isinstance(live_room, dict):
        room_id = _text(live_room.get("roomid") or live_room.get("room_id"))
        room_title = _text(live_room.get("title"))
        live_status = _to_optional_int(live_room.get("liveStatus"))
    if not room_id:
        room_id = _text(data.get("roomid"))

    lines: list[str] = []
    header = "📺 B站用户"
    if name:
        header += f": {name}"
    if mid:
        header += f" (UID: {mid})"
    lines.append(header)

    if level is not None and level >= 0:
        lines.append(f"🆙 等级: Lv{level}")
    if sex:
        lines.append(f"⚧ 性别: {sex}")
    if sign:
        lines.append(f"📝 简介: {sign}")
    if official_desc:
        lines.append(f"✅ 认证: {official_desc}")

    if follower is not None or following is not None:
        follower_text = str(follower) if follower is not None else "-"
        following_text = str(following) if following is not None else "-"
        lines.append(f"👥 粉丝: {follower_text} | 关注: {following_text}")

    if like_num is not None:
        lines.append(f"👍 获赞: {like_num}")
    if archive_count is not None:
        lines.append(f"🎬 稿件: {archive_count}")
    if detail_mode == "full" and article_count is not None:
        lines.append(f"📰 专栏: {article_count}")

    if detail_mode == "full" and vip_label:
        lines.append(f"💎 会员: {vip_label}")
    if detail_mode == "full" and birthday:
        lines.append(f"🎂 生日: {birthday}")
    if detail_mode == "full" and silence is not None:
        silence_text = "封禁" if silence == 1 else "正常"
        lines.append(f"🛡️ 状态: {silence_text}")
    if detail_mode == "full" and top_photo:
        lines.append(f"🖼️ 头图: {top_photo}")

    if include_live and room_id:
        status_text = ""
        if live_status is not None:
            status_text = "（直播中）" if live_status == 1 else "（未开播）"
        room_line = f"🎥 直播间: {room_id}{status_text}"
        if room_title:
            room_line += f" - {room_title}"
        lines.append(room_line)

    if include_face and face:
        lines.append(f"🖼️ 头像: {face}")
    if include_space_link and mid:
        lines.append(f"🔗 空间: https://space.bilibili.com/{mid}")

    return "\n".join(lines)


async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    del context

    mid = _to_int(args.get("mid"), default=0)
    if mid <= 0:
        return "请提供有效的用户 UID（mid）。"

    config = get_config(strict=False)
    cookie_raw = _text(config.bilibili_cookie)
    cookies = parse_cookie_string(cookie_raw)
    cookie_ready = bool(cookies)

    detail_mode = _text(args.get("detail_mode") or "brief").lower()
    if detail_mode not in {"brief", "full"}:
        return "detail_mode 仅支持 brief 或 full。"

    include_relation = _to_bool(args.get("include_relation"), default=True)
    include_card = _to_bool(args.get("include_card"), default=True)
    include_live = _to_bool(args.get("include_live"), default=True)
    include_face = _to_bool(args.get("include_face"), default=True)
    include_space_link = _to_bool(args.get("include_space_link"), default=True)

    timeout_raw = float(config.network_request_timeout)
    timeout = timeout_raw if timeout_raw > 0 else 30.0

    try:
        client_kwargs = build_httpx_client_kwargs(
            _USER_INFO_WBI_ENDPOINT,
            proxy_scope="bilibili",
            headers=_HEADERS,
            cookies=cookies,
            timeout=timeout,
            follow_redirects=True,
        )
        async with httpx.AsyncClient(**client_kwargs) as client:
            user_info_payload, source = await _request_user_info(client, mid=mid)

            if _to_int(user_info_payload.get("code"), default=-1) != 0:
                return _format_api_error(user_info_payload, cookie_ready=cookie_ready)

            relation_stat = (
                await _request_relation_stat(client, mid=mid)
                if include_relation
                else None
            )
            user_card = (
                await _request_user_card(client, mid=mid) if include_card else None
            )

        result = _format_user_info(
            user_info_payload,
            relation_stat=relation_stat,
            user_card=user_card,
            detail_mode=detail_mode,
            include_live=include_live,
            include_face=include_face,
            include_space_link=include_space_link,
        )
        if source == "legacy":
            return (
                result
                + "\n⚠️ 当前使用旧接口回退结果，建议检查 Cookie 以启用 WBI 主接口。"
            )
        return result
    except Exception as exc:
        logger.exception("B站用户查询失败: %s", exc)
        return "B站用户查询失败，请稍后重试"
