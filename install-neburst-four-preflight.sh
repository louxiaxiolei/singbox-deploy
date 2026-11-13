#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
[[ "$EUID" == 0 ]] || { echo '需要 root'; exit 1; }
command -v python3 >/dev/null || { echo '缺少 python3'; exit 1; }
command -v curl >/dev/null || { echo '缺少 curl'; exit 1; }
url='https://raw.githubusercontent.com/louxiaxiolei/singbox-deploy/376e0c4da3e6b92ea8c39b4d11e8610f9db403a4/relay-enhancement/neburst_four_prepare.py'
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
curl -fLSs --retry 2 --connect-timeout 10 --max-time 45 "$url" -o "$tmp/prepare.py"
python3 -m py_compile "$tmp/prepare.py"
python3 "$tmp/prepare.py"
