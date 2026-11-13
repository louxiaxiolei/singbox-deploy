#!/usr/bin/env bash
# Unified VPS installer and manager; intended for fresh Debian/Ubuntu VPS with systemd.
set -Eeuo pipefail
umask 077
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
[[ $EUID -eq 0 ]] || { echo '请使用 root 运行'; exit 1; }
BASE_URL='https://raw.githubusercontent.com/louxiaxiolei/singbox-deploy/relay'
CACHE=/usr/local/lib/sb-manager
mkdir -p "$CACHE"
chmod 700 "$CACHE"
fetch() {
  local path=$1 dst=$2 tmp
  tmp=$(mktemp)
  if ! curl -fLSs --retry 2 --connect-timeout 10 --max-time 50 "$BASE_URL/$path" -o "$tmp"; then
    rm -f "$tmp";echo "下载失败: $path" >&2;return 1
  fi
  [[ -s "$tmp" ]] || { rm -f "$tmp";echo '下载内容为空' >&2;return 1; }
  case "$dst" in *.py) python3 -m py_compile "$tmp" || { rm -f "$tmp";return 1; };; *.sh) bash -n "$tmp" || { rm -f "$tmp";return 1; };; esac
  install -m 700 "$tmp" "$dst"
  rm -f "$tmp"
}
ensure_curl() {
  if command -v curl >/dev/null; then return; fi
  echo '缺少 curl；请先安装 curl';return 1
}
ensure_python() {
  if command -v python3 >/dev/null;then return;fi
  echo '缺少 python3；Debian/Ubuntu 可执行 apt-get update && apt-get install -y python3';return 1
}
systemd_required() {
  [[ -d /run/systemd/system ]] && command -v systemctl >/dev/null || { echo '中转与落地管理需要 systemd';return 1; }
}
singbox_required() {
  command -v sing-box >/dev/null || { echo '请先选择 1 安装至少一个节点';return 1; }
}
node_install() {
  fetch install.sh "$CACHE/install.sh" || return
  bash "$CACHE/install.sh"
}
relay_menu() {
  ensure_python && systemd_required && singbox_required || return
  if [[ ! -d /etc/singbox-deploy/nodes ]] || ! compgen -G '/etc/singbox-deploy/nodes/*.json' >/dev/null;then
    echo '请先选择 1 安装本项目节点；本模块不会修改其他 sing-box 服务';return
  fi
  fetch relay-enhancement/relay_manager.py "$CACHE/relay_manager.py" || return
  python3 "$CACHE/relay_manager.py"
}
landing_create() {
  ensure_python && systemd_required && singbox_required || return
  command -v openssl >/dev/null || { echo '缺少 openssl';return; }
  fetch relay-enhancement/landing_manager.py "$CACHE/landing_manager.py" || return
  python3 "$CACHE/landing_manager.py"
}
landing_manage() {
  ensure_python && systemd_required && singbox_required || return
  fetch relay-enhancement/landing_control.py "$CACHE/landing_control.py" || return
  python3 "$CACHE/landing_control.py"
}
status() {
  echo '=== sing-box ==='
  if command -v sing-box >/dev/null;then sing-box version | head -1;else echo '尚未安装';fi
  echo '=== 本项目普通节点 ==='
  local f id
  for f in /etc/singbox-deploy/nodes/*.json;do
    [[ -f "$f" ]] || continue
    id=${f##*/};id=${id%.json}
    printf '%s | ' "$id"
    systemctl is-active "singbox-deploy-$id.service" 2>/dev/null || true
  done
  echo '=== 本项目落地节点 ==='
  for f in /etc/singbox-deploy-v2/nodes/*.json;do
    [[ -f "$f" ]] || continue
    id=${f##*/};id=${id%.json}
    printf '%s | ' "$id"
    systemctl is-active "singbox-landing-$id.service" 2>/dev/null || true
  done
  echo '=== 备份目录（只显示文件名，不输出凭据） ==='
  for d in /root/singbox-deploy-backups /etc/singbox-deploy/relay-backups /etc/singbox-deploy-v2/backups;do
    if [[ -d "$d" ]];then echo "$d";find "$d" -maxdepth 1 -type f -printf '  %f\n' | tail -20;fi
  done
  echo '提示：原 Neburst 专用 /etc/sing-box/config.json 不由此通用菜单管理。'
}
while true;do
  echo
  echo '====== Sing-box 一键管理 ======'
  echo '1. 安装主流代理节点'
  echo '2. 查看、管理已有节点'
  echo '3. 添加中转出口'
  echo '4. 恢复节点直连'
  echo '5. 创建落地节点'
  echo '6. 管理落地节点（停用 / 启用 / 删除）'
  echo '7. 查看运行状态和备份'
  echo '0. 退出'
  read -r -p '请选择: ' choice || exit 0
  case "$choice" in
    1) ensure_curl && node_install || true;;
    2) ensure_curl && node_install || true;;
    3) ensure_curl && relay_menu || true;;
    4) ensure_curl && relay_menu || true;;
    5) ensure_curl && landing_create || true;;
    6) ensure_curl && landing_manage || true;;
    7) status;;
    0) exit 0;;
    *) echo '无效选项';;
  esac
done
