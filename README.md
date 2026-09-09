# relay-imagegen

通过 OpenAI 兼容中转 API 生成和修改图片的 Codex skill。

- 默认中转地址：`https://api.9e.lv/v1`
- 默认模型：`gpt-image-2`
- 无参考图调用 `/images/generations`
- 有参考图调用 `/images/edits`
- 纯 Python 标准库，无需每次安装依赖

使用方法见 [outputs/relay-imagegen/README.md](outputs/relay-imagegen/README.md)。
