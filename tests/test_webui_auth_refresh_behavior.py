"""Concurrent WebUI refreshes share one rotation and respect session replacement."""

from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest

from test_webui_runtime_chat_behavior import REPO_ROOT, _require_env


def _run_refresh_scenario(scenario: str) -> dict[str, Any]:
    _require_env()
    script = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const state = {authAccessToken: 'oldA', authRefreshToken: 'oldR',
  authAccessTokenExpiresAt: Date.now() + 10, authenticated: true};
const stored = {access: 'oldA', refresh: 'oldR', expiresAt: ''};
const pending = [];
let resources = 0;
const context = vm.createContext({state, Response, AbortController, Map,
  FormData, Blob, URLSearchParams, console, setTimeout, clearTimeout,
  window: {setTimeout: () => 1}, refreshUI: () => {},
  readAuthStorage: key => {
    if (key === 'undefined_auth_access_token') return stored.access;
    if (key === 'undefined_auth_refresh_token') return stored.refresh;
    if (key === 'undefined_auth_access_expires_at') return stored.expiresAt;
    return '';
  },
  storeAuthTokens: tokens => {
    Object.assign(state, {authAccessToken: tokens.accessToken,
      authRefreshToken: tokens.refreshToken, authAccessTokenExpiresAt: tokens.accessTokenExpiresAt});
    stored.access = tokens.accessToken || '';
    stored.refresh = tokens.refreshToken || '';
    stored.expiresAt = String(tokens.accessTokenExpiresAt || '');
  },
  clearStoredAuthTokens: () => {
    Object.assign(state, {authAccessToken: '',
      authRefreshToken: '', authAccessTokenExpiresAt: 0});
    stored.access = ''; stored.refresh = ''; stored.expiresAt = '';
  },
  fetch: async (path, options) => {
    if (path === '/refresh') return new Promise(resolve => pending.push({resolve,
      body: JSON.parse(options.body)}));
    resources++;
    return new Response('{}', {status: input.scenario === 'cookie' || state.authAccessToken ? 200 : 401});
  },
});
vm.runInContext(fs.readFileSync(input.source, 'utf8'), context);
vm.runInContext('AUTH_ENDPOINTS.refresh = ["/refresh"]', context);
const pair = {access_token: 'newA', refresh_token: 'newR', expires_in: 900};
const tick = async () => { for(let i=0; i<10; i++) await new Promise(r => setImmediate(r)); };
(async () => {
  if (input.scenario === 'stale_tab') {
    stored.refresh = 'otherR';
    stored.access = 'otherA';
    stored.expiresAt = String(Date.now() + 900000);
    const request = vm.runInContext('refreshAccessToken()', context);
    await tick();
    pending[0].resolve(new Response('{}', {status: 401}));
    await request.catch(() => {});
    console.log(JSON.stringify({state, stored, refreshes: pending.length}));
    return;
  }
  if (input.scenario.startsWith('replacement')) {
    const request = vm.runInContext('refreshAccessToken()', context);
    await tick();
    Object.assign(state, {authAccessToken: 'loginA', authRefreshToken: 'loginR'});
    pending[0].resolve(new Response(JSON.stringify(pair), {
      status: input.scenario === 'replacement_error' ? 401 : 200}));
    await request;
  } else {
    const calls = vm.runInContext('Promise.allSettled([api("/status"), api("/system")])', context);
    await tick();
    const refreshCountWhilePending = pending.length;
    pending[0].resolve(new Response(JSON.stringify(pair), {status: input.scenario === 'failure' ? 401 : 200}));
    const results = await calls;
    console.log(JSON.stringify({state, refreshCountWhilePending, refreshes: pending.length,
      inputs: pending.map(item => item.body), resources, results: results.map(item => item.status)}));
    return;
  }
  console.log(JSON.stringify({state, refreshes: pending.length}));
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    completed = subprocess.run(
        ["node", "-e", script],
        input=json.dumps(
            {
                "source": str(REPO_ROOT / "src/Undefined/webui/static/js/api.js"),
                "scenario": scenario,
            }
        ),
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    result: dict[str, Any] = json.loads(completed.stdout.strip().splitlines()[-1])
    return result


@pytest.mark.parametrize("scenario", ["token", "cookie"])
def test_parallel_api_requests_share_one_auth_refresh(scenario: str) -> None:
    result = _run_refresh_scenario(scenario)
    assert result["refreshCountWhilePending"] == result["refreshes"] == 1
    assert result["inputs"] == [{"refresh_token": "oldR"}]
    assert result["state"]["authAccessToken"] == "newA"
    assert result["state"]["authRefreshToken"] == "newR"
    assert result["resources"] == 2
    assert result["results"] == ["fulfilled", "fulfilled"]


@pytest.mark.parametrize("scenario", ["replacement_success", "replacement_error"])
def test_late_refresh_response_preserves_new_login(scenario: str) -> None:
    result = _run_refresh_scenario(scenario)
    assert result["state"]["authAccessToken"] == "loginA"
    assert result["state"]["authRefreshToken"] == "loginR"


def test_failed_shared_refresh_clears_its_own_expired_tokens() -> None:
    result = _run_refresh_scenario("failure")
    assert result["refreshes"] == 1
    assert result["state"]["authRefreshToken"] == ""
    assert result["results"] == ["rejected", "rejected"]


def test_failed_refresh_keeps_token_rotated_by_another_tab() -> None:
    result = _run_refresh_scenario("stale_tab")
    assert result["refreshes"] == 1
    # 其他标签页已轮换：共享存储和内存状态都跟随新令牌，不被旧请求清除。
    assert result["stored"]["refresh"] == "otherR"
    assert result["state"]["authRefreshToken"] == "otherR"
    assert result["state"]["authAccessToken"] == "otherA"
