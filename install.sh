#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
BASE=/etc/singbox-deploy
NODES="$BASE/nodes"
EXPORT=/root/sing-box-nodes.txt
[[ $(id -u) == 0 ]] || { echo '请使用 root 执行'; exit 1; }
. /etc/os-release
case "$ID" in alpine) PKG=apk;; debian|ubuntu) PKG=apt;; rocky) PKG=dnf;; *) echo "不支持的系统: $ID"; exit 1;; esac
case "$(uname -m)" in x86_64) SARCH=amd64;; aarch64) SARCH=arm64;; *) echo '不支持的 CPU 架构'; exit 1;; esac
# 将当前脚本安装为本地管理程序；LM 不依赖网络即可打开菜单
install_lm_launcher(){
  local source="${BASH_SOURCE[0]}" target=/usr/local/lib/singbox-deploy/install.sh
  mkdir -p /usr/local/lib/singbox-deploy
  if [[ "$source" == /dev/fd/* || "$source" == /proc/self/fd/* ]]; then
    local tmp
    tmp=$(mktemp)
    if command -v curl >/dev/null 2>&1 && curl -fsSL --connect-timeout 5 --max-time 30 "https://raw.githubusercontent.com/louxiaxiolei/singbox-deploy/main/install.sh" -o "$tmp"; then
      install -m 700 "$tmp" "$target"
    elif command -v wget >/dev/null 2>&1 && wget -qO "$tmp" -T 30 "https://raw.githubusercontent.com/louxiaxiolei/singbox-deploy/main/install.sh"; then
      install -m 700 "$tmp" "$target"
    fi
    rm -f "$tmp"
  elif [[ -f "$source" && -s "$source" ]]; then
    if [[ "$(readlink -f "$source")" != "$(readlink -f "$target" 2>/dev/null || true)" ]]; then
      install -m 700 "$source" "$target"
    fi
  elif [[ ! -s "$target" ]]; then
    echo '提示：通过进程替换运行时无法缓存脚本；LM 将在联网时首次下载。' >&2
  fi
  cat > /usr/local/bin/LM <<'LM_SCRIPT'
#!/usr/bin/env bash
set -Eeuo pipefail
url="https://raw.githubusercontent.com/louxiaxiolei/singbox-deploy/main/install.sh"
target=/usr/local/lib/singbox-deploy/install.sh
if [[ -s "$target" ]]; then exec bash "$target" "$@"; fi
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
if command -v curl >/dev/null 2>&1; then
  curl -fsSL --connect-timeout 5 --max-time 30 "$url" -o "$tmp"
elif command -v wget >/dev/null 2>&1; then
  wget -qO "$tmp" -T 30 "$url"
else
  echo '需要 curl 或 wget 才能首次下载管理脚本' >&2; exit 1
fi
[[ -s "$tmp" ]] || { echo '下载失败' >&2; exit 1; }
install -m 700 "$tmp" "$target"
exec bash "$target" "$@"
LM_SCRIPT
  chmod 755 /usr/local/bin/LM
}
install_lm_launcher
say(){ printf '\n%s\n' "$*"; }
die(){ echo "错误: $*" >&2; exit 1; }
valid_port(){ [[ "$1" =~ ^[0-9]{1,5}$ ]] && (( 10#$1 >= 1 && 10#$1 <= 65535 )); }
random_port(){ local p i; for ((i=0;i<80;i++)); do p=$((10000 + $(od -An -N4 -tu4 /dev/urandom) % 50000)); if ! grep -REqs '"listen_port"[[:space:]]*:[[:space:]]*'"$p"'([,}]|$)' "$NODES" --include='*.json' 2>/dev/null && ! { command -v ss >/dev/null && ss -H -lnut 2>/dev/null | awk '{print $5}' | grep -Eq ":$p$"; }; then echo "$p"; return; fi; done; die '无法找到空闲端口'; }
port_available(){
  local port=$1 proto=$2 f used
  for f in "$NODES"/*.json; do
    [[ -f "$f" ]] || continue
    used=$(jq -r --argjson p "$port" '.inbounds[]? | select(.listen_port == $p) | .type' "$f" 2>/dev/null || true)
    [[ -z "$used" ]] || return 1
  done
  if command -v ss >/dev/null 2>&1; then
    if [[ "$proto" == hy2 || "$proto" == tuic ]]; then
      ss -H -lun 2>/dev/null | awk '{print $5}' | grep -Eq ":${port}$" && return 1
    else
      ss -H -ltn 2>/dev/null | awk '{print $4}' | grep -Eq ":${port}$" && return 1
    fi
  fi
  return 0
}
public_ip(){ local v u; if [[ -n "${SSH_CONNECTION:-}" ]]; then v=$(awk '{print $3}' <<< "$SSH_CONNECTION"); if [[ "$v" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] && ! [[ "$v" =~ ^(10\.|127\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.|169\.254\.) ]]; then echo "$v"; return; fi; fi; for u in https://api.ipify.org https://ipv4.icanhazip.com; do v=$(curl -4fsSL --connect-timeout 3 --max-time 8 "$u" 2>/dev/null || true); v=${v//$'\n'/}; if [[ "$v" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then echo "$v"; return; fi; done; return 1; }
install_deps(){ case "$PKG" in apk) apk add --no-cache curl ca-certificates tar gzip openssl jq coreutils;; apt) export DEBIAN_FRONTEND=noninteractive; apt-get update && apt-get install -y curl ca-certificates tar gzip openssl jq coreutils;; dnf) dnf install -y curl ca-certificates tar gzip openssl jq coreutils;; esac; }
install_singbox(){ if command -v sing-box >/dev/null 2>&1; then return; fi; if case "$PKG" in apk) apk add --no-cache sing-box;; apt) apt-get install -y sing-box;; dnf) dnf install -y sing-box;; esac >/dev/null 2>&1; then return; fi; local tag ver dir tmp; tag=$(curl -fsSL --retry 2 https://api.github.com/repos/SagerNet/sing-box/releases/latest | jq -r .tag_name); [[ "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || die '无法获取官方稳定版'; ver=${tag#v}; dir="sing-box-$ver-linux-$SARCH"; tmp=$(mktemp -d); curl -fL --retry 2 --max-time 180 "https://github.com/SagerNet/sing-box/releases/download/$tag/$dir.tar.gz" -o "$tmp/a.tar.gz" || die '下载 sing-box 失败'; tar -xzf "$tmp/a.tar.gz" -C "$tmp" "$dir/sing-box" || die '解压失败'; install -m 755 "$tmp/$dir/sing-box" /usr/local/bin/sing-box; rm -rf "$tmp"; }
lowmem(){ local limit; limit=$(cat /sys/fs/cgroup/memory.max 2>/dev/null || echo max); if [[ "$limit" =~ ^[0-9]+$ ]] && (( limit <= 100663296 )); then echo 28MiB; else echo 128MiB; fi; }
prepare(){ install_deps; install_singbox; sing-box version | head -1; mkdir -p "$NODES"; chmod 700 "$BASE" "$NODES"; }
cert(){ if [[ -s "$BASE/cert.pem" && -s "$BASE/key.pem" ]]; then return; fi; local ip=$1; openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -sha256 -days 3650 -keyout "$BASE/key.pem" -out "$BASE/cert.pem" -subj '/CN=singbox.local' -addext "subjectAltName=DNS:singbox.local,IP:$ip" >/dev/null 2>&1 || die '生成证书失败'; chmod 600 "$BASE/key.pem"; }
urlenc(){ local s=$1 i c h out=''; LC_ALL=C; for ((i=0;i<${#s};i++)); do c=${s:i:1}; case "$c" in [a-zA-Z0-9._~-]) out+="$c";; *) printf -v h '%%%02X' "'$c"; out+="$h";; esac; done; printf '%s' "$out"; }
regen(){ : > "$EXPORT"; local f; for f in "$NODES"/*.link; do [[ -f "$f" ]] && cat "$f" >> "$EXPORT"; done; chmod 600 "$EXPORT"; }
start_node(){ local id=$1 conf="$NODES/$1.json"; if [[ -d /run/systemd/system ]] && command -v systemctl >/dev/null; then cat > "/etc/systemd/system/singbox-deploy-$id.service" <<EOF
[Unit]
Description=singbox-deploy $id
After=network-online.target
[Service]
Environment=GOMEMLIMIT=$(lowmem)
Environment=GOGC=50
Environment=GOMAXPROCS=1
ExecStart=$(command -v sing-box) run -c $conf
Restart=on-failure
RestartSec=3
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload; systemctl enable --now "singbox-deploy-$id.service"; elif command -v rc-service >/dev/null && [[ -x /sbin/openrc-run ]]; then cat > "/etc/init.d/singbox-deploy-$id" <<EOF
#!/sbin/openrc-run
command="$(command -v sing-box)"
command_args="run -c $conf"
command_background="yes"
pidfile="/run/singbox-deploy-$id.pid"
export GOMEMLIMIT="$(lowmem)" GOGC=50 GOMAXPROCS=1
EOF
chmod +x "/etc/init.d/singbox-deploy-$id"; rc-update add "singbox-deploy-$id" default; rc-service "singbox-deploy-$id" start; else GOMEMLIMIT="$(lowmem)" GOGC=50 GOMAXPROCS=1 nohup sing-box run -c "$conf" >"$NODES/$id.log" 2>&1 </dev/null & echo $! > "$NODES/$id.pid"; say '当前环境无 init，重启后需要手动启动'; fi; }
stop_node(){ local id=$1; if [[ -f "/etc/systemd/system/singbox-deploy-$id.service" ]]; then systemctl disable --now "singbox-deploy-$id.service" || true; rm -f "/etc/systemd/system/singbox-deploy-$id.service"; systemctl daemon-reload; elif [[ -f "/etc/init.d/singbox-deploy-$id" ]]; then rc-service "singbox-deploy-$id" stop || true; rc-update del "singbox-deploy-$id" default || true; rm -f "/etc/init.d/singbox-deploy-$id"; elif [[ -f "$NODES/$id.pid" ]]; then kill "$(cat "$NODES/$id.pid")" 2>/dev/null || true; fi; }
add_node(){ local proto=$1 ip port external name label id uuid pw key pub sid path conf link inbound tls; prepare; ip=$(public_ip) || die '无法自动检测公网 IP'; say "自动识别公网 IP: $ip"; port=$(random_port); read -r -p "监听端口 [$port，回车随机]: " x; port=${x:-$port}; valid_port "$port" || die '监听端口无效'; port_available "$port" "$proto" || die "监听端口 $port 已被占用"; read -r -p "节点连接端口 [$port]: " x; external=${x:-$port}; valid_port "$external" || die '连接端口无效'; read -r -p "节点名称 [$proto]: " x; name=${x:-$proto}; [[ -n "$name" && ${#name} -le 80 ]] || die '节点名称无效'; label=$(urlenc "$name"); id="${proto}-$(date +%s)-$(od -An -N3 -tx1 /dev/urandom | tr -d ' \n')"; uuid=$(sing-box generate uuid); pw=$(openssl rand -hex 20); conf="$NODES/$id.json"; tls=$(jq -n --arg cert "$BASE/cert.pem" --arg key "$BASE/key.pem" '{enabled:true,server_name:"singbox.local",certificate_path:$cert,key_path:$key,alpn:["h3"]}'); case "$proto" in
 reality) key=$(sing-box generate reality-keypair); pub=$(sed -n 's/^PublicKey: *//p' <<< "$key"); key=$(sed -n 's/^PrivateKey: *//p' <<< "$key"); sid=$(openssl rand -hex 8); [[ -n "$pub" && -n "$key" ]] || die 'Reality 密钥生成失败'; inbound=$(jq -n --arg uuid "$uuid" --arg priv "$key" --arg sid "$sid" --argjson port "$port" '{type:"vless",tag:"in",listen:"0.0.0.0",listen_port:$port,users:[{uuid:$uuid,flow:"xtls-rprx-vision"}],tls:{enabled:true,server_name:"www.microsoft.com",reality:{enabled:true,handshake:{server:"www.microsoft.com",server_port:443},private_key:$priv,short_id:[$sid]}}}'); link="vless://$uuid@$ip:$external?encryption=none&flow=xtls-rprx-vision&security=reality&sni=www.microsoft.com&fp=chrome&pbk=$pub&sid=$sid&type=tcp#$label";;
 hy2) cert "$ip"; inbound=$(jq -n --arg pw "$pw" --argjson port "$port" --argjson tls "$tls" '{type:"hysteria2",tag:"in",listen:"0.0.0.0",listen_port:$port,users:[{password:$pw}],tls:$tls}'); link="hysteria2://$pw@$ip:$external?sni=singbox.local&insecure=1#$label";;
 tuic) cert "$ip"; inbound=$(jq -n --arg uuid "$uuid" --arg pw "$pw" --argjson port "$port" --argjson tls "$tls" '{type:"tuic",tag:"in",listen:"0.0.0.0",listen_port:$port,users:[{uuid:$uuid,password:$pw}],congestion_control:"bbr",tls:$tls}'); link="tuic://$uuid:$pw@$ip:$external?sni=singbox.local&alpn=h3&congestion_control=bbr&allow_insecure=1#$label";;
 vmess) path="/$(openssl rand -hex 6)"; inbound=$(jq -n --arg uuid "$uuid" --arg path "$path" --argjson port "$port" '{type:"vmess",tag:"in",listen:"0.0.0.0",listen_port:$port,users:[{uuid:$uuid,alterId:0}],transport:{type:"ws",path:$path}}'); link="vmess://$(jq -cn --arg add "$ip" --argjson port "$external" --arg id "$uuid" --arg ps "$name" --arg path "$path" '{v:"2",ps:$ps,add:$add,port:($port|tostring),id:$id,aid:"0",net:"ws",type:"none",host:"",path:$path,tls:""}' | base64 | tr -d '\n')";;
 trojan) cert "$ip"; tls=$(jq -n --arg cert "$BASE/cert.pem" --arg key "$BASE/key.pem" '{enabled:true,server_name:"singbox.local",certificate_path:$cert,key_path:$key}'); inbound=$(jq -n --arg pw "$pw" --argjson port "$port" --argjson tls "$tls" '{type:"trojan",tag:"in",listen:"0.0.0.0",listen_port:$port,users:[{password:$pw}],tls:$tls}'); link="trojan://$pw@$ip:$external?security=tls&sni=singbox.local&allowInsecure=1#$label";;
 esac
 jq -n --argjson inbound "$inbound" '{log:{level:"error"},inbounds:[$inbound],outbounds:[{type:"direct",tag:"direct"}]}' > "$conf"; chmod 600 "$conf"; if ! GOMEMLIMIT="$(lowmem)" GOGC=50 GOMAXPROCS=1 sing-box check -c "$conf"; then rm -f "$conf"; die "配置检查失败（可能是 sing-box 版本不支持 $proto）"; fi; printf '%s\n' "$link" > "$NODES/$id.link"; printf '%s\n' "$name | $proto | 本地:$port | 连接:$external" > "$NODES/$id.info"; if ! start_node "$id"; then
  stop_node "$id" || true
  rm -f "$conf" "$NODES/$id.link" "$NODES/$id.info" "$NODES/$id.pid"
  die '节点服务启动失败，已回滚本次新增配置'
fi
sleep 2
if [[ -f "/etc/systemd/system/singbox-deploy-$id.service" ]]; then
  if ! systemctl is-active --quiet "singbox-deploy-$id.service"; then
    journalctl -u "singbox-deploy-$id.service" -n 15 --no-pager >&2 || true
    stop_node "$id"; rm -f "$conf" "$NODES/$id.link" "$NODES/$id.info"
    die '服务未正常运行，已回滚本次新增配置'
  fi
elif [[ -f "$NODES/$id.pid" ]] && ! kill -0 "$(cat "$NODES/$id.pid")" 2>/dev/null; then
  stop_node "$id"; rm -f "$conf" "$NODES/$id.link" "$NODES/$id.info" "$NODES/$id.pid"
  die '后台进程已退出，已回滚本次新增配置'
fi
regen; say "节点已添加：$name ($proto)"; echo "$link"; say "节点汇总文件：$EXPORT"; if [[ "$proto" != reality && "$proto" != vmess ]]; then say '注意：使用自签名证书，客户端需开启跳过证书验证；此模式不适合对 TLS 身份认证要求较高的场景。'; fi; if [[ "$proto" == hy2 || "$proto" == tuic ]]; then say "请确保 UDP $external 已放行并正确转发到 UDP $port"; else say "请确保 TCP $external 已放行并正确转发到 TCP $port"; fi; }
remove_node(){ local ids=() f n; for f in "$NODES"/*.info; do [[ -f "$f" ]] && ids+=("${f##*/}"); done; ((${#ids[@]})) || die '没有节点'; for ((n=0;n<${#ids[@]};n++)); do printf '%d) %s\n' "$((n+1))" "$(cat "$NODES/${ids[n]}")"; done; read -r -p '输入要删除的序号: ' n; [[ "$n" =~ ^[0-9]+$ ]] && ((n>=1 && n<=${#ids[@]})) || die '无效序号'; local id=${ids[n-1]%.info}; stop_node "$id"; rm -f "$NODES/$id.json" "$NODES/$id.link" "$NODES/$id.info" "$NODES/$id.pid" "$NODES/$id.log"; regen; say '节点已删除'; }
view_nodes(){ [[ -s "$EXPORT" ]] && cat "$EXPORT" || say '暂无通过本脚本安装的节点'; }
restart_nodes(){ local f id; for f in "$NODES"/*.json; do [[ -f "$f" ]] || continue; id=${f##*/}; id=${id%.json}; stop_node "$id"; start_node "$id"; done; say '已尝试重启所有节点'; }
backup_nodes(){
  local folder=/root/singbox-deploy-backups stamp output
  mkdir -p "$folder"; chmod 700 "$folder"
  stamp=$(date +%Y%m%d-%H%M%S)
  output="$folder/nodes-$stamp.tar.gz"
  tar -czf "$output" -C /etc singbox-deploy
  chmod 600 "$output"
  say "备份成功：$output（包含节点凭据和证书私钥，请妥善保管）"
}
restore_nodes(){
  local file tmp f
  read -r -p '输入备份文件绝对路径: ' file
  [[ -f "$file" ]] || die '找不到备份文件'
  tar -tzf "$file" | grep -Eq '^singbox-deploy/' || die '备份格式不正确'
  if tar -tzf "$file" | grep -Eq '(^/|(^|/)\.\.(/|$))'; then die '备份存在不安全路径'; fi
  read -r -p '恢复将覆盖现有节点配置。输入 RESTORE 确认: ' tmp
  [[ "$tmp" == RESTORE ]] || { say '已取消'; return; }
  backup_nodes
  for f in "$NODES"/*.json; do [[ -f "$f" ]] || continue; tmp=${f##*/}; stop_node "${tmp%.json}" 2>/dev/null || true; done
  rm -f "$NODES"/*.json "$NODES"/*.link "$NODES"/*.info
  tar -xzf "$file" -C /etc
  chmod 700 "$BASE" "$NODES"
  for f in "$NODES"/*.json; do [[ -f "$f" ]] || continue; sing-box check -c "$f" || die "恢复的配置检查失败：$f"; done
  for f in "$NODES"/*.json; do [[ -f "$f" ]] || continue; tmp=${f##*/}; start_node "${tmp%.json}"; done
  regen; say '已恢复节点配置并尝试启动服务'
}
diagnose(){
  local f id proto port
  say '=== 环境 ==='
  printf '系统: %s\n架构: %s\n' "$PRETTY_NAME" "$(uname -m)"
  free -h 2>/dev/null || true
  if command -v sing-box >/dev/null; then sing-box version | head -1; else echo 'sing-box 未安装'; fi
  say '=== 节点配置与服务 ==='
  for f in "$NODES"/*.json; do
    [[ -f "$f" ]] || continue
    id=${f##*/}; id=${id%.json}
    proto=$(jq -r '.inbounds[0].type' "$f" 2>/dev/null || echo unknown)
    port=$(jq -r '.inbounds[0].listen_port' "$f" 2>/dev/null || echo unknown)
    printf '%s | %s | 本地端口 %s | ' "$id" "$proto" "$port"
    if [[ -f "/etc/systemd/system/singbox-deploy-$id.service" ]]; then
      systemctl is-active "singbox-deploy-$id.service" 2>/dev/null || true
    elif [[ -f "$NODES/$id.pid" ]] && kill -0 "$(cat "$NODES/$id.pid")" 2>/dev/null; then
      echo running
    else echo '未确认运行状态'; fi
    sing-box check -c "$f" >/dev/null 2>&1 && echo '配置检查：通过' || echo '配置检查：失败'
  done
  say '=== 端口监听 ==='
  ss -lntu 2>/dev/null | head -35 || echo '未安装 ss，无法显示监听情况'
  say '云服务商安全组及外部 NAT 映射无法从服务器内部完全验证'
}
mkdir -p "$NODES"; chmod 700 "$BASE" "$NODES"
say '========== singbox-deploy =========='
printf '系统: %s\n1. VLESS + Reality\n2. Hysteria2 (UDP)\n3. TUIC (UDP)\n4. VMess + WebSocket\n5. Trojan + TLS\n6. 逐个安装全部协议\n7. 查看节点\n8. 删除节点\n9. 重启所有节点\n10. 备份节点配置\n11. 恢复节点配置\n12. 故障诊断\n0. 退出\n' "$PRETTY_NAME"
read -r -p '请选择: ' choice
case "$choice" in 1) add_node reality;; 2) add_node hy2;; 3) add_node tuic;; 4) add_node vmess;; 5) add_node trojan;; 6) for p in reality hy2 tuic vmess trojan; do add_node "$p"; done;; 7) view_nodes;; 8) remove_node;; 9) restart_nodes;; 10) backup_nodes;; 11) restore_nodes;; 12) diagnose;; 0) exit;; *) die '无效选项';; esac
