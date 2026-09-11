#!/usr/bin/env bash
# relay-imagegen 一键安装脚本
#
#   curl -fsSL https://raw.githubusercontent.com/liwenxiang-bot/relay-imagegen/main/install.sh | bash
#
# 可选环境变量：
#   TARGET=codex|claude|both   指定安装目标，默认自动检测
#   REPO_REF=main              指定分支
set -euo pipefail

REPO_URL="https://github.com/liwenxiang-bot/relay-imagegen.git"
REPO_REF="${REPO_REF:-main}"
SKILL_NAME="relay-imagegen"

info()  { printf '\033[36m==>\033[0m %s\n' "$1"; }
ok()    { printf '\033[32m ✓\033[0m %s\n' "$1"; }
warn()  { printf '\033[33m ！\033[0m %s\n' "$1"; }
die()   { printf '\033[31m ✗ %s\033[0m\n' "$1" >&2; exit 1; }

command -v git >/dev/null 2>&1 || die "需要 git，请先安装。"

PYTHON=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
      PYTHON="$candidate"; break
    fi
  fi
done
[ -n "$PYTHON" ] || die "需要 Python 3.9 或更高版本。"
ok "Python: $($PYTHON --version 2>&1)"

CODEX_DIR="${CODEX_HOME:-$HOME/.codex}"
CLAUDE_DIR="${CLAUDE_HOME:-$HOME/.claude}"

TARGETS=()
case "${TARGET:-auto}" in
  codex)  TARGETS=("$CODEX_DIR") ;;
  claude) TARGETS=("$CLAUDE_DIR") ;;
  both)   TARGETS=("$CODEX_DIR" "$CLAUDE_DIR") ;;
  auto)
    [ -d "$CODEX_DIR" ]  && TARGETS+=("$CODEX_DIR")
    [ -d "$CLAUDE_DIR" ] && TARGETS+=("$CLAUDE_DIR")
    if [ ${#TARGETS[@]} -eq 0 ]; then
      warn "没检测到 ~/.codex 或 ~/.claude，默认装到 $CODEX_DIR"
      TARGETS=("$CODEX_DIR")
    fi
    ;;
  *) die "TARGET 只能是 codex / claude / both" ;;
esac

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
info "下载 $SKILL_NAME ($REPO_REF) ..."
git clone -q --depth 1 --branch "$REPO_REF" "$REPO_URL" "$TMP_DIR/repo" \
  || die "下载失败，检查网络或仓库地址。"
[ -f "$TMP_DIR/repo/skill/SKILL.md" ] || die "仓库结构异常：缺少 skill/SKILL.md"

for home in "${TARGETS[@]}"; do
  dest="$home/skills/$SKILL_NAME"
  info "安装到 $dest"
  mkdir -p "$dest"

  # 保住已有配置，只覆盖代码和文档
  if [ -f "$dest/config.json" ]; then
    cp "$dest/config.json" "$TMP_DIR/config.json.keep"
    ok "已保留现有 config.json"
  fi

  rm -rf "$dest/scripts" "$dest/agents" "$dest/references"
  cp -R "$TMP_DIR/repo/skill/." "$dest/"
  chmod +x "$dest/scripts/"*.py 2>/dev/null || true

  if [ -f "$TMP_DIR/config.json.keep" ]; then
    cp "$TMP_DIR/config.json.keep" "$dest/config.json"
    chmod 600 "$dest/config.json"
    rm -f "$TMP_DIR/config.json.keep"
  fi
  ok "已安装：$dest"
done

PRIMARY="${TARGETS[0]}/skills/$SKILL_NAME"

echo
if [ -f "$PRIMARY/config.json" ]; then
  ok "检测到已有配置，直接自检："
  echo
  echo "    $PYTHON \"$PRIMARY/scripts/relay_imagegen.py\" --doctor"
else
  info "还剩一步：配置你的中转 API"
  echo
  echo "    $PYTHON \"$PRIMARY/scripts/configure.py\""
  echo
  echo "  配置完成后自检："
  echo
  echo "    $PYTHON \"$PRIMARY/scripts/relay_imagegen.py\" --doctor"
fi
echo
info "自检通过后，重启 Codex / Claude Code，直接说「画一只猫」即可。"
