#!/usr/bin/env bash
# Short menu for the existing Neburst <-> AkileCloud relay. Does not alter existing node names.
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 ]] || { echo '请使用 root'; exit 1; }
for c in curl python3 sing-box systemctl; do command -v "$c" >/dev/null || { echo "缺少 $c"; exit 1; }; done
ROOT=/root/neburst-relay-preflight
MANAGER=/root/neburst-persistent-switch.py
CANDIDATE="$ROOT/config.candidate-20261113T160005Z.json"
URL='https://raw.githubusercontent.com/louxiaxiolei/singbox-deploy/a32b93d594b16285a14c827e92abaa115b12ef12/relay-enhancement/neburst_persistent_switch.py'
if [[ ! -f "$MANAGER" ]]; then
  t=$(mktemp);trap 'rm -f "$t"' EXIT
  curl -fLSs --retry 2 --connect-timeout 10 --max-time 45 "$URL" -o "$t"
  python3 -m py_compile "$t"
  install -m 700 "$t" "$MANAGER"
fi
get_status() {
  python3 - "$ROOT/persistent-state.json" <<'PY'
import json,sys,pathlib
p=pathlib.Path(sys.argv[1])
try: print(json.loads(p.read_text()).get('status','unknown') if p.exists() else 'none')
except Exception: print('invalid')
PY
}
while true; do
  echo
  echo '==== SB 中转管理（Neburst）===='
  echo '1 查看状态'
  echo '2 启用长期中转（AkileCloud 出口）'
  echo '3 恢复原始直连（Neburst 出口）'
  echo '0 退出'
  read -r -p '选择: ' op || exit 0
  case "$op" in
    1) python3 "$MANAGER" status ;;
    2)
      s=$(get_status)
      if [[ "$s" == persistent ]]; then echo '已处于长期中转模式';continue;fi
      if [[ "$s" == pending ]]; then
        echo '已有待确认的切换；直接保留当前中转配置'
        python3 "$MANAGER" keep
        continue
      fi
      if [[ "$s" == invalid ]]; then echo '状态文件异常，拒绝操作';continue;fi
      echo '将重启 sing-box；操作期间代理连接可能中断。'
      # activate does strict config checks and creates a backup; no separate preflight menu.
      if python3 "$MANAGER" activate --candidate "$CANDIDATE" --confirm-disruption; then
        # Immediately commit persistent mode: no user testing or KEEP step.
        python3 "$MANAGER" keep
      else
        echo '启用失败，请查看状态；不要删除备份。'
      fi
      ;;
    3)
      s=$(get_status)
      if [[ "$s" == pending || "$s" == persistent ]]; then
        echo '恢复备份并重启 sing-box...'
        python3 "$MANAGER" restore --confirm-disruption
      else
        echo "当前状态为 $s；无需要恢复的活动中转"
      fi
      ;;
    0) exit 0 ;;
    *) echo '无效选项' ;;
  esac
done
