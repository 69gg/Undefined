from typing import Any, Dict
import logging
import httpx

from Undefined.config import get_config

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    """对特定网址或域名执行网络质量巡检，探测 HTTP 状态及延迟情况"""
    request_id = str(context.get("request_id", "-"))
    host = args.get("host")

    if not host:
        return "❌ 主机地址不能为空"

    try:
        config = get_config(strict=False)
        timeout = float(config.network_request_timeout)
        if timeout <= 0:
            timeout = 30.0
        api_token = config.xxapi_api_token
        base_url = str(config.api_xxapi_base_url).strip().rstrip("/")
        if not base_url:
            base_url = "https://v2.xxapi.cn"

        async with httpx.AsyncClient(timeout=timeout) as client:
            if not api_token:
                return "❌ XXAPI 未配置 API Token"
            params = {"host": host, "key": api_token}
            logger.info(f"网络检测: {host}")

            response = await client.get(f"{base_url}/api/netCheck", params=params)
            response.raise_for_status()
            data = response.json()

            if data.get("code") != 200:
                return f"网络检测失败: {data.get('msg')}"

            check_data = data.get("data", {})
            result = f"【{host} 网络检测报告】\n\n"

            # DNS 解析结果
            dns = check_data.get("dns", {})
            if dns:
                result += "【DNS 解析】\n"
                a_records = dns.get("A", [])
                if a_records:
                    result += f"A记录：{', '.join(a_records)}\n"
                aaaa_records = dns.get("AAAA", [])
                if aaaa_records:
                    result += f"AAAA记录：{', '.join(aaaa_records)}\n"
                cname = dns.get("CNAME")
                if cname:
                    result += f"CNAME：{cname}\n"
                dns_time = dns.get("time", "")
                if dns_time:
                    result += f"查询耗时：{dns_time}\n"
                result += "\n"

            # ICMP Ping 检测
            ping = check_data.get("ping", {})
            if ping:
                result += "【ICMP Ping】\n"
                reachable = ping.get("reachable", False)
                result += f"可达性：{'是' if reachable else '否'}\n"
                if reachable:
                    rtt = ping.get("rtt", "")
                    if rtt:
                        result += f"延迟：{rtt}\n"
                    ip = ping.get("ip", "")
                    if ip:
                        result += f"IP地址：{ip}\n"
                result += "\n"

            # HTTP 检测
            http = check_data.get("http", {})
            if http:
                result += "【HTTP 检测】\n"
                status = http.get("status", "")
                result += f"状态码：{status}\n"
                ok = http.get("ok", False)
                result += f"请求成功：{'是' if ok else '否'}\n"
                latency = http.get("latency", "")
                if latency:
                    result += f"响应时间：{latency}\n"
                redirects = http.get("redirects", 0)
                result += f"跳转次数：{redirects}\n"
                final_url = http.get("final_url", "")
                if final_url:
                    result += f"最终URL：{final_url}\n"
                result += "\n"

            # HTTPS 检测
            https = check_data.get("https", {})
            if https:
                result += "【HTTPS 检测】\n"
                status = https.get("status", "")
                result += f"状态码：{status}\n"
                ok = https.get("ok", False)
                result += f"请求成功：{'是' if ok else '否'}\n"
                latency = https.get("latency", "")
                if latency:
                    result += f"响应时间：{latency}\n"
                tls_version = https.get("tls_version", "")
                if tls_version:
                    result += f"TLS版本：{tls_version}\n"
                days_left = https.get("days_left", 0)
                result += f"证书剩余天数：{days_left}天\n"
                issuer = https.get("issuer", "")
                if issuer:
                    result += f"证书颁发者：{issuer}\n"
                not_after = https.get("not_after", "")
                if not_after:
                    result += f"证书到期时间：{not_after}\n"

            return result

    except httpx.TimeoutException:
        return "请求超时，请稍后重试"
    except httpx.HTTPStatusError as e:
        logger.error("HTTP 错误: request_id=%s err=%s", request_id, e)
        return "网络检测失败：上游接口返回异常状态"
    except Exception as e:
        logger.exception("网络检测失败: request_id=%s err=%s", request_id, e)
        return "网络检测失败：服务暂时不可用，请稍后重试"
