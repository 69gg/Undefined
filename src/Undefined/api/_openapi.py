"""OpenAPI / Swagger specification builder."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aiohttp import web

from Undefined import __version__
from ._helpers import _AUTH_HEADER, _naga_routes_enabled

if TYPE_CHECKING:
    from .app import RuntimeAPIContext


def _build_openapi_spec(ctx: RuntimeAPIContext, request: web.Request) -> dict[str, Any]:
    server_url = f"{request.scheme}://{request.host}"
    cfg = ctx.config_getter()
    naga_routes_enabled = _naga_routes_enabled(cfg, ctx.naga_store)
    paths: dict[str, Any] = {
        "/health": {
            "get": {
                "summary": "Health check",
                "security": [],
                "responses": {"200": {"description": "OK"}},
            }
        },
        "/openapi.json": {
            "get": {
                "summary": "OpenAPI schema",
                "security": [],
                "responses": {"200": {"description": "Schema JSON"}},
            }
        },
        "/api/v1/probes/internal": {
            "get": {
                "summary": "Internal runtime probes",
                "description": (
                    "Returns system info (version, Python, platform, uptime), "
                    "OneBot connection status, request queue snapshot, "
                    "memory count, cognitive service status, API config, "
                    "skill statistics (tools/agents/anthropic_skills with call counts), "
                    "and model configuration (names, masked URLs, thinking flags)."
                ),
            }
        },
        "/api/v1/probes/external": {
            "get": {
                "summary": "External dependency probes",
                "description": (
                    "Concurrently probes all configured model API endpoints "
                    "(chat, vision, security, naga, agent, embedding, rerank) "
                    "and OneBot WebSocket. Each result includes status, "
                    "model name, masked URL, HTTP status code, and latency."
                ),
            }
        },
        "/api/v1/memory": {
            "get": {"summary": "List/search manual memories"},
            "post": {"summary": "Create a manual memory"},
        },
        "/api/v1/memory/{uuid}": {
            "patch": {"summary": "Update a manual memory by UUID"},
            "delete": {"summary": "Delete a manual memory by UUID"},
        },
        "/api/v1/memes": {"get": {"summary": "List/search meme library items"}},
        "/api/v1/memes/stats": {"get": {"summary": "Get meme library stats"}},
        "/api/v1/memes/{uid}": {
            "get": {"summary": "Get a meme by uid"},
            "patch": {"summary": "Update a meme by uid"},
            "delete": {"summary": "Delete a meme by uid"},
        },
        "/api/v1/memes/{uid}/blob": {"get": {"summary": "Get meme blob file"}},
        "/api/v1/memes/{uid}/preview": {"get": {"summary": "Get meme preview file"}},
        "/api/v1/memes/{uid}/reanalyze": {
            "post": {"summary": "Queue a meme reanalyze job"}
        },
        "/api/v1/memes/{uid}/reindex": {
            "post": {"summary": "Queue a meme reindex job"}
        },
        "/api/v1/cognitive/events": {
            "get": {"summary": "Search cognitive event memories"}
        },
        "/api/v1/cognitive/profiles": {"get": {"summary": "Search cognitive profiles"}},
        "/api/v1/cognitive/profile/{entity_type}/{entity_id}": {
            "get": {"summary": "Get a profile by entity type/id"}
        },
        "/api/v1/chat": {
            "post": {
                "summary": "WebUI special private chat",
                "description": (
                    "POST JSON {message, stream?}. "
                    "When stream=true, response is SSE with keep-alive comments."
                ),
            }
        },
        "/api/v1/chat/history": {
            "get": {"summary": "Get virtual private chat history for WebUI"}
        },
        "/api/v1/tools": {
            "get": {
                "summary": "List available tools",
                "description": (
                    "Returns currently available tools filtered by "
                    "tool_invoke_expose / allowlist / denylist config. "
                    "Each item follows the OpenAI function calling schema."
                ),
            }
        },
        "/api/v1/tools/invoke": {
            "post": {
                "summary": "Invoke a tool",
                "description": (
                    "Execute a specific tool by name. Supports synchronous "
                    "response and optional async webhook callback."
                ),
            }
        },
    }

    if naga_routes_enabled:
        paths.update(
            {
                "/api/v1/naga/bind/callback": {
                    "post": {
                        "summary": "Finalize a Naga bind request",
                        "description": (
                            "Internal callback used by Naga to approve or reject "
                            "a bind_uuid."
                        ),
                        "security": [{"BearerAuth": []}],
                    }
                },
                "/api/v1/naga/messages/send": {
                    "post": {
                        "summary": "Send a Naga-authenticated message",
                        "description": (
                            "Validates bind_uuid + delivery_signature, runs "
                            "moderation, then delivers the message. "
                            "Caller may provide uuid for idempotent retry deduplication."
                        ),
                        "security": [{"BearerAuth": []}],
                    }
                },
                "/api/v1/naga/unbind": {
                    "post": {
                        "summary": "Revoke an active Naga binding",
                        "description": (
                            "Allows Naga to proactively revoke a binding using "
                            "Authorization: Bearer <naga.api_key>."
                        ),
                        "security": [{"BearerAuth": []}],
                    }
                },
            }
        )

    return {
        "openapi": "3.0.3",
        "info": {
            "title": "Undefined Runtime API",
            "version": __version__,
            "description": "API exposed by the main Undefined process.",
        },
        "servers": [
            {
                "url": server_url,
                "description": "Runtime endpoint",
            }
        ],
        "components": {
            "securitySchemes": {
                "ApiKeyAuth": {
                    "type": "apiKey",
                    "in": "header",
                    "name": _AUTH_HEADER,
                },
                "BearerAuth": {"type": "http", "scheme": "bearer"},
            }
        },
        "security": [{"ApiKeyAuth": []}],
        "paths": paths,
    }
