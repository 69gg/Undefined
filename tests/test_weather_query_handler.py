from __future__ import annotations

from typing import Any

import httpx

from Undefined.skills.agents.info_agent.tools.weather_query import (
    handler as weather_handler,
)


def _sample_wttr_payload() -> dict[str, Any]:
    return {
        "current_condition": [
            {
                "FeelsLikeC": "31",
                "humidity": "84",
                "localObsDateTime": "2026-02-24 08:00 PM",
                "temp_C": "29",
                "uvIndex": "7",
                "visibility": "9",
                "weatherCode": "176",
                "weatherDesc": [{"value": "Patchy rain nearby"}],
                "winddir16Point": "NE",
                "winddirDegree": "45",
                "windspeedKmph": "12",
            }
        ],
        "nearest_area": [
            {
                "areaName": [{"value": "Beijing"}],
                "country": [{"value": "China"}],
                "region": [{"value": "Beijing"}],
            }
        ],
        "weather": [
            {
                "date": "2026-02-24",
                "maxtempC": "31",
                "mintempC": "24",
                "hourly": [
                    {
                        "chanceofrain": "70",
                        "weatherCode": "176",
                        "weatherDesc": [{"value": "Patchy rain nearby"}],
                        "windspeedKmph": "18",
                    },
                    {
                        "chanceofrain": "30",
                        "weatherCode": "116",
                        "weatherDesc": [{"value": "Partly cloudy"}],
                        "windspeedKmph": "14",
                    },
                ],
            },
            {
                "date": "2026-02-25",
                "maxtempC": "30",
                "mintempC": "22",
                "hourly": [
                    {
                        "chanceofrain": "10",
                        "weatherCode": "113",
                        "weatherDesc": [{"value": "Sunny"}],
                        "windspeedKmph": "10",
                    }
                ],
            },
        ],
    }


async def _fake_get_json_with_retry(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return _sample_wttr_payload()


async def test_weather_now_uses_wttr_payload(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        weather_handler, "get_json_with_retry", _fake_get_json_with_retry
    )
    result = await weather_handler.execute(
        {"location": "Beijing", "query_type": "now"}, {}
    )
    assert "【Beijing 天气实况】" in result
    assert "天气: 小雨" in result
    assert "温度: 29°C" in result
    assert "风向: NE (45°)" in result


async def test_weather_forecast_uses_wttr_payload(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        weather_handler, "get_json_with_retry", _fake_get_json_with_retry
    )
    result = await weather_handler.execute(
        {"location": "Beijing", "query_type": "forecast"},
        {},
    )
    assert "【Beijing 未来天气预报】" in result
    assert "2026-02-24: 多云 24~31°C 降水概率70% 风速18km/h" in result
    assert "2026-02-25: 晴 22~30°C 降水概率10% 风速10km/h" in result


async def test_weather_unknown_query_type_falls_back_to_now(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        weather_handler, "get_json_with_retry", _fake_get_json_with_retry
    )
    result = await weather_handler.execute(
        {"location": "Beijing", "query_type": "life"},
        {},
    )
    assert "【Beijing 天气实况】" in result
    assert "天气: 小雨" in result


async def test_weather_requires_location() -> None:
    result = await weather_handler.execute({"query_type": "now"}, {})
    assert result == "请提供城市名称。"


async def test_weather_timeout_error_is_returned_to_ai(monkeypatch: Any) -> None:
    async def _raise_timeout(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr(weather_handler, "get_json_with_retry", _raise_timeout)
    result = await weather_handler.execute(
        {"location": "上海", "query_type": "now"}, {}
    )
    assert "ReadTimeout: timed out" in result


async def test_weather_http_error_is_returned_to_ai(monkeypatch: Any) -> None:
    async def _raise_http(*args: Any, **kwargs: Any) -> dict[str, Any]:
        request = httpx.Request("GET", "https://wttr.in/上海")
        response = httpx.Response(503, request=request, text="upstream unavailable")
        raise httpx.HTTPStatusError(
            "Server error '503 Service Unavailable'",
            request=request,
            response=response,
        )

    monkeypatch.setattr(weather_handler, "get_json_with_retry", _raise_http)
    result = await weather_handler.execute(
        {"location": "上海", "query_type": "forecast"},
        {},
    )
    assert "HTTPStatusError: 503 upstream unavailable" in result
