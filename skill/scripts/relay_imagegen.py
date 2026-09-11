#!/usr/bin/env python3
"""通过 OpenAI 兼容中转 API 生成 / 修改图片。只依赖 Python 标准库。

设计要点：
- 配置来源优先级：命令行 --config > 环境变量 > 本地 config.json > 内置默认值
- 无参考图 -> POST {base}/images/generations
- 有参考图 -> POST {base}/images/edits，请求体形状会在多种常见方案间自动回退
- 响应同时兼容 b64_json / url / 异步任务轮询
- API key 永不打印，异常信息里也会被打码
"""
from __future__ import annotations

import argparse
import base64
import binascii
import json
import mimetypes
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

VERSION = "2.0.0"
SKILL_DIR = Path(__file__).resolve().parents[1]
CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
CLAUDE_HOME = Path(os.environ.get("CLAUDE_HOME", Path.home() / ".claude")).expanduser()

DEFAULT_BASE_URL = "https://api.9e.lv/v1"
DEFAULT_MODEL = "gpt-image-2"
DEFAULT_TIMEOUT = 300
UA = f"relay-imagegen/{VERSION}"

IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

# 文件头 -> 扩展名，用于按真实返回内容决定后缀
MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpg"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
)


# ── 输出与错误 ────────────────────────────────────────────────

_SECRETS: list[str] = []


def scrub(text: str) -> str:
    """把 key 从任何要打印的文本里抹掉。"""
    for secret in _SECRETS:
        if secret and len(secret) >= 8:
            text = text.replace(secret, "sk-***")
    return re.sub(r"sk-[A-Za-z0-9_\-]{12,}", "sk-***", text)


def info(message: str) -> None:
    print(f"relay-imagegen: {scrub(message)}", file=sys.stderr)


def fail(message: str, hint: str = "", code: int = 1) -> None:
    print(f"relay-imagegen 错误：{scrub(message)}", file=sys.stderr)
    if hint:
        print(f"  → {scrub(hint)}", file=sys.stderr)
    raise SystemExit(code)


# ── 配置 ─────────────────────────────────────────────────────

CONFIG_CANDIDATES = (
    CODEX_HOME / "skills" / "relay-imagegen" / "config.json",
    CLAUDE_HOME / "skills" / "relay-imagegen" / "config.json",
    SKILL_DIR / "config.json",
)

ALIASES = {
    "api_key": ("RELAY_IMAGE_API_KEY", "OPENAI_API_KEY", "IMG_API_KEY", "API_KEY"),
    "base_url": ("RELAY_IMAGE_BASE_URL", "OPENAI_BASE_URL", "OPENAI_API_BASE", "IMG_BASE_URL"),
    "model": ("RELAY_IMAGE_MODEL", "OPENAI_IMAGE_MODEL", "IMAGE_MODEL", "IMG_MODEL"),
}


def _clean(value: Any) -> str:
    text = str(value).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        text = text[1:-1].strip()
    return text


def read_config_file(path: Path) -> dict[str, str]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        fail(f"无法读取配置文件 {path}：{exc}")
    except json.JSONDecodeError as exc:
        fail(f"配置文件 {path} 不是合法 JSON：{exc}",
             "用 configure.py 重新生成，或手工修正该文件。")
    if not isinstance(raw, dict):
        fail(f"配置文件 {path} 的顶层必须是 JSON 对象。")
    return {str(k): _clean(v) for k, v in raw.items() if v is not None}


def normalize_base_url(base: str) -> str:
    base = base.strip().rstrip("/")
    if not base:
        return base
    if not base.startswith(("http://", "https://")):
        base = "https://" + base
    # 中转站地址常被漏写 /v1；这里补齐，避免 404
    tail = urllib.parse.urlparse(base).path.rstrip("/")
    if not re.search(r"/v\d+(?:beta)?$", tail):
        base = base + "/v1"
    return base


def load_config(explicit: Path | None) -> dict[str, str]:
    file_values: dict[str, str] = {}
    used_file: Path | None = None
    if explicit:
        if not explicit.is_file():
            fail(f"指定的配置文件不存在：{explicit}")
        file_values = read_config_file(explicit)
        used_file = explicit
    else:
        for candidate in CONFIG_CANDIDATES:
            if candidate.is_file():
                file_values = read_config_file(candidate)
                used_file = candidate
                break

    resolved: dict[str, str] = {}
    for field, names in ALIASES.items():
        for name in names:
            env_value = _clean(os.environ.get(name, ""))
            if env_value:
                resolved[field] = env_value
                break
        else:
            for name in (field, *names):
                if _clean(file_values.get(name, "")):
                    resolved[field] = _clean(file_values[name])
                    break

    resolved.setdefault("base_url", DEFAULT_BASE_URL)
    resolved.setdefault("model", DEFAULT_MODEL)
    resolved["base_url"] = normalize_base_url(resolved["base_url"])
    resolved["_config_file"] = str(used_file) if used_file else ""

    if not resolved.get("api_key"):
        fail(
            "没有找到 API key。",
            "运行一次 `python3 " + str(SKILL_DIR / "scripts" / "configure.py")
            + "` 完成配置，或在 shell 里 export OPENAI_API_KEY 和 OPENAI_BASE_URL。",
        )
    _SECRETS.append(resolved["api_key"])
    return resolved


# ── HTTP ─────────────────────────────────────────────────────

RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504, 520, 522, 524}

# 有些中转站把「模型不存在 / 无可用渠道」也返回成 5xx。这类错误重试没有意义，
# 靠响应体特征识别出来后立即停止，并给出针对性提示。
NO_RETRY_PATTERNS = re.compile(
    r"model_not_found|无可用渠道|no available channel|model not found|"
    r"invalid_api_key|invalid token|insufficient|quota|余额",
    re.IGNORECASE,
)


def http_json(
    url: str,
    api_key: str,
    payload: dict[str, Any] | None = None,
    method: str = "POST",
    timeout: int = DEFAULT_TIMEOUT,
    attempts: int = 3,
) -> tuple[dict[str, Any], int]:
    """发一个 JSON 请求，返回 (解析后的对象, HTTP 状态码)。失败直接退出。"""
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "User-Agent": UA,
    }
    if body is not None:
        headers["Content-Type"] = "application/json"

    last_detail = ""
    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
                status = response.status
            break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            last_detail = detail[:1200]
            retriable = exc.code in RETRY_STATUS and not NO_RETRY_PATTERNS.search(last_detail)
            if retriable and attempt < attempts:
                wait = min(2 ** attempt, 8)
                info(f"HTTP {exc.code}，{wait}s 后重试（{attempt}/{attempts - 1}）")
                time.sleep(wait)
                continue
            _fail_http(exc.code, last_detail, url)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_detail = str(exc)
            if attempt < attempts:
                wait = min(2 ** attempt, 8)
                info(f"连接失败（{exc}），{wait}s 后重试")
                time.sleep(wait)
                continue
            fail(
                f"无法连接中转 API：{last_detail}",
                f"确认能访问 {url}，以及网络 / 代理设置是否正常。",
            )
    else:  # pragma: no cover - 循环必然 break 或 fail
        fail(f"请求失败：{last_detail}")

    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        fail(
            f"中转 API 返回的不是 JSON（HTTP {status}）：{raw[:300]!r}",
            "地址可能少了 /v1，或者中转站返回了 HTML 错误页。",
        )
    if not isinstance(parsed, dict):
        fail(f"中转 API 返回格式不正确，顶层不是对象：{str(parsed)[:200]}")
    return parsed, status


def _fail_http(code: int, detail: str, url: str) -> None:
    # 先按响应体内容判断真实原因：中转站常常用「不那么对」的状态码来包装业务错误
    if re.search(r"model_not_found|无可用渠道|no available channel|model not found",
                 detail, re.IGNORECASE):
        fail(
            f"中转 API 返回 HTTP {code}：{detail}",
            "这个模型名在该中转站没有可用渠道。用 --list-models 查看真实开放的模型名，"
            "再用 configure.py 改成其中一个。",
        )
    if re.search(r"insufficient|quota|余额|balance", detail, re.IGNORECASE):
        fail(f"中转 API 返回 HTTP {code}：{detail}", "账户额度或余额不足，请到中转站充值后重试。")

    hints = {
        401: "API key 无效或已过期。注意：这是你的中转站 key，不是 OpenAI 官方 key。"
             "用 configure.py 重新配置。",
        403: "key 没有这个模型的权限，或来源 IP 被中转站限制了。",
        404: f"接口路径不存在：{url}。检查 base_url 是否应包含 /v1。",
        400: "请求参数被中转站拒绝。先确认模型名在该站真实存在（--list-models 可查）。",
        413: "参考图太大。先压缩图片再重试。",
        429: "触发限流，稍后再试。若持续出现，检查中转站账户额度。",
    }
    fail(f"中转 API 返回 HTTP {code}：{detail}", hints.get(code, ""))


def download(url: str, timeout: int = DEFAULT_TIMEOUT) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        fail(f"无法下载生成的图片：{exc}")
    return b""  # pragma: no cover


# ── 图片编解码 ────────────────────────────────────────────────


def encode_reference(path_text: str) -> str:
    path = Path(path_text).expanduser()
    if not path.is_file():
        fail(f"参考图片不存在：{path}")
    mime = IMAGE_MIME.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0]
    if mime not in set(IMAGE_MIME.values()):
        fail(f"不支持的参考图格式：{path.suffix or '未知'}",
             "支持 png / jpg / jpeg / webp / gif。")
    data = path.read_bytes()
    if not data:
        fail(f"参考图片是空文件：{path}")
    size_mb = len(data) / 1_048_576
    if size_mb > 20:
        info(f"参考图 {path.name} 有 {size_mb:.1f}MB，部分中转站会拒收，建议压缩。")
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def decode_data_uri(value: str) -> bytes | None:
    if not value.startswith("data:") or "," not in value:
        return None
    header, encoded = value.split(",", 1)
    if ";base64" not in header:
        return None
    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        fail(f"无法解码返回的 data URL 图片：{exc}")
    return None  # pragma: no cover


def sniff_extension(data: bytes, fallback: str) -> str:
    for magic, ext in MAGIC:
        if data.startswith(magic):
            return ext
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return fallback


# ── 结果落盘 ─────────────────────────────────────────────────


def extract_items(result: dict[str, Any]) -> list[dict[str, Any]]:
    """从各种中转站响应结构里挖出图片条目。"""
    for key in ("data", "images", "output", "results"):
        value = result.get(key)
        if isinstance(value, list) and value:
            items: list[dict[str, Any]] = []
            for entry in value:
                if isinstance(entry, dict):
                    items.append(entry)
                elif isinstance(entry, str):
                    items.append({"url": entry} if entry.startswith("http") else {"b64_json": entry})
            if items:
                return items
    return []


def save_items(items: list[dict[str, Any]], output_dir: Path, fmt: str, prefix: str) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    saved: list[Path] = []

    for index, item in enumerate(items, 1):
        payload = item.get("b64_json") or item.get("b64") or item.get("image_base64")
        data: bytes | None = None
        if payload:
            text = str(payload)
            data = decode_data_uri(text)
            if data is None:
                try:
                    data = base64.b64decode(text.split(",", 1)[-1], validate=False)
                except (binascii.Error, ValueError) as exc:
                    fail(f"无法解码第 {index} 张图片的 base64 数据：{exc}")
        else:
            url = item.get("url") or item.get("image_url") or item.get("image")
            if isinstance(url, dict):
                url = url.get("url")
            if not url:
                fail(f"第 {index} 个返回条目既没有 b64_json 也没有 url："
                     f"{json.dumps(item, ensure_ascii=False)[:200]}")
            url = str(url)
            data = decode_data_uri(url) or download(url)

        if not data:
            fail(f"第 {index} 张图片内容为空。")

        extension = sniff_extension(data, fmt if fmt != "jpeg" else "jpg")
        target = output_dir / f"{prefix}-{stamp}-{index:02d}.{extension}"
        counter = 2
        while target.exists():
            target = output_dir / f"{prefix}-{stamp}-{index:02d}-{counter}.{extension}"
            counter += 1
        target.write_bytes(data)
        saved.append(target)

    return saved


# ── 异步中转站轮询 ─────────────────────────────────────────────

DONE_STATES = {"succeeded", "success", "completed", "complete", "finished", "done", "ok"}
FAILED_STATES = {"failed", "error", "cancelled", "canceled", "rejected"}


def find_task_id(result: dict[str, Any]) -> str | None:
    for key in ("task_id", "taskId", "request_id", "job_id", "id"):
        value = result.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def poll_async(base: str, api_key: str, task_id: str, timeout: int, interval: int = 3) -> dict[str, Any]:
    """中转站返回任务 ID 时轮询结果。不同站点路径不一，逐个试。"""
    paths = [
        f"{base}/images/generations/{task_id}",
        f"{base}/images/{task_id}",
        f"{base}/tasks/{task_id}",
        f"{base}/task/{task_id}",
    ]
    info(f"中转站返回异步任务 {task_id}，开始轮询结果...")
    deadline = time.time() + timeout
    working: str | None = None

    while time.time() < deadline:
        for path in ([working] if working else paths):
            try:
                result, _ = http_json(path, api_key, method="GET", timeout=60, attempts=1)
            except SystemExit:
                continue
            working = path
            status = str(result.get("status") or result.get("state") or "").lower()
            if extract_items(result):
                return result
            if status in FAILED_STATES:
                reason = result.get("error") or result.get("message") or result
                fail(f"中转站任务失败：{json.dumps(reason, ensure_ascii=False)[:300]}")
            if status in DONE_STATES and not extract_items(result):
                fail(f"任务标记完成但没有图片数据：{json.dumps(result, ensure_ascii=False)[:300]}")
            break
        else:
            fail(f"无法查询任务状态 {task_id}",
                 "该中转站的异步查询路径不在已知列表内，请提交 issue 补充。")
        time.sleep(interval)

    fail(f"等待任务 {task_id} 超时（{timeout}s）。")
    return {}  # pragma: no cover


# ── 请求体构造 ────────────────────────────────────────────────


def build_payload(model: str, prompt: str, args: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {"model": model, "prompt": prompt}
    if args.n and args.n > 1:
        payload["n"] = args.n
    else:
        payload["n"] = 1
    if args.size and args.size != "auto":
        payload["size"] = args.size
    if args.quality:
        payload["quality"] = args.quality
    if args.background:
        payload["background"] = args.background
    if args.output_format:
        payload["output_format"] = args.output_format
    for item in args.extra or []:
        if "=" not in item:
            fail(f"--extra 需要 key=value 形式：{item}")
        key, value = item.split("=", 1)
        try:
            payload[key.strip()] = json.loads(value)
        except json.JSONDecodeError:
            payload[key.strip()] = value
    return payload


def edit_shapes(references: list[str]) -> list[tuple[str, dict[str, Any]]]:
    """不同中转站对参考图的字段要求不同，按可能性排序依次尝试。"""
    return [
        ("images[{image_url}]", {"images": [{"image_url": ref} for ref in references]}),
        ("image_urls[]", {"image_urls": references}),
        ("images[]", {"images": references}),
        ("image", {"image": references[0]}),
    ]


MISSING_PARAM = re.compile(
    r"missing required parameter|unknown parameter|invalid.*parameter|unrecognized|"
    r"not supported|invalid_request_error",
    re.IGNORECASE,
)


def call_with_shape_fallback(
    base: str, api_key: str, payload: dict[str, Any], references: list[str], timeout: int
) -> dict[str, Any]:
    """有参考图时，在 /images/edits 上尝试多种请求体形状，再退回 /images/generations。"""
    attempts: list[tuple[str, str, dict[str, Any]]] = []
    for label, extra in edit_shapes(references):
        attempts.append((f"{base}/images/edits", f"edits {label}", {**payload, **extra}))
    for label, extra in edit_shapes(references):
        if label in {"image_urls[]", "images[{image_url}]"}:
            attempts.append((f"{base}/images/generations", f"generations {label}", {**payload, **extra}))

    last_error = ""
    for url, label, body in attempts:
        info(f"尝试 {label} ...")
        try:
            result, _ = http_json(url, api_key, body, timeout=timeout, attempts=2)
        except SystemExit as exc:
            last_error = str(exc)
            continue
        if extract_items(result) or find_task_id(result):
            return result
        last_error = json.dumps(result, ensure_ascii=False)[:300]

    fail(
        "所有参考图请求形状都被中转站拒绝了。",
        f"最后一次返回：{last_error}。该站可能不支持图生图，可先只用文字描述生成。",
    )
    return {}  # pragma: no cover


# ── 子命令 ───────────────────────────────────────────────────


def cmd_doctor(config: dict[str, str], timeout: int) -> None:
    print("relay-imagegen 自检")
    print(f"  版本      : {VERSION}")
    print(f"  Python    : {sys.version.split()[0]}")
    print(f"  配置文件  : {config['_config_file'] or '（未使用，来自环境变量）'}")
    print(f"  base_url  : {config['base_url']}")
    print(f"  model     : {config['model']}")
    key = config["api_key"]
    print(f"  api_key   : {key[:6]}***{key[-4:]}（长度 {len(key)}）")

    print("\n[1/2] 拉取模型列表 ...")
    try:
        result, _ = http_json(f"{config['base_url']}/models", key, method="GET",
                              timeout=30, attempts=1)
        models = [m.get("id") for m in result.get("data", []) if isinstance(m, dict)]
        image_models = [m for m in models if m and re.search(
            r"image|dall|flux|banana|seedream|qwen-image|kolors|sd\d|midjourney", m, re.I)]
        print(f"      可用模型 {len(models)} 个；图片类：{', '.join(image_models) or '未识别到'}")
        if image_models and config["model"] not in models:
            print(f"      ⚠️  当前配置的 {config['model']} 不在列表里，"
                  f"建议改成上面其中一个。")
    except SystemExit:
        print("      ⚠️  /models 查询失败（部分中转站不开放该接口，不影响生图）")

    print("\n[2/2] 试生成一张小图 ...")
    payload = {"model": config["model"], "prompt": "a plain solid red circle on white background",
               "n": 1, "size": "1024x1024"}
    result, _ = http_json(f"{config['base_url']}/images/generations", key,
                          payload, timeout=timeout)
    task_id = None if extract_items(result) else find_task_id(result)
    if task_id:
        result = poll_async(config["base_url"], key, task_id, timeout)
    items = extract_items(result)
    if not items:
        fail(f"接口通了但没有返回图片：{json.dumps(result, ensure_ascii=False)[:300]}")
    paths = save_items(items, Path("/tmp/relay-imagegen-doctor"), "png", "doctor")
    print(f"      ✅ 成功，样例图片：{paths[0]}")
    print("\n自检通过，可以正常生图。")


def cmd_list_models(config: dict[str, str]) -> None:
    result, _ = http_json(f"{config['base_url']}/models", config["api_key"],
                          method="GET", timeout=30, attempts=1)
    models = sorted(m.get("id", "") for m in result.get("data", []) if isinstance(m, dict))
    if not models:
        fail("中转站没有返回模型列表。")
    for name in models:
        marker = "  <- 当前配置" if name == config["model"] else ""
        print(f"{name}{marker}")


def cmd_generate(config: dict[str, str], args: argparse.Namespace) -> None:
    if args.prompt:
        prompt = args.prompt.strip()
    else:
        try:
            prompt = Path(args.prompt_file).expanduser().read_text(encoding="utf-8").strip()
        except OSError as exc:
            fail(f"无法读取 prompt 文件：{exc}")
    if not prompt:
        fail("prompt 不能为空。")

    base = config["base_url"]
    payload = build_payload(config["model"], prompt, args)
    references = [encode_reference(p) for p in (args.image or [])]

    if references:
        info(f"{len(references)} 张参考图，走图生图流程（model={config['model']}）")
        result = call_with_shape_fallback(base, config["api_key"], payload,
                                         references, args.timeout)
    else:
        info(f"调用 {base}/images/generations（model={config['model']}, size={args.size}）")
        result, _ = http_json(f"{base}/images/generations", config["api_key"],
                              payload, timeout=args.timeout)

    if not extract_items(result):
        task_id = find_task_id(result)
        if task_id:
            result = poll_async(base, config["api_key"], task_id, args.timeout)

    items = extract_items(result)
    if not items:
        fail(
            f"中转站没有返回图片数据：{json.dumps(result, ensure_ascii=False)[:400]}",
            "确认该模型在这个站点确实支持图片生成。",
        )

    paths = save_items(items, Path(args.output_dir).expanduser(),
                       args.output_format or "png", args.prefix)
    for path in paths:
        print(path.resolve())


# ── 入口 ─────────────────────────────────────────────────────


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="relay_imagegen.py",
        description="通过 OpenAI 兼容中转 API 生成或修改图片（纯标准库实现）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例：
  # 文生图
  %(prog)s --prompt "一只橘猫坐在窗台看夕阳，水彩风格" --size 1024x1024

  # 图生图 / 改图（可多张参考图）
  %(prog)s --prompt "把背景换成浅蓝影棚，保留产品外观" --image product.png

  # 自检：验证 key、地址、模型是否可用
  %(prog)s --doctor

  # 查看中转站真实开放的模型
  %(prog)s --list-models
""",
    )
    parser.add_argument("--prompt", help="图片描述")
    parser.add_argument("--prompt-file", help="从文本文件读取长 prompt")
    parser.add_argument("--image", action="append", metavar="PATH",
                        help="参考图路径，可重复传入多张")
    parser.add_argument("--size", default="1024x1024",
                        help="尺寸，如 1024x1024 / 1536x1024 / 1024x1536 / 16:9 / auto")
    parser.add_argument("--quality", choices=("low", "medium", "high", "auto"),
                        help="质量档位（部分中转站会忽略）")
    parser.add_argument("--background", choices=("transparent", "opaque", "auto"),
                        help="背景，transparent 用于透明底")
    parser.add_argument("--n", type=int, default=1, choices=range(1, 11), metavar="1-10",
                        help="生成数量，默认 1")
    parser.add_argument("--output-dir", default="generated-images", help="输出目录")
    parser.add_argument("--output-format", choices=("png", "jpeg", "webp"), default="png",
                        help="期望格式；实际后缀按返回内容判断")
    parser.add_argument("--prefix", default="image", help="输出文件名前缀")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="单次请求超时秒数")
    parser.add_argument("--config", help="指定 config.json 路径")
    parser.add_argument("--extra", action="append", metavar="KEY=VALUE",
                        help="附加请求字段，如 --extra resolution=2k")
    parser.add_argument("--doctor", action="store_true", help="自检配置与连通性")
    parser.add_argument("--list-models", action="store_true", help="列出中转站可用模型")
    parser.add_argument("--version", action="version", version=f"relay-imagegen {VERSION}")

    args = parser.parse_args(argv)
    if not (args.doctor or args.list_models) and not (args.prompt or args.prompt_file):
        parser.error("需要 --prompt 或 --prompt-file（或使用 --doctor / --list-models）")
    return args


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    config = load_config(Path(args.config).expanduser() if args.config else None)
    if args.doctor:
        cmd_doctor(config, args.timeout)
    elif args.list_models:
        cmd_list_models(config)
    else:
        cmd_generate(config, args)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nrelay-imagegen: 已取消。", file=sys.stderr)
        raise SystemExit(130)
