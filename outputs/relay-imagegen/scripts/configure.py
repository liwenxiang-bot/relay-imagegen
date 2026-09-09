#!/usr/bin/env python3
"""One-time local setup for relay-imagegen. The key is entered silently and stored with mode 600."""
from __future__ import annotations
import getpass
import json
import os
from pathlib import Path

CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
CONFIG = CODEX_HOME / "skills" / "relay-imagegen" / "config.json"

def main() -> None:
    print("Relay Image Generator 一次性配置（API key 不会显示，也不会上传到聊天）。")
    base = input("中转 API 地址 [https://api.9e.lv/v1]: ").strip() or "https://api.9e.lv/v1"
    if base.rstrip("/") == "https://api.9e.lv":
        base = base.rstrip("/") + "/v1"
    model = input("图片模型 [gpt-image-2]: ").strip() or "gpt-image-2"
    key = getpass.getpass("API key（输入时不显示）: ").strip()
    if not key:
        raise SystemExit("API key 不能为空")
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps({"base_url": base.rstrip("/"), "model": model, "api_key": key}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(CONFIG, 0o600)
    print(f"配置已保存到 {CONFIG}。以后直接描述画图需求即可。")

if __name__ == "__main__":
    main()
