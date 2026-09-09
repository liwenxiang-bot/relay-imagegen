# Relay Image Generator 使用说明

这个 skill 通过你配置的 OpenAI 兼容中转 API 生成和修改图片，默认中转地址为 `https://api.9e.lv/v1`，默认模型为 `gpt-image-2`。

## 第一次使用

在终端运行一次：

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/relay-imagegen/scripts/configure.py"
```

按提示输入：

1. 中转地址：直接回车使用 `https://api.9e.lv/v1`
2. 图片模型：直接回车使用 `gpt-image-2`
3. API key：输入时不会显示

配置保存在本机 `~/.codex/skills/relay-imagegen/config.json`，权限为仅当前用户可读写。API key 不会发送到聊天内容，也不会出现在脚本日志中。

## 生成图片

配置完成后，在 Codex 中直接描述需求即可，例如：

```text
生成一张白色陶瓷咖啡杯的电商主图，纯白背景，柔和棚拍光线，正方形
```

也可以显式调用：

```text
$relay-imagegen 生成一张赛博朋克城市夜景图，16:9，电影感
```

图片会保存到当前工作目录的 `generated-images/` 文件夹。

## 修改图片

在 Codex 中提供本地图片路径并描述修改内容：

```text
$relay-imagegen 修改 /Users/me/product.png，把背景换成浅蓝色摄影棚，保留产品外观和标签
```

有参考图时，脚本调用 `/v1/images/edits`；没有参考图时调用 `/v1/images/generations`。参考图使用官方 Images API 的 `images[].image_url` 数据结构。

## 手动运行脚本

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/relay-imagegen/scripts/generate_image.py" \
  --prompt "A clean editorial product photo of a ceramic mug" \
  --size 1024x1024 \
  --output-dir generated-images
```

修改图片时加上 `--image`：

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/relay-imagegen/scripts/generate_image.py" \
  --prompt "Replace the background with a soft blue studio backdrop" \
  --image /Users/me/product.png \
  --size 1024x1024
```

常用参数：

- `--prompt-file prompt.txt`：从文件读取长提示词
- `--size 1024x1024`、`1536x1024`、`1024x1536`：图片尺寸
- `--quality low|medium|high`：图片质量
- `--n 1` 到 `4`：生成数量
- `--format png|jpeg|webp`：保存格式
- `--output-dir path`：输出目录

## 环境变量方式

熟悉终端的用户也可以使用环境变量：

```bash
export OPENAI_API_KEY=sk-xxxxxx
export OPENAI_BASE_URL=https://api.9e.lv/v1
export OPENAI_IMAGE_MODEL=gpt-image-2
```

环境变量优先于本地配置文件。

## 常见问题

### 401 或 403

检查 API key 是否正确，且没有多余空格。

### 404

检查中转地址是否包含 `/v1`，脚本最终会访问：

```text
https://api.9e.lv/v1/images/generations
https://api.9e.lv/v1/images/edits
```

### 400 或提示模型不存在

确认中转站实际开放的模型名称。如果站点使用其他名称，可以重新运行配置脚本并填写实际模型名。

### Codex 没有自动使用这个 skill

在请求开头显式写 `$relay-imagegen`，或重启 Codex 让新 skill 重新加载。

脚本只使用 Python 标准库，不会在每次生成图片时安装依赖。
