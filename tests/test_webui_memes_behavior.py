"""Meme detail selection and drafts survive delayed management responses."""

from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest

from test_webui_runtime_chat_behavior import REPO_ROOT, _require_env


def _run_meme_scenario(scenario: str) -> dict[str, Any]:
    _require_env()
    script = r"""
const fs=require('node:fs');
const root=process.argv[1], scenario=process.argv[2];
const {JSDOM}=require(root+'/tests/frontend/node_modules/jsdom');
const dom=new JSDOM(fs.readFileSync(root+'/src/Undefined/webui/templates/index.html','utf8'),
  {url:'http://isolated.example',runScripts:'outside-only'});
const w=dom.window, details=[], patches=[];
w.get=id=>w.document.getElementById(id);w.t=k=>k;w.escapeHtml=s=>String(s);w.showToast=()=>{};
w.confirm=()=>true;
w.api=async(path,opts={})=>{
  if(path.endsWith('/stats'))return {ok:true,json:async()=>({})};
  if(path.includes('/memes?'))return {ok:true,json:async()=>({items:[{uid:'A'},{uid:'B'}],total:2,page:1,page_size:50})};
  if(opts.method==='PATCH'||opts.method==='DELETE')return new Promise(resolve=>patches.push({path,body:opts.body&&JSON.parse(opts.body),resolve}));
  return new Promise(resolve=>details.push({uid:path.split('/').at(-1),resolve}));
};
w.eval(fs.readFileSync(root+'/src/Undefined/webui/static/js/memes.js','utf8'));
w.MemesController.init();w.MemesController.onTabActivated('memes');
const tick=async()=>{for(let i=0;i<10;i++)await new Promise(r=>setImmediate(r));};
const answer=(request,text)=>request.resolve({ok:true,json:async()=>({record:{uid:request.uid,
  manual_description:text,enabled:true},sources:[]})});
const click=uid=>w.document.querySelector(`[data-meme-uid="${uid}"]`).click();
(async()=>{
  await tick();click('A');await tick();
  if(scenario==='selection'){
    click('B');answer(details[1],'B saved');await tick();
    w.get('memesDetailManualDescription').value='B unsaved';answer(details[0],'A saved');await tick();
  }else{
    answer(details[0],'A saved');await tick();
    if(scenario==='refresh'){
      w.get('btnMemesRefresh').click();await tick();
      w.get('memesDetailManualDescription').value='A draft during refresh';
      answer(details[1],'A refreshed');await tick();
    }else{
      w.get('memesDetailManualDescription').value='A first edit';w.get('btnMemesSave').click();await tick();
      if(scenario==='save_switch'){
        click('B');answer(details[1],'B saved');await tick();
        w.get('memesDetailManualDescription').value='B unsaved';
      }else if(scenario==='save_edit')w.get('memesDetailManualDescription').value='A second unsaved edit';
      patches[0].resolve({ok:true});await tick();
      if(scenario!=='save_switch')answer(details[1],'A first edit');
      await tick();
    }
  }
  console.log(JSON.stringify({uid:w.get('memesDetailUid').textContent,
    draft:w.get('memesDetailManualDescription').value,detailRequests:details.map(item=>item.uid),
    sent:patches.map(item=>item.body),saveEnabled:!w.get('btnMemesSave').disabled}));
  dom.window.close();
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    completed = subprocess.run(
        ["node", "-e", script, str(REPO_ROOT), scenario],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    result: dict[str, Any] = json.loads(completed.stdout.strip().splitlines()[-1])
    return result


def test_late_meme_detail_cannot_change_selection_or_draft() -> None:
    result = _run_meme_scenario("selection")
    assert result["uid"] == "B"
    assert result["draft"] == "B unsaved"


@pytest.mark.parametrize(
    ("scenario", "uid", "draft"),
    [
        ("save_edit", "A", "A second unsaved edit"),
        ("save_switch", "B", "B unsaved"),
        ("save_unchanged", "A", "A first edit"),
        ("refresh", "A", "A draft during refresh"),
    ],
)
def test_meme_background_refresh_preserves_later_edits(
    scenario: str, uid: str, draft: str
) -> None:
    result = _run_meme_scenario(scenario)
    assert result["uid"] == uid
    assert result["draft"] == draft
    assert result["saveEnabled"] is True
    if scenario.startswith("save_"):
        assert result["sent"][0]["manual_description"] == "A first edit"
    if scenario == "save_switch":
        assert result["detailRequests"] == ["A", "B"]
