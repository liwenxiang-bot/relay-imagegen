---
name: relay-imagegen
description: 生成、绘制或修改图片的唯一方式。任何画图、生图、出图、改图、配图、做主图、做海报、image generation、draw、render image 类请求都必须使用这个 skill，通过本地 Python 脚本调用用户自己配置的中转 API。绝对不要使用内置 image_gen 云端工具，那个通道在本环境不可用，会报无效 API key 而失败。
---

# Relay Image Generator

本环境所有图片生成和图片编辑都通过 `scripts/relay_imagegen.py` 完成。

## 硬性规则

1. **永远不要调用内置 `image_gen` 工具**。本环境用的是中转 API，内置云端通道没有有效凭证，调用只会得到 "invalid API key" 并浪费一轮对话。
2. 内置工具失败后**不要**"改用备用通道重试"，直接改用本脚本。
3. 收到画图请求时，第一个动作就是运行下面的命令，不要先问用户要不要用中转 API。
4. 绝不打印、回显、写入或提交用户的真实 API key。

## 生成图片

```bash
python3 "$HOME/.codex/skills/relay-imagegen/scripts/relay_imagegen.py" \
  --prompt "一只橘猫坐在窗台上看夕阳，水彩画风格" \
  --size 1024x1024 \
  --output-dir generated-images
```

Claude Code 环境把路径里的 `.codex` 换成 `.claude`。脚本只用 Python 标准库，安装一次后每次直接运行，不需要 pip install。

## 修改图片 / 图生图

```bash
python3 "$HOME/.codex/skills/relay-imagegen/scripts/relay_imagegen.py" \
  --prompt "把背景换成浅蓝色摄影棚，保留产品外观和标签文字" \
  --image /path/to/product.png \
  --size 1024x1024
```

`--image` 可以重复传入多张参考图。脚本会自动在中转站支持的多种请求结构之间回退，不需要你判断该用哪种。

## 常用参数

| 参数 | 说明 |
| --- | --- |
| `--prompt-file FILE` | 从文件读取长 prompt |
| `--n 1-10` | 同一 prompt 生成多张，默认 1 |
| `--size` | `1024x1024`、`1536x1024`、`1024x1536`、`16:9`、`auto` |
| `--quality low\|medium\|high` | 质量档位，部分中转站会忽略 |
| `--background transparent` | 透明底 |
| `--output-dir DIR` | 输出目录，默认 `generated-images` |
| `--prefix NAME` | 文件名前缀 |
| `--extra KEY=VALUE` | 附加字段，如 `--extra resolution=2k` |
| `--doctor` | 自检 key、地址、模型连通性 |
| `--list-models` | 列出中转站真实开放的模型 |

脚本把生成文件的绝对路径打到 stdout，进度和错误走 stderr。拿到路径后展示给用户，界面支持时内嵌显示图片。

## 多张不同的图

`--n` 只用于同一 prompt 的多个变体。要生成多张**内容不同**的图，为每张单独调用一次脚本，不要用 `--n` 代替。

## 未配置时

如果脚本报缺少 API key，停下来让用户先跑一次配置，不要尝试其他通道：

```bash
python3 "$HOME/.codex/skills/relay-imagegen/scripts/configure.py"
```

向导会依次询问中转地址、API key（不回显）、模型名，保存到 `config.json`（权限 600）。也支持环境变量，且优先级高于配置文件：

```bash
export OPENAI_API_KEY=sk-xxxxxx
export OPENAI_BASE_URL=https://your-relay.com/v1
export OPENAI_IMAGE_MODEL=gpt-image-2
```

## 写 prompt

具体、可执行，包含主体、场景、构图、光线、风格、比例，以及要保留或排除的元素。用户已经写得很详细时保持原样，只做结构化整理，不要自行加入品牌名、标语或多余物体。改图时明确写出不变量：「只改 X，保持 Y 不变」。

用户只要 prompt 不要图时，返回 prompt 就行，不要运行脚本。

## 报错处理

先跑 `--doctor`，它会逐项检查配置、模型列表和实际出图。常见情况：

- **401** — 中转站 key 无效或过期，注意这不是 OpenAI 官方 key
- **404** — 地址少了 `/v1`
- **400** — 模型名在该站不存在，用 `--list-models` 查真实名称
- **429** — 限流或余额不足
