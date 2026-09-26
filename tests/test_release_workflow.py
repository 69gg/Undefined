"""Release workflow 的结构契约。

这里的每一条都对应一次真实踩过的事故，而不是「YAML 长什么样」：

- build-push-action 默认上传的构建记录是**非 zip** artifact，而
  ``actions/download-artifact`` 不带 ``name``/``pattern`` 时会下载全部
  artifact 并在非 zip 上失败（官方 README 明确警告），整条发版流水线会红；
- 用 ``gh release create release-downloads/*`` 发资产时，任何内部 artifact
  混进下载目录都会被当成发行资产发出去；
- 在 amd64 runner 上用 QEMU 模拟 arm64 构建本体镜像，会在
  ``playwright install --with-deps chromium`` 上超时，而该 job 失败会连带
  阻断 release 与 PyPI。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"

BUILD_PUSH = "docker/build-push-action"
DOWNLOAD_ARTIFACT = "actions/download-artifact"
UPLOAD_ARTIFACT = "actions/upload-artifact"


def _workflow() -> dict[str, Any]:
    data: Any = yaml.safe_load(RELEASE_WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "release.yml 解析结果不是映射"
    return data


def _steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    return list(job.get("steps") or [])


def _all_steps(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    return [step for job in workflow["jobs"].values() for step in _steps(job)]


def test_build_records_are_never_uploaded() -> None:
    """只要有一个 build-push 步骤开着构建记录上传，下载侧就会拿到非 zip。"""
    workflow = _workflow()
    assert (workflow["env"] or {}).get("DOCKER_BUILD_RECORD_UPLOAD") == "false", (
        "workflow 级 env 必须关掉构建记录上传；否则 build-push-action 会上传"
        "非 zip 的 .dockerbuild artifact，下载侧会因此失败"
    )
    assert any(
        str(step.get("uses", "")).startswith(BUILD_PUSH)
        for step in _all_steps(workflow)
    ), "没有任何 build-push 步骤，这条断言会失去意义"


def test_no_download_without_name_or_pattern() -> None:
    """不带 name 也不带 pattern 的下载会拉走**全部** artifact。

    这正是构建记录（非 zip）把发布流水线弄红的机制：上游 README 明确要求
    这种情况下必须写 ``pattern: "!*.dockerbuild"``。
    """
    workflow = _workflow()
    for job_name, job in workflow["jobs"].items():
        for step in _steps(job):
            if not str(step.get("uses", "")).startswith(DOWNLOAD_ARTIFACT):
                continue
            with_args = step.get("with") or {}
            assert "name" in with_args or with_args.get("pattern"), (
                f"{job_name} 的「{step.get('name')}」既没有 name 也没有 pattern，"
                "会下载全部 artifact（含非 zip 的内部产物）"
            )


def test_release_assets_exclude_internal_artifacts() -> None:
    """`gh release create release-downloads/*` 会把目录里的一切当发行资产。"""
    workflow = _workflow()
    release_job = workflow["jobs"]["publish-release"]
    assert any(
        "gh release create" in str(step.get("run", "")) for step in _steps(release_job)
    ), "publish-release 不再用 gh release create，这条断言需要重新审视"

    asset_downloads = [
        step
        for step in _steps(release_job)
        if str(step.get("uses", "")).startswith(DOWNLOAD_ARTIFACT)
    ]
    assert asset_downloads, "publish-release 没有下载任何 artifact"
    for step in asset_downloads:
        pattern = str((step.get("with") or {}).get("pattern", ""))
        assert pattern.startswith("!"), (
            f"「{step.get('name')}」没有排除内部产物（pattern={pattern!r}），"
            "digest 文件会被当成发行资产发出去"
        )


def test_download_patterns_match_uploaded_artifacts() -> None:
    """下载侧的 name/pattern 必须真的对得上上传的 artifact 名。

    改个 artifact 名而忘了改 pattern，失败会推迟到真跑 workflow 时才出现
    （而且往往正好卡在发版那一步）。
    """
    workflow = _workflow()
    uploaded = {
        str((step.get("with") or {}).get("name", ""))
        for step in _all_steps(workflow)
        if str(step.get("uses", "")).startswith(UPLOAD_ARTIFACT)
    }
    assert uploaded, "workflow 没有上传任何 artifact"

    checked: list[str] = []
    for job_name, job in workflow["jobs"].items():
        for step in _steps(job):
            if not str(step.get("uses", "")).startswith(DOWNLOAD_ARTIFACT):
                continue
            with_args = step.get("with") or {}
            label = f"{job_name}/「{step.get('name')}」"
            if "name" in with_args:
                wanted = str(with_args["name"])
                assert wanted in uploaded, f"{label} 下载的 {wanted!r} 无人上传"
                checked.append(wanted)
                continue
            raw = str(with_args.get("pattern", ""))
            prefix = raw.lstrip("!").rstrip("*")
            matched = {name for name in uploaded if name.startswith(prefix)}
            assert matched, (
                f"{label} 的模式 {raw!r} 匹配不到任何 artifact；"
                f"实际上传的：{sorted(uploaded)}"
            )
            checked.append(raw)
    assert checked, "没有任何下载模式被校验，这条断言已形同虚设"


def test_no_emulated_arm64_build() -> None:
    """arm64 必须跑在原生 runner 上，且不能再依赖 QEMU 模拟。"""
    workflow = _workflow()
    job = workflow["jobs"]["build-docker"]
    matrix = job["strategy"]["matrix"]["include"]
    platforms = {entry["platform"] for entry in matrix}
    runners = {entry["runner"] for entry in matrix}
    assert platforms == {"linux/amd64", "linux/arm64"}
    # 同一个 runner 跑两个架构 = 其中一个必然是模拟的
    assert len(runners) == len(platforms), f"架构与 runner 不是一一对应：{matrix}"
    assert not [
        step
        for step in _all_steps(workflow)
        if "setup-qemu" in str(step.get("uses", ""))
    ], "原生 runner 构建不需要 QEMU，留着会掩盖「某个架构其实是模拟的」"


def test_arm64_digests_are_merged_into_a_manifest_list() -> None:
    """两个架构各自推 digest，最终 tag 必须由 merge 步骤合并出来。

    注意每个 build-push 步骤都要按 digest 推：只改其中一个（例如只让本体镜像
    直接 push tag）会让「多架构」静默退化成单架构。
    """
    workflow = _workflow()
    build = workflow["jobs"]["build-docker"]
    build_steps = [
        step
        for step in _steps(build)
        if str(step.get("uses", "")).startswith(BUILD_PUSH)
    ]
    assert build_steps, "build-docker 里没有 build-push 步骤"
    for step in build_steps:
        outputs = str((step.get("with") or {}).get("outputs", ""))
        assert "push-by-digest=true" in outputs, (
            f"「{step.get('name')}」没有按 digest 推送（outputs={outputs!r}），"
            "多架构合并会退化"
        )

    merge = workflow["jobs"]["merge-docker"]
    merges = [
        step
        for step in _steps(merge)
        if "imagetools create" in str(step.get("run", ""))
    ]
    assert merges, "merge-docker 没有创建 manifest list"
    for step in merges:
        assert "-t " in str(step["run"]), "合并时必须打上最终 tag"


def test_lxmusic2api_image_is_built_unconditionally() -> None:
    """pin 是硬要求，CI 不该再留「占位就跳过」的分支。

    短 sha 会被当作镜像 tag，只有完整 sha 才能复现构建——这一点由
    `tests/test_deploy_catalog.py::test_lxmusic2api_pin_is_full_sha` 强制，而它在
    verify-python 里先跑。因此「未 pin 时跳过构建」的分支永远不可达，留着只会
    让流程看起来宽容（并且让 docker-pins 的输出多一个没人能触发的取值）。
    """
    workflow = _workflow()
    pins = workflow["jobs"]["docker-pins"]["outputs"]
    assert "lxmusic2api_pinned" not in pins, f"跳过分支又回来了：{sorted(pins)}"

    for job_name in ("build-docker", "merge-docker"):
        conditional = [
            step.get("name")
            for step in _steps(workflow["jobs"][job_name])
            if "lxmusic2api_pinned" in str(step.get("if", ""))
        ]
        assert not conditional, f"{job_name} 仍有依赖跳过分支的步骤：{conditional}"

    # 该镜像的构建步骤必须存在且无条件
    builds = [
        step
        for step in _steps(workflow["jobs"]["build-docker"])
        if str(step.get("uses", "")).startswith(BUILD_PUSH)
        and "LXMUSIC2API_IMAGE" in str((step.get("with") or {}).get("outputs", ""))
    ]
    assert len(builds) == 1, "build-docker 里应有且只有一个 lxmusic2api 构建步骤"
    assert "if" not in builds[0]


def test_release_waits_for_the_docker_images() -> None:
    """「版本发布前面，程序构建后面」：发版必须等镜像合并完成。"""
    workflow = _workflow()
    needs = workflow["jobs"]["publish-release"]["needs"]
    assert "merge-docker" in needs, (
        "publish-release 必须等 merge-docker 把 manifest list 建好，"
        "否则发行资产会指向还不存在的镜像 tag"
    )
    # merge-docker 必须真的构建过镜像，而不是只依赖 pin 解析
    assert "build-docker" in workflow["jobs"]["merge-docker"]["needs"], (
        "merge-docker 没有依赖 build-docker，合并的 digest 来源不明"
    )


_OUTPUT_REF = re.compile(r"needs\.([A-Za-z0-9_-]+)\.outputs\.([A-Za-z0-9_-]+)")
_STEP_OUTPUT_REF = re.compile(r"steps\.([A-Za-z0-9_-]+)\.outputs")


def _strings(node: Any) -> list[str]:
    """递归取出节点里的所有字符串（含 list / dict 嵌套）。"""
    if isinstance(node, str):
        return [node]
    if isinstance(node, list):
        return [text for item in node for text in _strings(item)]
    if isinstance(node, dict):
        return [text for value in node.values() for text in _strings(value)]
    return []


def _needs(job: dict[str, Any]) -> set[str]:
    raw = job.get("needs") or []
    return {raw} if isinstance(raw, str) else set(raw)


def test_workflow_output_references_resolve() -> None:
    """`needs.<job>.outputs.<name>` 与 `steps.<id>.outputs` 必须真的存在。

    workflow 没法在本地执行，写错引用只会在推 tag 那一刻才炸——正好是发版最不
    该出错的时刻。这里做一次静态解析：引用链、job 的 needs、声明的 outputs、
    step id 四者必须自洽。
    """
    workflow = _workflow()
    jobs = workflow["jobs"]
    checked: list[str] = []

    for job_name, job in jobs.items():
        step_ids = {
            step["id"] for step in _steps(job) if isinstance(step.get("id"), str)
        }
        needs = _needs(job)
        for text in _strings(job.get("steps") or []):
            for ref_job, ref_output in _OUTPUT_REF.findall(text):
                assert ref_job in needs, (
                    f"{job_name} 引用了 {ref_job} 的输出，但 needs 里没有它："
                    f"{sorted(needs)}（跨 job 取输出必须显式声明依赖）"
                )
                outputs = jobs[ref_job].get("outputs") or {}
                assert ref_output in outputs, (
                    f"{job_name} 引用了 {ref_job}.outputs.{ref_output}，"
                    f"但该 job 只声明了 {sorted(outputs)}"
                )
                checked.append(f"needs.{ref_job}.outputs.{ref_output}")
            for ref_step in _STEP_OUTPUT_REF.findall(text):
                assert ref_step in step_ids, (
                    f"{job_name} 引用了 steps.{ref_step}.outputs，"
                    f"但该 job 里没有这个 id：{sorted(step_ids)}"
                )
                checked.append(f"steps.{ref_step}")

    assert checked, "没有解析到任何 output 引用，该断言已形同虚设"
