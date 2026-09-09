---
name: relay-imagegen
description: Generate or edit images through a user-configured OpenAI-compatible relay API. Use this for all image generation and image editing requests when the user uses OPENAI_BASE_URL, a proxy, or a non-OpenAI account; use the bundled local script instead of Codex's cloud imagegen.
---

# Relay Image Generator

Use the persistent `scripts/generate_image.py` helper for actual image generation. Do not call the built-in cloud `imagegen` tool for this skill: the purpose is to send the request to the user's configured relay URL.

The skill supports ordinary text-to-image requests and image edits. Keep prompts concise and concrete: subject, setting, composition, lighting, style, aspect ratio, and any text or exclusions the user requests. If the user asks only for a prompt, return the prompt without running the script.

## One-time setup for beginners

If the user has not configured the API, guide them to run this once from the skill directory:

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/relay-imagegen/scripts/configure.py"
```

The setup asks for the relay URL, image model, and API key in the terminal; the key is hidden while typing and is saved locally with restrictive permissions. It is never sent to chat or printed. The defaults are `https://api.9e.lv/v1` and `gpt-image-2`; if a user enters `https://api.9e.lv/`, the setup normalizes it to `/v1`.

Advanced users can instead export:

```bash
export OPENAI_API_KEY=sk-xxxxxx
export OPENAI_BASE_URL=https://proxy.example.com/v1
export OPENAI_IMAGE_MODEL=gpt-image-2
```

Environment variables override the local setup. The script also accepts `IMG_API_KEY`, `IMG_BASE_URL`, and `IMG_MODEL`. Never ask the user to paste a real key into the conversation, and never echo it in logs or responses.

## Generate

Use the installed skill path so the command works from any workspace:

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/relay-imagegen/scripts/generate_image.py" \
  --prompt "A clean editorial product photo of ..." \
  --size 1024x1024 \
  --output-dir generated-images
```

For a reference image:

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/relay-imagegen/scripts/generate_image.py" \
  --prompt "Preserve the product shape and label; place it in ..." \
  --image /path/to/reference.png \
  --size 1024x1536
```

Use `--prompt-file` for a long prompt, `--quality low|medium|high` when the relay supports it, `--n 1..4` for multiple images, and `--format png|jpeg|webp` for the saved extension. The script writes generated files locally and prints only their paths on stdout; progress and errors go to stderr.

The helper uses only Python's standard library, so it is installed once with the skill and does not run `pip install` on each request. Without `--image`, it POSTs JSON to `{OPENAI_BASE_URL}/images/generations`. With `--image`, it POSTs JSON to `{OPENAI_BASE_URL}/images/edits` using the standard GPT Image `images: [{image_url: ...}]` input shape. Both calls send `Authorization: Bearer ...`, accept `b64_json` or `url` response items, and save the result locally. The relay must expose these OpenAI-compatible Images endpoints.

When the script succeeds, show the resulting local image(s) to the user when the interface supports it and include the absolute file paths. If configuration is missing, stop before any API call and give the one-time `configure.py` command.
