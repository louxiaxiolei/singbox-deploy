#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 ]] || { echo "请使用 root"; exit 1; }
for c in curl python3 sing-box systemctl openssl; do command -v "$c" >/dev/null || { echo "缺少 $c"; exit 1; }; done
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
url="https://raw.githubusercontent.com/louxiaxiolei/singbox-deploy/1569b4911c48318e8b86b098bb718a03eea46987/relay-enhancement/landing_manager.py"
curl -fLSs --retry 2 --connect-timeout 10 --max-time 45 "$url" -o "$tmp/landing_manager.py"
python3 -m py_compile "$tmp/landing_manager.py"
echo "=== 新增独立落地节点：旧配置和旧服务不会被修改 ==="
python3 "$tmp/landing_manager.py"
