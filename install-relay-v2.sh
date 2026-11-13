#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 ]] || { echo "需要 root"; exit 1; }
for c in curl python3 sing-box; do command -v "$c" >/dev/null || { echo "缺少 $c"; exit 1; }; done
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
base="https://raw.githubusercontent.com/louxiaxiolei/singbox-deploy/eb330199824b3e534bbed41fed0d637f737135e6"
curl -fLSs --retry 2 --connect-timeout 10 --max-time 45 "$base/relay-enhancement/relay_manager.py" -o "$tmp/relay_manager.py"
curl -fLSs --retry 2 --connect-timeout 10 --max-time 45 "$base/relay-enhancement/install_relay.py" -o "$tmp/install_relay.py"
python3 -m py_compile "$tmp/relay_manager.py" "$tmp/install_relay.py"
cd "$tmp"
python3 install_relay.py
echo "请执行 relay-manager 进入中转菜单。"
