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
curl -fLsS --retry 2 --connect-timeout 10 --max-time 40 "$base/relay-enhancement/landing_audit.py" -o "$tmp/landing_audit.py"
python3 -m py_compile "$tmp/relay_manager.py" "$tmp/install_relay.py" "$tmp/landing_audit.py"
cd "$tmp"
if [[ ! -f /usr/local/lib/singbox-deploy/install.sh ]]; then
  echo "未检测到本项目 LM；进入落地机只读检查模式，不安装、不修改服务。"
  python3 landing_audit.py
  exit 0
fi
python3 install_relay.py
echo '安装结束。执行 LM 进入中转管理。'
