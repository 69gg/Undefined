# Undefined 9527 人设图

- 日期：2026-10-26（Asia/Shanghai）
- 模型：`gpt-image-2.5-sunburst`（用户指定）
- 生成方式：imagegen 技能的 API / CLI 模式，通过用户指定的兼容接口调用。
- 原图：[undefined-9527-concept-20261026.png](undefined-9527-concept-20261026.png)
- 最终提示词：[undefined-9527-concept-20261026.prompt.txt](undefined-9527-concept-20261026.prompt.txt)，原文直接提交，`--no-augment`。
- 参数：`n=1`、`size=1024x1536`、`quality=high`、`output_format=png`。
- 返回文件：PNG、RGB、1024 × 1536，1,814,154 字节。
- 接口调用耗时：41.2 秒。
- SHA-256：`ee0cb7d373a0c575d241d7fce298671106bba6d5b750d11f3f5156138af136f3`。

## 结果检查

已通过 Pillow 文件完整性检查和重新解码检查，并肉眼检查全身构图、黑橙短发、灰色眼睛与琥珀色准星、黑色机能服、`UNDEFINED 9527` 胸牌及悬浮记忆卡。模型输出为包含主立绘、三视图和局部细节的人设展示页。保留模型返回的原始像素，未裁切、重绘或替换现有项目图片。

## 复现调用

先在本地进程环境中设置 `OPENAI_API_KEY` 和 `OPENAI_BASE_URL`；后者应指向用户指定兼容接口的 `/v1` 地址。凭据和接口地址不写入本目录文件。

```bash
uv run --no-sync python /home/pyl/.codex/skills/.system/imagegen/scripts/image_gen.py generate \
  --model gpt-image-2.5-sunburst \
  --prompt-file output/imagegen/undefined-9527-concept-20261026.prompt.txt \
  --no-augment \
  --size 1024x1536 \
  --quality high \
  --output-format png \
  --out output/imagegen/undefined-9527-concept-20261026-rerun.png
```

重新调用会生成新的图像，不能保证像素一致。

## 后续清理版

根据用户要求，已另存[去除外围细节框、三视图和文字的干净立绘](undefined-9527-clean-20261026.png)，详见[编辑记录](undefined-9527-clean-20261026.md)。本原始展示页保留不变。
