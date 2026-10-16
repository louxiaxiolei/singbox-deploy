#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
CONFIG=/etc/sing-box/config.json
NODE=/root/sing-box-node.txt
ENVFILE=/etc/sing-box/lowmem.env
SERVICE=sing-box
say(){ printf '\n%s\n' "$*"; }
fail(){ printf '错误: %s\n' "$*" >&2; exit 1; }
trap 'printf "安装失败，行号 %s，退出码 %s\n" "$LINENO" "$?" >&2' ERR
[[ ${EUID:-$(id -u)} -eq 0 ]] || fail '请使用 root 运行'
[[ -r /etc/os-release ]] || fail '找不到 /etc/os-release'
. /etc/os-release
case "$ID" in
 alpine) PKG=apk;;
 debian|ubuntu) PKG=apt;;
 rocky) PKG=dnf;;
 *) fail "暂不支持系统: $ID";;
esac
ARCH=$(uname -m)
case "$ARCH" in x86_64|aarch64) ;; *) fail "暂不支持架构: $ARCH";; esac
memlimit(){
 local n
 n=$(cat /sys/fs/cgroup/memory.max 2>/dev/null || true)
 [[ "$n" =~ ^[0-9]+$ ]] && { echo "$n"; return; }
 n=$(cat /sys/fs/cgroup/memory/memory.limit_in_bytes 2>/dev/null || true)
 [[ "$n" =~ ^[0-9]+$ ]] && { echo "$n"; return; }
 echo 0
}
LIMIT=$(memlimit)
if (( LIMIT > 0 && LIMIT <= 100663296 )); then
 GO_MEM=28MiB; GO_GC=50; GO_PROCS=1
else
 GO_MEM=128MiB; GO_GC=100; GO_PROCS=2
fi
install_pkg(){
 case "$PKG" in
 apk) apk add --no-cache sing-box;;
 apt) export DEBIAN_FRONTEND=noninteractive; apt-get update; apt-get install -y ca-certificates sing-box;;
 dnf) dnf install -y sing-box;;
 esac
}
valid_ipv4(){
 local ip="$1" a b c d extra oct
 IFS=. read -r a b c d extra <<< "$ip"
 [[ -z "${extra:-}" && -n "${a:-}" && -n "${b:-}" && -n "${c:-}" && -n "${d:-}" ]] || return 1
 for oct in "$a" "$b" "$c" "$d"; do
  [[ "$oct" =~ ^[0-9]{1,3}$ ]] || return 1
  (( 10#$oct <= 255 )) || return 1
 done
}
public_ipv4(){
 local ip="$1" a b c d
 valid_ipv4 "$ip" || return 1
 IFS=. read -r a b c d <<< "$ip"
 (( 10#$a != 0 && 10#$a != 10 && 10#$a != 127 && 10#$a < 224 )) || return 1
 (( !(10#$a == 169 && 10#$b == 254) )) || return 1
 (( !(10#$a == 172 && 10#$b >= 16 && 10#$b <= 31) )) || return 1
 (( !(10#$a == 192 && 10#$b == 168) )) || return 1
 (( !(10#$a == 100 && 10#$b >= 64 && 10#$b <= 127) )) || return 1
 (( !(10#$a == 192 && 10#$b == 0 && 10#$c == 0) )) || return 1
 (( !(10#$a == 198 && (10#$b == 18 || 10#$b == 19)) )) || return 1
 (( !(10#$a == 192 && 10#$b == 0 && 10#$c == 2) )) || return 1
 (( !(10#$a == 198 && 10#$b == 51 && 10#$c == 100) )) || return 1
 (( !(10#$a == 203 && 10#$b == 0 && 10#$c == 113) )) || return 1
}
auto_public_ip(){
 local candidate='' url
 if [[ -n "${SSH_CONNECTION:-}" ]]; then
  candidate=$(awk '{print $3}' <<< "$SSH_CONNECTION")
  if public_ipv4 "$candidate"; then printf '%s' "$candidate"; return 0; fi
 fi
 for url in https://api.ipify.org https://ipv4.icanhazip.com https://ifconfig.me/ip; do
  candidate=''
  if command -v curl >/dev/null 2>&1; then
   candidate=$(curl -4fsSL --connect-timeout 3 --max-time 6 "$url" 2>/dev/null || true)
  elif command -v wget >/dev/null 2>&1; then
   candidate=$(wget -qO- -T 6 "$url" 2>/dev/null || true)
  fi
  candidate=${candidate//$'\r'/}
  candidate=${candidate//$'\n'/}
  if public_ipv4 "$candidate"; then printf '%s' "$candidate"; return 0; fi
 done
 return 1
}
valid_port(){ [[ "$1" =~ ^[0-9]+$ ]] && (( 10#$1 >= 1 && 10#$1 <= 65535 )); }
read_port(){ local prompt=$1 default=$2 value; read -r -p "$prompt [$default]: " value; value=${value:-$default}; valid_port "$value" || fail "无效端口: $value"; printf '%s' "$value"; }
install_node(){
 [[ ! -e "$CONFIG" ]] || fail "已有配置 $CONFIG；为避免覆盖，已停止。"
 local localport host publicport keys private public uuid sid link
 read -r -p '内网监听 TCP 端口 [10000]: ' localport; localport=${localport:-10000}
 valid_port "$localport" || fail '内网端口无效'
 host=$(auto_public_ip) || fail '自动识别公网 IP 失败，请检查 VPS 的 HTTPS 出口网络'
 say "自动识别公网 IP: $host"
 read -r -p "公网映射 TCP 端口 [$localport]: " publicport; publicport=${publicport:-$localport}
 valid_port "$publicport" || fail '公网端口无效'
 say "系统: $PRETTY_NAME | 架构: $ARCH | 内存限制: $LIMIT 字节"
 say '安装 sing-box（仅使用系统仓库，不执行未知远程安装脚本）'
 if ! command -v sing-box >/dev/null 2>&1; then
  if ! install_pkg; then fail '系统仓库安装失败；请检查软件源，当前脚本不会自动引入第三方仓库'; fi
 fi
 command -v sing-box >/dev/null 2>&1 || fail '找不到 sing-box 可执行文件'
 sing-box version || fail 'sing-box 无法执行（可能是内存不足）'
 keys=$(GOMEMLIMIT="$GO_MEM" GOGC="$GO_GC" GOMAXPROCS="$GO_PROCS" sing-box generate reality-keypair)
 private=$(printf '%s\n' "$keys" | sed -n 's/^PrivateKey: *//p' | head -n1)
 public=$(printf '%s\n' "$keys" | sed -n 's/^PublicKey: *//p' | head -n1)
 uuid=$(sing-box generate uuid)
 sid=$(od -An -N8 -tx1 /dev/urandom | tr -d ' \n')
 [[ -n "$private" && -n "$public" && -n "$uuid" && -n "$sid" ]] || fail '密钥生成失败'
 mkdir -p /etc/sing-box
 cat > "$CONFIG" <<EOF
{
 "log":{"level":"error"},
 "inbounds":[{"type":"vless","tag":"vless-in","listen":"0.0.0.0","listen_port":$localport,
 "users":[{"uuid":"$uuid","flow":"xtls-rprx-vision"}],
 "tls":{"enabled":true,"server_name":"www.microsoft.com","reality":{"enabled":true,
 "handshake":{"server":"www.microsoft.com","server_port":443},
 "private_key":"$private","short_id":["$sid"]}}}],
 "outbounds":[{"type":"direct","tag":"direct"}]
}
EOF
 cat > "$ENVFILE" <<EOF
GOMEMLIMIT=$GO_MEM
GOGC=$GO_GC
GOMAXPROCS=$GO_PROCS
EOF
 chmod 600 "$CONFIG" "$ENVFILE"
 GOMEMLIMIT="$GO_MEM" GOGC="$GO_GC" GOMAXPROCS="$GO_PROCS" sing-box check -c "$CONFIG" || fail '配置校验失败'
 # Use an explicit wrapper for all init variants.
 cat > /usr/local/bin/sing-box-lowmem <<'EOF'
#!/bin/sh
set -a
. /etc/sing-box/lowmem.env
set +a
exec sing-box run -c /etc/sing-box/config.json
EOF
 chmod 755 /usr/local/bin/sing-box-lowmem
 if command -v systemctl >/dev/null 2>&1 && [[ -d /run/systemd/system ]]; then
  cat > /etc/systemd/system/sing-box-lowmem.service <<'EOF'
[Unit]
Description=sing-box lightweight Reality
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
ExecStart=/usr/local/bin/sing-box-lowmem
Restart=on-failure
RestartSec=3
[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable --now sing-box-lowmem.service
 elif command -v rc-service >/dev/null 2>&1 && [[ -d /run/openrc ]]; then
  cat > /etc/init.d/sing-box-lowmem <<'EOF'
#!/sbin/openrc-run
name="sing-box-lowmem"
command="/usr/local/bin/sing-box-lowmem"
command_background="yes"
pidfile="/run/sing-box-lowmem.pid"
output_log="/var/log/sing-box-lowmem.log"
error_log="/var/log/sing-box-lowmem.log"
EOF
  chmod +x /etc/init.d/sing-box-lowmem
  rc-update add sing-box-lowmem default
  rc-service sing-box-lowmem start
 else
  say '未检测到运行中的 init；使用临时后台模式（容器重启后需重新启动）'
  nohup /usr/local/bin/sing-box-lowmem >/tmp/sing-box-lowmem.log 2>&1 </dev/null &
  echo $! >/run/sing-box-lowmem.pid
 fi
 sleep 2
 if ! pgrep -f 'sing-box run -c /etc/sing-box/config.json' >/dev/null 2>&1; then
  say '未检测到服务进程，请检查日志或服务状态；不输出成功提示'
  exit 1
 fi
 link="vless://$uuid@$host:$publicport?encryption=none&flow=xtls-rprx-vision&security=reality&sni=www.microsoft.com&fp=chrome&pbk=$public&sid=$sid&type=tcp#Alpine-NAT"
 printf '%s\n' "$link" > "$NODE"
 chmod 600 "$NODE"
 say '服务已启动。节点链接（请勿公开分享）：'
 printf '%s\n' "$link"
 say "已保存到 $NODE。请确认 NAT TCP 映射已在服务商面板配置。"
}
say '==== sing-box 多系统一键管理 ===='
printf '系统: %s | 架构: %s\n' "$PRETTY_NAME" "$ARCH"
printf '1. 安装 VLESS + Reality\n2. 查看已有节点链接\nq. 退出\n'
read -r -p '请选择: ' choice
case "$choice" in
 1) install_node;;
 2) [[ -r "$NODE" ]] && cat "$NODE" || fail '尚无保存的节点链接';;
 q|Q) exit 0;;
 *) fail '无效选项';;
esac
