from typing import Any, Dict
import logging
import httpx

logger = logging.getLogger(__name__)


async def execute(args: Dict[str, Any], context: Dict[str, Any]) -> str:
    domain = args.get("domain")

    if not domain:
        return "❌ 域名不能为空"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            params = {"domain": domain}
            logger.info(f"查询Whois信息: {domain}")

            response = await client.get("https://v2.xxapi.cn/api/whois", params=params)
            response.raise_for_status()
            data = response.json()

            if data.get("code") != 200:
                return f"查询Whois失败: {data.get('msg')}"

            whois_data = data.get("data", {})
            result = f"【{domain} Whois信息】\n\n"

            domain_name = whois_data.get("Domain Name", "")
            registrar = whois_data.get("Sponsoring Registrar", "")
            registrar_url = whois_data.get("Registrar URL", "")
            registrant = whois_data.get("Registrant", "")
            registrant_email = whois_data.get("Registrant Contact Email", "")
            registration_time = whois_data.get("Registration Time", "")
            expiration_time = whois_data.get("Expiration Time", "")
            dns_servers = whois_data.get("DNS Serve", [])

            if domain_name:
                result += f"域名: {domain_name}\n"
            if registrar:
                result += f"注册商: {registrar}\n"
            if registrar_url:
                result += f"注册商URL: {registrar_url}\n"
            if registrant:
                result += f"注册人: {registrant}\n"
            if registrant_email:
                result += f"注册人邮箱: {registrant_email}\n"
            if registration_time:
                result += f"注册时间: {registration_time}\n"
            if expiration_time:
                result += f"到期时间: {expiration_time}\n"
            if dns_servers:
                result += f"DNS服务器: {', '.join(dns_servers)}\n"

            return result

    except httpx.TimeoutException:
        return "请求超时，请稍后重试"
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP 错误: {e}")
        return f"查询Whois失败: {e}"
    except Exception as e:
        logger.exception(f"查询Whois失败: {e}")
        return f"查询Whois失败: {e}"
