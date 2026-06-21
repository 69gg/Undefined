# scripts/

运维与维护脚本集合。

## 脚本列表

### [`build_native_apps.py`](build_native_apps.py) — 本地原生 App 构建

统一编排本机可构建的 Console / Chat 原生产物。脚本不会自动安装系统依赖、Android SDK 包或 Rust target；`check` 子命令只报告缺口并给出修复提示。

```bash
# 查看将要执行的本地构建矩阵
uv run python scripts/build_native_apps.py list --product all --targets all --android-abi all

# 检查 Android arm64 debug APK 构建环境
uv run python scripts/build_native_apps.py check --targets android --android-abi arm64-v8a

# 构建 Chat arm64 debug APK
uv run python scripts/build_native_apps.py build --product chat --targets android --android-abi arm64-v8a

# 构建 Console + Chat 的 Linux deb
uv run python scripts/build_native_apps.py build --product all --targets desktop --desktop-bundles deb
```

常用参数：

- `--product chat|console|all`：选择 App，默认 `chat`。
- `--targets android|desktop|all`：选择本机目标，默认 `android`。
- `--android-abi arm64-v8a|armeabi-v7a|x86|x86_64|all`：选择 Android ABI，默认 `arm64-v8a`。
- `--desktop-bundles deb|appimage|all`：Linux 桌面包类型，默认 `deb`。
- `--android-init auto|always|skip`：Android 生成工程初始化策略，默认 `auto`。
- `--output-dir PATH`：产物收集目录，默认 `dist/native/<short-sha>/`。
- `--dry-run`：只打印命令，不执行。
- `--no-install-deps`：不在缺少 `node_modules/.bin/tauri` 时自动执行 `npm ci`。

### [`sync_config_template.py`](sync_config_template.py) — 同步配置模板与注释

保留当前 `config.toml` 已有配置值，同时把 `config.toml.example` 中新增的配置项、默认空表和双语注释同步回来。

```bash
# 直接用 Python 运行
python scripts/sync_config_template.py

# 若希望复用项目虚拟环境，也可这样运行
uv run python scripts/sync_config_template.py

# 仅预览，不落盘
python scripts/sync_config_template.py --dry-run

# 输出同步后的完整内容
python scripts/sync_config_template.py --stdout
```

**适用场景**：
- 项目升级后想把新增配置项补齐到现有 `config.toml`
- 想恢复 `config.toml.example` 中的最新双语注释
- 不想手工比对新旧配置文件

### [`reembed_cognitive.py`](reembed_cognitive.py) — 认知记忆向量库重嵌入

当更换嵌入模型（维度变化或模型升级）时，对 ChromaDB 中的 `cognitive_events` 和 `cognitive_profiles` 进行全量重嵌入。

**原理**：ChromaDB 存储了完整的原文本（`documents`），脚本读取所有记录，用新模型重新计算向量后 upsert 覆写，metadata 保持不变。

**前置条件**：先在 `config.toml` 中将 `[models.embedding]` 更新为新模型配置。

```bash
# 全量重嵌入（事件 + 侧写）
uv run python scripts/reembed_cognitive.py

# 仅重嵌入事件
uv run python scripts/reembed_cognitive.py --events-only

# 仅重嵌入侧写
uv run python scripts/reembed_cognitive.py --profiles-only

# 自定义批大小（默认 32，降低可减小 API 压力）
uv run python scripts/reembed_cognitive.py --batch-size 16

# 模拟运行（不实际写入，用于验证配置和统计数量）
uv run python scripts/reembed_cognitive.py --dry-run

# 详细日志
uv run python scripts/reembed_cognitive.py -v
```

**注意**：
- 运行期间不要同时启动机器人，避免 ChromaDB 写入冲突
- 大量记录时注意 API 限速，可通过 `--batch-size` 降低并发
- 建议先用 `--dry-run` 确认记录数量和配置正确性

### release_notes.py — 发布版本校验与 Release notes 生成

Release workflow 使用这个脚本在构建前校验版本一致性，并在发布阶段从 `CHANGELOG.md` 最新版本条目生成 GitHub Release 说明。Release notes 会先写入 changelog 自动提取内容，再用 `---` 分隔并追加 `Detailed Changes`，按上一个 tag 到当前 tag 的 commit 主题分类列出 features、bug fixes 和 maintenance/others。

```bash
# 校验 tag、构建版本和 CHANGELOG 最新版本一致
uv run python scripts/release_notes.py validate --tag v3.4.0

# 从 CHANGELOG 最新条目生成 Release notes，并追加 Detailed Changes
python3 scripts/release_notes.py notes --tag v3.4.0 --output release_notes.md
```

**校验范围**：

- `pyproject.toml`
- `src/Undefined/__init__.py`
- `apps/undefined-console/package.json`
- `apps/undefined-console/package-lock.json`
- `apps/undefined-console/src-tauri/Cargo.toml`
- `apps/undefined-console/src-tauri/tauri.conf.json`
- `apps/undefined-console/src-tauri/Cargo.lock` 根包版本
- `apps/undefined-chat/package.json`
- `apps/undefined-chat/package-lock.json`
- `apps/undefined-chat/src-tauri/Cargo.toml`
- `apps/undefined-chat/src-tauri/tauri.conf.json`
- `apps/undefined-chat/src-tauri/Cargo.lock` 根包版本
- `CHANGELOG.md` 最新版本条目

### bump_version.py — 同步项目版本号

统一以 `pyproject.toml` 的主版本为源，更新 Python 包、Console 和 Chat 的版本文件。

```bash
uv run python scripts/bump_version.py 3.6.0
uv run python scripts/bump_version.py 3.6.0 --dry-run
uv run python scripts/bump_version.py 3.6.0 --commit
```

同步范围：

- `pyproject.toml`
- `src/Undefined/__init__.py`
- `apps/undefined-console/package.json`
- `apps/undefined-console/package-lock.json`
- `apps/undefined-console/src-tauri/Cargo.toml`
- `apps/undefined-console/src-tauri/tauri.conf.json`
- `apps/undefined-console/src-tauri/Cargo.lock`
- `apps/undefined-chat/package.json`
- `apps/undefined-chat/package-lock.json`
- `apps/undefined-chat/src-tauri/Cargo.toml`
- `apps/undefined-chat/src-tauri/tauri.conf.json`
- `apps/undefined-chat/src-tauri/Cargo.lock`

非 dry-run 时脚本还会执行 `uv sync`，并分别在 Console / Chat 下执行 `npm install --package-lock-only` 与 `cargo update --workspace`，保证 lock 文件和 manifest 不漂移。
脚本更新 JSON manifest 时只替换顶层 `version` 字段，保留现有格式，避免 Tauri 配置与 Biome 格式化规则漂移。

### prepare_tauri_android.py — 生成后 Android 修补

Tauri 的 `src-tauri/gen/` 是生成目录，不提交到仓库。Undefined Chat 需要移动端 HTML 预览使用独立 Android Activity，并需要 Android Keystore 安全存储插件，因此 Chat 的 `npm run tauri:android:init` 会在生成后运行：

```bash
python3 ../../scripts/prepare_tauri_android.py .
python3 ../../scripts/prepare_tauri_android.py . --check
```

脚本只对 `apps/undefined-chat` 生效，会向生成的 Android app 注入 `HtmlPreviewActivity.kt`、`SecretPlugin.kt`，并在 `AndroidManifest.xml` 中声明预览 Activity 的 `android:exported="false"`。Console 保持 no-op。
