#!/usr/bin/env python3
"""relay-imagegen 一次性配置。API key 输入时不回显，保存后权限为 600。"""
from __future__ import annotations

import getpass
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_BASE_URL = "https://api.9e.lv/v1"
DEFAULT_MODEL = "gpt-image-2"

CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
CLAUDE_HOME = Path(os.environ.get("CLAUDE_HOME", Path.home() / ".claude")).expanduser()


def target_config_path() -> Path:
    """装在哪个 agent 目录下，就把配置写到对应位置。"""
    here = Path(__file__).resolve()
    for home in (CODEX_HOME, CLAUDE_HOME):
        try:
            here.relative_to(home)
            return home / "skills" / "relay-imagegen" / "config.json"
        except ValueError:
            continue
    return here.parents[1] / "config.json"


def normalize_base_url(base: str) -> str:
    base = base.strip().rstrip("/")
    if not base:
        return DEFAULT_BASE_URL
    if not base.startswith(("http://", "https://")):
        base = "https://" + base
    tail = urllib.parse.urlparse(base).path.rstrip("/")
    if not re.search(r"/v\d+(?:beta)?$", tail):
        base += "/v1"
    return base


def ask(label: str, default: str) -> str:
    try:
        value = input(f"{label} [{default}]: ").strip()
    except EOFError:
        return default
    return value or default


def probe_models(base: str, key: str) -> list[str]:
    request = urllib.request.Request(
        f"{base}/models",
        headers={"Authorization": f"Bearer {key}", "User-Agent": "relay-imagegen/2.0.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return []
    return [m.get("id", "") for m in payload.get("data", []) if isinstance(m, dict)]


def main() -> None:
    print("=" * 56)
    print(" relay-imagegen 配置向导")
    print(" API key 输入时不会显示，也不会出现在对话或日志里。")
    print("=" * 56)

    base = normalize_base_url(ask("1/3 中转 API 地址", DEFAULT_BASE_URL))
    print(f"      → 使用 {base}")

    try:
        key = getpass.getpass("2/3 API key（输入时不显示，粘贴后回车）: ").strip()
    except EOFError:
        key = ""
    if not key:
        raise SystemExit("API key 不能为空，配置中止。")
    if key.startswith("sk-") and len(key) < 20:
        print("      ⚠️  这个 key 看起来偏短，请确认粘贴完整。")

    print("      正在验证 key 并拉取模型列表 ...")
    models = probe_models(base, key)
    image_models = [m for m in models if m and re.search(
        r"image|dall|flux|banana|seedream|qwen-image|kolors|sd\d|midjourney", m, re.I)]
    if image_models:
        print(f"      ✅ 连接成功，可用图片模型：{', '.join(image_models)}")
        suggested = DEFAULT_MODEL if DEFAULT_MODEL in image_models else image_models[0]
    else:
        print("      ⚠️  未能拉到模型列表（部分中转站不开放 /models，不影响生图）")
        suggested = DEFAULT_MODEL

    model = ask("3/3 图片模型", suggested)
    if models and model not in models:
        print(f"      ⚠️  {model} 不在该站模型列表里，如果生图报 400 请改用上面列出的名称。")

    config_path = target_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps({"base_url": base, "model": model, "api_key": key},
                   ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.chmod(config_path, 0o600)

    print()
    print(f"配置已保存：{config_path}（权限 600，仅本人可读）")
    print()
    print("下一步：跑一次自检确认能出图")
    print(f"  python3 {Path(__file__).resolve().parent / 'relay_imagegen.py'} --doctor")
    print()
    print("之后在 Codex / Claude Code 里直接说“画一只猫”就行。")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已取消。", file=sys.stderr)
        raise SystemExit(130)
