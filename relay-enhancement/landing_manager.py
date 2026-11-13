#!/usr/bin/env python3
"""Isolated five-protocol landing nodes. Never edits existing sing-box configs/services."""
import argparse,base64,ipaddress,json,os,pathlib,re,secrets,shutil,socket,subprocess,sys,tempfile,time,urllib.parse,uuid
BASE=pathlib.Path("/etc/singbox-deploy-v2"); NODES=BASE/"nodes";CERT=BASE/"cert";UNITS=pathlib.Path("/etc/systemd/system")
PROTOS={"ss":"shadowsocks","hy2":"hysteria2","tuic":"tuic","reality":"vless","anytls":"anytls"}
def fail(m):raise RuntimeError(m)
def run(cmd,**kw):return subprocess.run(cmd,check=True,text=True,capture_output=True,**kw).stdout
def write(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    with open(path,"x") as f:json.dump(obj,f,ensure_ascii=False,indent=2);f.write("\n")
    path.chmod(0o600)
def tls():
    CERT.mkdir(parents=True,exist_ok=True);CERT.chmod(0o700)
    cert=CERT/"cert.pem";key=CERT/"key.pem"
    if cert.exists() != key.exists():fail("证书文件不完整，请人工检查")
    if not cert.exists():
        run(["openssl","req","-x509","-newkey","rsa:2048","-nodes","-days","365","-subj","/CN=singbox.local","-keyout",str(key),"-out",str(cert)])
        key.chmod(0o600);cert.chmod(0o600)
    return {"enabled":True,"certificate_path":str(cert),"key_path":str(key)}
def port_free(port,udp):
    # Probe both families and both transports; fail closed on unknown bind errors.
    for family,addr in ((socket.AF_INET,"0.0.0.0"),(socket.AF_INET6,"::")):
        for kind in (socket.SOCK_DGRAM,socket.SOCK_STREAM):
            try:
                with socket.socket(family,kind) as sock:
                    if family==socket.AF_INET6:
                        sock.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_V6ONLY,1)
                    sock.bind((addr,port))
            except OSError as e:
                if family==socket.AF_INET6 and e.errno in (97,93):
                    continue
                return False
    return True
def choose_port(proto):
    raw=input("新节点端口（回车随机 20000-60000）: ").strip()
    if raw:
        try:port=int(raw)
        except ValueError:fail("端口必须是数字")
        if not 1024<=port<=65535:fail("端口范围 1024-65535")
        if not port_free(port,proto in ("hy2","tuic")):fail("端口已占用")
        return port
    for _ in range(200):
        port=secrets.randbelow(40001)+20000
        name=f"{proto}-{port}"
        if (port_free(port,proto in ("hy2","tuic"))
            and not (NODES/(name+".json")).exists()
            and not (UNITS/("singbox-landing-"+name+".service")).exists()):
            print("自动选择未占用端口:",port)
            return port
    fail("无法找到可用端口，请手动指定")
def valid_host(host):
    if not host or any(c in host for c in "/?#@ \\t\\r\\n"):return False
    try:
        ip=ipaddress.ip_address(host)
        return ip.version==4 and ip.is_global
    except ValueError:
        return bool(re.fullmatch(r"(?=.{1,253}$)[A-Za-z0-9-]+(?:\\.[A-Za-z0-9-]+)+",host))
def public_ip():
    host=input("落地机公网 IPv4 或域名（回车自动检测）: ").strip()
    if not host:
        for url in ("https://api.ipify.org","https://ipv4.icanhazip.com"):
            try:
                found=run(["curl","-4","-fsS","--noproxy","*","--connect-timeout","4","--max-time","8",url]).strip()
                if valid_host(found):
                    print("检测到公网 IPv4:",found)
                    host=found
                    break
            except (OSError,subprocess.CalledProcessError,subprocess.TimeoutExpired):
                continue
        if not host:fail("公网 IPv4 自动检测失败，请手动输入公网 IP 或域名")
    if not valid_host(host):fail("公网 IPv4 或域名格式不合法")
    return host
def make(proto,port,host):
    password=secrets.token_urlsafe(24);uid=str(uuid.uuid4());tlsconf=None
    if proto in ("hy2","tuic","anytls"):tlsconf=tls()
    if proto=="ss":
        method="aes-256-gcm"
        inbound={"type":"shadowsocks","tag":"in","listen":"::","listen_port":port,"method":method,"password":password}
        auth=base64.urlsafe_b64encode((method+":"+password).encode()).decode().rstrip("=")
        link=f"ss://{auth}@{host}:{port}#landing-ss"
    elif proto=="hy2":
        inbound={"type":"hysteria2","tag":"in","listen":"::","listen_port":port,"users":[{"password":password}],"tls":tlsconf}
        link=f"hysteria2://{password}@{host}:{port}?sni=singbox.local&insecure=1#landing-hy2"
    elif proto=="tuic":
        inbound={"type":"tuic","tag":"in","listen":"::","listen_port":port,"users":[{"uuid":uid,"password":password}],"congestion_control":"bbr","tls":dict(tlsconf,alpn=["h3"])}
        link=f"tuic://{uid}:{password}@{host}:{port}?sni=singbox.local&alpn=h3&insecure=1#landing-tuic"
    elif proto=="anytls":
        inbound={"type":"anytls","tag":"in","listen":"::","listen_port":port,"users":[{"password":password}],"tls":tlsconf}
        link=f"anytls://{password}@{host}:{port}?sni=singbox.local&insecure=1#landing-anytls"
    else:
        result=run(["sing-box","generate","reality-keypair"])
        m1=re.search(r"PrivateKey:\s*(\S+)",result);m2=re.search(r"PublicKey:\s*(\S+)",result)
        if not m1 or not m2:fail("Reality 密钥输出无法识别")
        sid=secrets.token_hex(4);sni="www.microsoft.com"
        inbound={"type":"vless","tag":"in","listen":"::","listen_port":port,"users":[{"uuid":uid,"flow":"xtls-rprx-vision"}],"tls":{"enabled":True,"server_name":sni,"reality":{"enabled":True,"handshake":{"server":sni,"server_port":443},"private_key":m1.group(1),"short_id":[sid]}}}
        link=f"vless://{uid}@{host}:{port}?encryption=none&security=reality&sni={sni}&fp=chrome&pbk={m2.group(1)}&sid={sid}&type=tcp&flow=xtls-rprx-vision#landing-reality"
    return {"log":{"level":"warn"},"inbounds":[inbound],"outbounds":[{"type":"direct","tag":"direct"}]},link
def add(proto,port,host):
    if proto not in PROTOS:fail("不支持的协议")
    if not 1024<=port<=65535:fail("端口范围 1024-65535")
    if not port_free(port,proto in ("hy2","tuic")):fail("端口被占用")
    name=f"{proto}-{port}";conf=NODES/(name+".json");linkfile=NODES/(name+".link")
    unit=UNITS/("singbox-landing-"+name+".service")
    if any(p.exists() for p in (conf,linkfile,unit)):fail("同名节点或服务已存在")
    config,link=make(proto,port,host)
    with tempfile.TemporaryDirectory(prefix="landing-preflight-") as d:
        p=pathlib.Path(d)/"config.json";p.write_text(json.dumps(config));run(["sing-box","check","-c",str(p)])
    print("预检查通过，自动创建独立节点；不会修改旧服务。")
    NODES.mkdir(parents=True,exist_ok=True);NODES.chmod(0o700)
    try:
        write(conf,config);linkfile.write_text(link+"\n");linkfile.chmod(0o600)
        service="[Unit]\nDescription=Isolated sing-box landing "+name+"\nAfter=network-online.target\nWants=network-online.target\n[Service]\nType=simple\nExecStart="+shutil.which("sing-box")+" run -c "+str(conf)+"\nRestart=on-failure\nRestartSec=3\nNoNewPrivileges=true\n[Install]\nWantedBy=multi-user.target\n"
        unit.write_text(service);unit.chmod(0o644)
        run(["systemctl","daemon-reload"]);run(["systemctl","enable","--now",unit.name])
        time.sleep(2)
        run(["systemctl","is-active","--quiet",unit.name])
    except Exception:
        subprocess.run(["systemctl","disable","--now",unit.name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        unit.unlink(missing_ok=True);conf.unlink(missing_ok=True);linkfile.unlink(missing_ok=True)
        subprocess.run(["systemctl","daemon-reload"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        raise
    print("新增成功:",name,"服务:",unit.name)
    print("节点链接已保存在",linkfile,"(含密码，请勿公开)")
    print("\\n===== 可复制的节点链接 =====")
    print(link)
    print("===== 链接结束 =====\\n")
    print("也可随时查看: cat",linkfile)
    print("请在云防火墙放行",("UDP" if proto in ("hy2","tuic") else "TCP"),port)
def main():
    if os.geteuid()!=0:fail("需要 root")
    for cmd in ("sing-box","systemctl","openssl"):
        if not shutil.which(cmd):fail("缺少 "+cmd)
    print("独立落地节点生成器（不会修改已有 sing-box/hysteria 服务）")
    while True:
        print("\n1 SS\n2 HY2\n3 TUIC\n4 VLESS Reality\n5 AnyTLS\n6 查看新增节点\n0 退出")
        choice=input("选择: ").strip()
        if choice=="0":return
        if choice=="6":
            for p in sorted(NODES.glob("*.json")):print(p.stem)
            continue
        proto={"1":"ss","2":"hy2","3":"tuic","4":"reality","5":"anytls"}.get(choice)
        if not proto:continue
        try:
            port=choose_port(proto)
            host=public_ip()
            add(proto,port,host)
        except (RuntimeError,ValueError,subprocess.CalledProcessError,OSError) as e:print("失败:",str(e)[:700])
if __name__=="__main__":
    try:main()
    except (KeyboardInterrupt,EOFError):print("\n已退出")
