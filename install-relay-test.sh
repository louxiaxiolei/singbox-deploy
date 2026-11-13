#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
[[ "$(id -u)" == 0 ]] || { echo '请用 root 运行'; exit 1; }
command -v python3 >/dev/null || { echo '需要 python3'; exit 1; }
command -v curl >/dev/null || { echo '需要 curl'; exit 1; }
base='https://raw.githubusercontent.com/louxiaxiolei/singbox-deploy/feature/relay-five-protocols-test'
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
curl -fLsS --retry 2 --connect-timeout 10 --max-time 40 "$base/relay-enhancement/relay_manager.py" -o "$tmp/relay_manager.py"
curl -fLsS --retry 2 --connect-timeout 10 --max-time 40 "$base/relay-enhancement/install_relay.py" -o "$tmp/install_relay.py"
python3 -m py_compile "$tmp/relay_manager.py" "$tmp/install_relay.py"
cd "$tmp"
python3 install_relay.py
echo '安装结束。执行 LM 进入中转管理。'
