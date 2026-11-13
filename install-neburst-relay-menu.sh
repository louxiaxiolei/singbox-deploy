#!/usr/bin/env bash
# Neburst third-party sing-box four inbound persistent relay menu.
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 ]] || { echo "请用 root 执行"; exit 1; }
for c in curl python3 sing-box systemctl; do command -v "$c" >/dev/null || { echo "缺少 $c"; exit 1; }; done
SCRIPT=/root/neburst-persistent-switch.py
CANDIDATE=/root/neburst-relay-preflight/config.candidate-20261113T160005Z.json
URL='https://raw.githubusercontent.com/louxiaxiolei/singbox-deploy/a32b93d594b16285a14c827e92abaa115b12ef12/relay-enhancement/neburst_persistent_switch.py'
if [[ ! -f "$SCRIPT" ]]; then
  echo '首次安装长期中转管理脚本（不会修改 sing-box 配置）'
  tmp=$(mktemp)
  trap 'rm -f "$tmp"' EXIT
  curl -fLSs --retry 2 --connect-timeout 10 --max-time 45 "$URL" -o "$tmp"
  python3 -m py_compile "$tmp"
  install -m 700 "$tmp" "$SCRIPT"
fi
while true; do
  echo
  echo '===== Neburst 四协议 → AkileCloud HY2 21460 ====='
  echo '1) 查看状态'
  echo '2) 只读预检'
  echo '3) 启用中转（重启 sing-box，600秒内需确认）'
  echo '4) 确认长期使用（取消自动回滚）'
  echo '5) 手动恢复 Neburst 原始直连（重启 sing-box）'
  echo '0) 退出'
  read -r -p '请选择: ' choice
  case "$choice" in
    1) python3 "$SCRIPT" status ;;
    2) python3 "$SCRIPT" preflight --candidate "$CANDIDATE" ;;
    3)
      python3 "$SCRIPT" preflight --candidate "$CANDIDATE" || continue
      echo '警告：将重启 sing-box，现有四个代理可能断开；请先准备服务商控制台。'
      read -r -p '输入 SWITCH 确认执行: ' yes
      [[ "$yes" == SWITCH ]] && python3 "$SCRIPT" activate --candidate "$CANDIDATE" --confirm-disruption || echo '已取消'
      ;;
    4)
      echo '请先通过 Hiddify 验证四节点出口均为 AkileCloud。'
      read -r -p '输入 KEEP 确认长期保留: ' yes
      [[ "$yes" == KEEP ]] && python3 "$SCRIPT" keep || echo '已取消'
      ;;
    5)
      echo '警告：将恢复 Neburst 原始配置并重启 sing-box。'
      read -r -p '输入 RESTORE 确认恢复: ' yes
      [[ "$yes" == RESTORE ]] && python3 "$SCRIPT" restore --confirm-disruption || echo '已取消'
      ;;
    0) exit 0 ;;
    *) echo '无效选项' ;;
  esac
done
