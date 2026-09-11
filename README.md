# relay-imagegen

让 Codex / Claude Code 用**中转 API** 画图的 skill。

Codex 自带的画图工具只认 OpenAI 官方账号，中转 API 用户调用会直接报 `invalid API key`。这个 skill 用一个本地 Python 脚本接管所有画图请求，走你自己的中转地址。

- 纯 Python 标准库，**不装任何依赖**，装一次永久可用
- 文生图 + 图生图（改图）
- 自带 `--doctor` 自检，一条命令定位问题
- 兼容各家中转站的响应格式差异，自动回退
- API key 存本地（权限 600），不进对话、不进日志

---

## 最省事的装法：让 Codex 自己装

不想碰命令行的话，**直接把下面这段话整段复制，发给 Codex**（或 Claude Code），它会自己装好并带你配置：

```text
帮我安装 relay-imagegen 这个画图 skill，仓库地址：
https://github.com/liwenxiang-bot/relay-imagegen

请依次做这几件事：
1. 运行仓库里的一键安装命令：
   curl -fsSL https://raw.githubusercontent.com/liwenxiang-bot/relay-imagegen/main/install.sh | bash
2. 装完告诉我配置向导的完整命令，我需要自己在终端里运行它来输入 API key
   （key 不能让你看到，所以这一步必须我自己做）
3. 我配置完成后，你帮我运行 --doctor 自检，确认能正常出图
4. 最后提醒我重启 Codex
```

> 第 2 步必须你自己在终端做 —— API key 属于隐私，不要贴进对话框。

装完重启 Codex，直接说「画一只猫」就行。

---

## 手动安装

### 第 1 步：安装

```bash
curl -fsSL https://raw.githubusercontent.com/liwenxiang-bot/relay-imagegen/main/install.sh | bash
```

脚本会自动检测你装的是 Codex 还是 Claude Code，放到对应目录。已有配置会自动保留。

### 第 2 步：填中转信息

```bash
python3 ~/.codex/skills/relay-imagegen/scripts/configure.py
```

按提示填三项：

| 问题 | 填什么 |
| --- | --- |
| 中转 API 地址 | 你的中转站地址，比如 `https://api.9e.lv/v1`。漏了 `/v1` 会自动补 |
| API key | 中转站给你的 key。**输入时不显示是正常的**，粘贴完直接回车 |
| 图片模型 | 直接回车用推荐值。向导会先拉一遍该站真实开放的模型给你看 |

### 第 3 步：自检

```bash
python3 ~/.codex/skills/relay-imagegen/scripts/relay_imagegen.py --doctor
```

看到这个就成了：

```
[2/2] 试生成一张小图 ...
      ✅ 成功，样例图片：/tmp/relay-imagegen-doctor/doctor-xxx.png

自检通过，可以正常生图。
```

### 第 4 步：重启 Codex

**必须重启**，否则新 skill 不会被加载。之后直接说人话：

```
画一只橘猫坐在窗台看夕阳，水彩风格
```

> Claude Code 用户把上面命令里的 `.codex` 换成 `.claude`。

---

## 用法

配置好之后正常提需求即可，不用带前缀：

```
画一张白色陶瓷咖啡杯的电商主图，纯白背景，柔和棚拍光线，正方形
把 ~/Desktop/product.png 的背景换成浅蓝影棚，保留产品外观和标签
生成 3 张不同风格的博客封面图，16:9
```

图片默认存到当前目录的 `generated-images/`。

如果模型没走这个 skill，显式点名：

```
用 relay-imagegen 画一只猫
```

---

## 手动跑脚本

```bash
SKILL=~/.codex/skills/relay-imagegen/scripts/relay_imagegen.py
```

文生图：

```bash
python3 "$SKILL" --prompt "一只橘猫坐在窗台看夕阳，水彩风格" --size 1024x1024
```

改图（`--image` 可重复传多张参考图）：

```bash
python3 "$SKILL" --prompt "背景换成浅蓝影棚，保留产品外观" --image product.png
```

### 参数

| 参数 | 说明 |
| --- | --- |
| `--prompt "..."` | 图片描述 |
| `--prompt-file f.txt` | 从文件读长 prompt |
| `--image PATH` | 参考图，可重复传多张 |
| `--size` | `1024x1024`（默认）、`1536x1024`、`1024x1536`、`16:9`、`auto` |
| `--n 1-10` | 同一 prompt 出几张，默认 1 |
| `--quality low\|medium\|high` | 质量档位 |
| `--background transparent` | 透明底 |
| `--output-dir DIR` | 输出目录，默认 `generated-images` |
| `--prefix NAME` | 文件名前缀 |
| `--output-format png\|jpeg\|webp` | 期望格式 |
| `--extra KEY=VALUE` | 附加字段，如 `--extra resolution=2k` |
| `--timeout 300` | 超时秒数 |
| `--doctor` | 自检 |
| `--list-models` | 列出中转站真实开放的模型 |

成功时脚本把图片绝对路径打到 stdout，进度和报错走 stderr，方便在管道里取路径。

---

## 环境变量方式

不想存配置文件的话直接 export（**优先级高于配置文件**）：

```bash
export OPENAI_API_KEY=sk-你的中转站key
export OPENAI_BASE_URL=https://your-relay.com/v1
export OPENAI_IMAGE_MODEL=gpt-image-2
```

写进 `~/.zshrc` 或 `~/.bashrc` 可永久生效。也支持 `RELAY_IMAGE_*` 和 `IMG_*` 前缀别名，避免和其他工具抢变量。

---

## 出问题了看这里

**先跑 `--doctor`**，它会逐项检查配置、模型列表、实际出图，大部分问题一眼定位。

### 模型还是去调内置画图，报"无效 API key"

最常见的情况，两个原因：

1. **没重启** Codex —— 新 skill 要重启才加载
2. 模型自己判断走了内置通道 —— 在请求里显式写 `用 relay-imagegen 画...`

确认 skill 装对了：

```bash
ls ~/.codex/skills/relay-imagegen/SKILL.md
```

### 401 / Invalid token

中转站 key 填错或已过期。注意这是**你中转站的 key**，不是 OpenAI 官方 key。重跑 `configure.py`。

### 404

地址少了 `/v1`。脚本会自动补，但如果你的中转站路径特殊（带额外前缀），需要手填完整地址。

### model_not_found / 无可用渠道

模型名在该站不存在。查真实名称：

```bash
python3 ~/.codex/skills/relay-imagegen/scripts/relay_imagegen.py --list-models
```

再重跑 `configure.py` 改成列表里的名字。

### 出图很慢

正常。中转转发 + 模型生成，一张图 15～30 秒是常态。要更久可以加 `--timeout 600`。

### 图生图失败

有些中转站只支持文生图。脚本会自动试 4 种参考图请求结构再放弃 —— 如果全失败，基本是该站没开图生图，先用纯文字描述生成。

### 尺寸 / 质量参数好像没生效

很多中转站是反向代理，会把 `size`、`quality` 归一化成自己的档位。这是中转站行为，不是脚本问题。

---

## 卸载

```bash
rm -rf ~/.codex/skills/relay-imagegen
```

---

## 目录结构

```
skill/
├── SKILL.md                  # skill 定义，决定模型何时调用
├── config.json               # 你的配置（安装后生成，不进 git）
├── agents/openai.yaml        # Codex 界面元信息
└── scripts/
    ├── relay_imagegen.py     # 生图主脚本
    └── configure.py          # 配置向导
```

## 给中转站站长

这个 skill 可以直接分发给你的用户。把 `configure.py` 和 `relay_imagegen.py` 里的 `DEFAULT_BASE_URL`、`DEFAULT_MODEL` 改成你站的地址和模型，用户装完一路回车就能用，只需要填一个 key。

## 安全

- key 只存本地 `config.json`，权限 `600`
- 输入 key 时不回显
- 所有报错输出会把 `sk-` 开头的字符串打码，不会因为贴日志泄漏
- `.gitignore` 已排除 `config.json` 和 `.env`

## License

MIT
