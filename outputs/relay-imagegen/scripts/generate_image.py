#!/usr/bin/env python3
"""Generate images through an OpenAI-compatible relay, using only the stdlib."""
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import sys
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

SKILL_DIR = Path(__file__).resolve().parents[1]
CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
USER_CONFIG = CODEX_HOME / "skills" / "relay-imagegen" / "config.json"
DEFAULT_MODEL = "gpt-image-2"
DEFAULT_BASE_URL = "https://api.9e.lv/v1"


def fail(message: str, code: int = 1) -> None:
    print(f"relay-imagegen: {message}", file=sys.stderr)
    raise SystemExit(code)


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"无法读取配置文件 {path}: {exc}")
    if not isinstance(value, dict):
        fail(f"配置文件 {path} 必须是 JSON 对象")
    return value


def load_config(path: Path | None) -> dict[str, str]:
    values: dict[str, str] = {}
    candidates = [path] if path else [USER_CONFIG, Path.cwd() / ".relay-imagegen.json"]
    for candidate in candidates:
        if candidate and candidate.is_file():
            raw = read_json(candidate)
            values = {str(k): str(v) for k, v in raw.items() if v is not None}
            break
    aliases = {
        "api_key": ("OPENAI_API_KEY", "IMG_API_KEY", "api_key"),
        "base_url": ("OPENAI_BASE_URL", "OPENAI_API_BASE", "IMG_BASE_URL", "base_url"),
        "model": ("OPENAI_IMAGE_MODEL", "IMAGE_MODEL", "IMG_MODEL", "model"),
    }
    result: dict[str, str] = {}
    for name, names in aliases.items():
        for env_name in names:
            if os.environ.get(env_name, "").strip():
                result[name] = os.environ[env_name].strip()
                break
            if env_name in values and values[env_name].strip():
                result[name] = values[env_name].strip()
                break
    result.setdefault("base_url", DEFAULT_BASE_URL)
    result.setdefault("model", DEFAULT_MODEL)
    if not result.get("api_key"):
        fail("没有找到 API key。运行 `python3 scripts/configure.py` 配置一次，或设置 OPENAI_API_KEY。")
    return result


def data_uri(path: str) -> str:
    file = Path(path).expanduser()
    if not file.is_file():
        fail(f"参考图片不存在: {file}")
    mime = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
    if mime not in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
        fail("参考图片仅支持 PNG、JPEG、WEBP 或 GIF")
    return f"data:{mime};base64,{base64.b64encode(file.read_bytes()).decode('ascii')}"


def decode_data_uri(value: str) -> bytes | None:
    if not value.startswith("data:") or "," not in value:
        return None
    header, encoded = value.split(",", 1)
    if ";base64" not in header:
        return None
    try:
        return base64.b64decode(encoded, validate=True)
    except Exception as exc:
        fail(f"无法解码 data URL 图片: {exc}")


def request_json(url: str, key: str, payload: dict[str, Any], timeout: int = 180) -> dict[str, Any]:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST", headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json", "Accept": "application/json",
        "User-Agent": "relay-imagegen/1.0",
    })
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                body = response.read()
            break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:1000]
            if exc.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            fail(f"API 返回 HTTP {exc.code}: {detail}")
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
            fail(f"无法连接 API: {exc}")
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        fail(f"API 返回不是 JSON: {body[:300]!r}")
    if not isinstance(parsed, dict):
        fail("API 返回格式不正确")
    return parsed


def save_images(result: dict[str, Any], output_dir: Path, fmt: str) -> list[Path]:
    items = result.get("data")
    if not isinstance(items, list) or not items:
        fail(f"API 返回没有 data 图片数组: {json.dumps(result, ensure_ascii=False)[:500]}")
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    stamp = time.strftime("%Y%m%d-%H%M%S")
    token = uuid.uuid4().hex[:8]
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict):
            fail("API 返回的 data 项不是对象")
        out = output_dir / f"image-{stamp}-{token}-{index:02d}.{fmt}"
        if item.get("b64_json"):
            try:
                encoded = str(item["b64_json"])
                out.write_bytes(base64.b64decode(encoded.split(",", 1)[-1], validate=True))
            except Exception as exc:
                fail(f"无法解码 b64_json: {exc}")
        elif item.get("url"):
            url = str(item["url"])
            inline = decode_data_uri(url)
            if inline is not None:
                out.write_bytes(inline)
                paths.append(out)
                continue
            suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
            if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
                out = out.with_suffix(".jpg" if suffix == ".jpeg" else suffix)
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "relay-imagegen/1.0"}), timeout=180) as response:
                    out.write_bytes(response.read())
            except (urllib.error.URLError, TimeoutError) as exc:
                fail(f"无法下载生成的图片: {exc}")
        else:
            fail("图片项既没有 b64_json 也没有 url")
        paths.append(out)
    return paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="通过 OpenAI 兼容中转 API 生成图片")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prompt", help="图片提示词")
    group.add_argument("--prompt-file", help="从文本文件读取提示词")
    parser.add_argument("--image", help="参考图片路径（部分中转服务支持）")
    parser.add_argument("--size", default="1024x1024", help="尺寸，如 1024x1024、1536x1024、1024x1536")
    parser.add_argument("--quality", help="可选质量参数，如 low、medium、high")
    parser.add_argument("--n", type=int, default=1, choices=range(1, 5), help="生成数量，默认 1")
    parser.add_argument("--output-dir", default="generated-images", help="输出目录")
    parser.add_argument("--format", choices=("png", "jpeg", "webp"), default="png")
    parser.add_argument("--config", help="指定 JSON 配置文件")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.prompt:
        prompt = args.prompt.strip()
    else:
        try:
            prompt = Path(args.prompt_file).expanduser().read_text(encoding="utf-8").strip()
        except OSError as exc:
            fail(f"无法读取 prompt 文件: {exc}")
    if not prompt:
        fail("prompt 不能为空")
    config = load_config(Path(args.config).expanduser() if args.config else None)
    payload: dict[str, Any] = {"model": config["model"], "prompt": prompt, "size": args.size, "n": args.n}
    if args.quality:
        payload["quality"] = args.quality
    endpoint = "images/edits" if args.image else "images/generations"
    if args.image:
        payload.pop("n", None)
        payload["images"] = [{"image_url": data_uri(args.image)}]
        payload["n"] = args.n
    payload["output_format"] = args.format
    base = config["base_url"].rstrip("/")
    print(f"正在调用图片 API（endpoint=/{endpoint}, model={config['model']}）...", file=sys.stderr)
    result = request_json(f"{base}/{endpoint}", config["api_key"], payload)
    paths = save_images(result, Path(args.output_dir).expanduser(), args.format)
    for path in paths:
        print(path.resolve())


if __name__ == "__main__":
    main()
