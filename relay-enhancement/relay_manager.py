#!/usr/bin/env python3
"""Opt-in singbox-deploy relay manager. Only touches /etc/singbox-deploy/nodes."""
import base64,copy,getpass,json,os,pathlib,secrets,shutil,socket,subprocess,sys,tempfile,time,urllib.parse
BASE=pathlib.Path("/etc/singbox-deploy"); NODES=BASE/"nodes"; STORE=BASE/"landings.json"; BACKUPS=BASE/"relay-backups"
def abort(msg): raise RuntimeError(msg)
def load(p,default=None): return json.loads(p.read_text()) if p.exists() else default
def save(p,data):
    p.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix=".relay-",dir=str(p.parent))
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,"w") as f:
            json.dump(data,f,ensure_ascii=False,indent=2);f.write("\n");f.flush();os.fsync(f.fileno())
        os.replace(name,p)
    finally:
        if os.path.exists(name):os.unlink(name)
def ask(s):return input(s+": ").strip()
def confirm(s):return ask(s+" (输入 YES 确认)")=="YES"
def parse(raw,tag):
    u=urllib.parse.urlsplit(raw.strip());scheme=u.scheme.lower()
    if scheme not in ("ss","hy2","hysteria2","tuic","vless","anytls"):abort("协议不支持")
    host=u.hostname
    try:port=u.port
    except ValueError:abort("端口无效")
    if not host or not port:abort("缺少地址或端口")
    q={k.lower():v[-1] for k,v in urllib.parse.parse_qs(u.query).items()}
    ob={"tag":tag,"server":host,"server_port":port}
    tls={"enabled":True,"server_name":q.get("sni",host),"insecure":q.get("insecure",q.get("allow_insecure",q.get("allowinsecure","0"))).lower() in ("1","true")}
    if q.get("alpn"):tls["alpn"]=q["alpn"].split(",")
    if scheme in ("hy2","hysteria2","anytls"):
        pw=urllib.parse.unquote(u.username or "")
        if not pw:abort("缺少密码")
        ob.update(type="hysteria2" if scheme!="anytls" else "anytls",password=pw,tls=tls)
        if scheme=="anytls" and q.get("security","tls") not in ("tls",""):abort("AnyTLS 仅支持 TLS")
        if scheme!="anytls" and q.get("obfs"):ob["obfs"]={"type":q["obfs"],"password":q.get("obfs-password","")}
    elif scheme=="tuic":
        uid=urllib.parse.unquote(u.username or "");pw=urllib.parse.unquote(u.password or "")
        if not uid or not pw:abort("TUIC 缺少 UUID 或密码")
        ob.update(type="tuic",uuid=uid,password=pw,congestion_control=q.get("congestion_control","bbr"),tls=tls)
    elif scheme=="vless":
        if q.get("security")!="reality" or q.get("type","tcp")!="tcp" or not q.get("pbk"):abort("仅支持 VLESS TCP Reality（需 pbk）")
        uid=urllib.parse.unquote(u.username or "")
        if not uid:abort("缺少 UUID")
        ob.update(type="vless",uuid=uid,tls={"enabled":True,"server_name":q.get("sni",host),"reality":{"enabled":True,"public_key":q["pbk"],"short_id":q.get("sid","")}})
        if q.get("flow"):ob["flow"]=q["flow"]
    else:
        if q.get("plugin"):abort("不支持 SS plugin")
        auth=urllib.parse.unquote(u.netloc.rsplit("@",1)[0]) if "@" in u.netloc else ""
        if ":" not in auth:
            try:auth=base64.urlsafe_b64decode(auth+"="*(-len(auth)%4)).decode()
            except Exception:abort("SS 认证格式无效")
        method,sep,pw=auth.partition(":")
        if not sep or not method or not pw:abort("SS 认证不完整")
        ob.update(type="shadowsocks",method=method,password=pw)
    return ob
def items():
    out=[]
    for p in sorted(NODES.glob("*.json")):
        try:
            c=load(p)
            if c.get("inbounds"):out.append((p,c))
        except (ValueError,AttributeError):pass
    return out
def choose(options,heading):
    if not options:abort("没有可选项目："+heading)
    print(heading)
    for i,(name,_) in enumerate(options,1):print(f"{i}. {name}")
    v=ask("序号")
    if not v.isdigit() or not 1<=int(v)<=len(options):abort("无效序号")
    return options[int(v)-1][1]
def node():
    return choose([(p.stem,(p,c)) for p,c in items()],"选择本项目节点")
def landing():
    return choose([(k,(k,copy.deepcopy(v))) for k,v in sorted(load(STORE,{}).items())],"选择落地")
def check(p):
    r=subprocess.run(["sing-box","check","-c",str(p)],capture_output=True,text=True)
    if r.returncode:abort("配置检查失败："+(r.stderr or r.stdout)[-800:])
def test(ob):
    with socket.socket() as s:s.bind(("127.0.0.1",0));port=s.getsockname()[1]
    cfg={"log":{"level":"warn"},"inbounds":[{"type":"mixed","tag":"test","listen":"127.0.0.1","listen_port":port}],"outbounds":[ob],"route":{"final":ob["tag"]}}
    with tempfile.TemporaryDirectory(prefix="relay-test-") as d:
        p=pathlib.Path(d)/"config.json";save(p,cfg);check(p)
        proc=subprocess.Popen(["sing-box","run","-c",str(p)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            time.sleep(1)
            if proc.poll() is not None:abort("测试进程启动失败")
            r=subprocess.run(["curl","-4","-fsS","--connect-timeout","6","--max-time","22","-x",f"http://127.0.0.1:{port}","https://api.ipify.org"],capture_output=True,text=True)
            if r.returncode:abort("落地连接失败："+r.stderr[-400:])
            ip=r.stdout.strip()
            if not ip:abort("出口 IP 为空")
            print("落地出口 IP:",ip)
        finally:
            proc.terminate()
            try:proc.wait(timeout=4)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()
def apply(p,new):
    service="singbox-deploy-"+p.stem+".service"
    if subprocess.run(["systemctl","is-active","--quiet",service]).returncode:abort("仅支持正在运行的 systemd 独立节点服务")
    BACKUPS.mkdir(parents=True,exist_ok=True)
    backup=BACKUPS/(p.stem+"-"+time.strftime("%Y%m%d-%H%M%S")+"-"+secrets.token_hex(3)+".json")
    shutil.copy2(p,backup);backup.chmod(0o600)
    save(p,new)
    try:
        subprocess.run(["systemctl","restart",service],check=True,timeout=20)
        time.sleep(2)
        subprocess.run(["systemctl","is-active","--quiet",service],check=True)
    except Exception:
        shutil.copy2(backup,p)
        subprocess.run(["systemctl","restart",service],timeout=20)
        abort("切换失败，已尝试回滚。请检查服务："+service)
    print("切换完成；请用客户端验证真实出口。备份：",backup)
def add():
    name=ask("落地名称（字母数字下划线横线）")
    if not name or len(name)>48 or not all(c.isascii() and (c.isalnum() or c in "_-") for c in name):abort("名称不合法")
    db=load(STORE,{})
    if name in db:abort("名称已存在")
    ob=parse(getpass.getpass("落地节点 URI（隐藏输入）: "),"relay-"+name)
    print("解析成功:",ob["type"],ob["server"],ob["server_port"])
    if ob.get("tls",{}).get("insecure"):print("警告：TLS 跳过证书验证")
    db[name]=ob;save(STORE,db);print("已保存，尚未修改任何节点")
def attach():
    p,c=node()
    name,ob=landing()
    attach_selected(p,c,name,ob)

def wizard():
    print("\n=== 中转配置向导 ===")
    print("步骤 1/3：选择要走落地的现有节点")
    p,c=node()
    current=c.get("route",{}).get("final","默认直连")
    print("当前出口:",current)
    if current.startswith("relay-"):
        print("该节点已配置中转；为避免覆盖，先使用「查看路由」核对。如需更换，请先恢复直连。")
        return
    db=load(STORE,{})
    print("\n步骤 2/3：选择落地")
    if db:
        print("1. 使用已保存的落地")
        print("2. 添加新的落地 URI")
        mode=ask("请选择 [1]")
        if mode in ("","1"):
            name,ob=landing()
        elif mode=="2":
            add()
            name,ob=landing()
        else:
            abort("无效选择")
    else:
        print("尚无落地，先添加一次（URI 隐藏输入）")
        add()
        name,ob=landing()
    print("\n步骤 3/3：自动测试、验证配置并确认切换")
    print("入站节点:",p.stem,"落地:",name)
    attach_selected(p,c,name,ob)

def batch_wizard():
    print("\n=== 批量配置中转（同一个落地） ===")
    available=items()
    if not available:abort("没有本项目创建的节点")
    print("选择多个节点，输入序号并以空格分隔，例如 1 2 3")
    for i,(p,c) in enumerate(available,1):
        print(f"{i}. {p.stem} | 当前出口: {c.get('route',{}).get('final','默认直连')}")
    raw=ask("节点序号（空格分隔）")
    tokens=raw.split()
    if not tokens or any(not t.isdigit() or not 1<=int(t)<=len(available) for t in tokens):
        abort("无效序号；未修改节点")
    indexes=list(dict.fromkeys(int(t)-1 for t in tokens))
    selected=[available[i] for i in indexes]
    print("\n选择一个统一落地")
    if not load(STORE,{}):
        print("尚未添加落地 URI")
        add()
    else:
        print("如需新落地，可先在高级管理中添加")
    name,ob=landing()
    prepared=[]
    for p,c in selected:
        route=c.get("route",{})
        if route.get("rules") or route.get("rule_set") or route.get("final") not in (None,"direct","direct-out"):
            abort(f"{p.stem} 存在自定义路由或已配置中转；未修改任何节点")
        if any(x.get("tag")==ob["tag"] for x in c.get("outbounds",[])):
            abort(f"{p.stem} 出站标签冲突；未修改任何节点")
        service="singbox-deploy-"+p.stem+".service"
        if subprocess.run(["systemctl","is-active","--quiet",service]).returncode:
            abort(f"{service} 未运行；未修改任何节点")
        new=copy.deepcopy(c)
        new.setdefault("outbounds",[]).append(copy.deepcopy(ob))
        new["route"]=dict(route,final=ob["tag"])
        with tempfile.TemporaryDirectory(prefix="relay-check-") as d:
            q=pathlib.Path(d)/"check.json";save(q,new);check(q)
        prepared.append((p,new))
    print("\n所有节点配置检查通过。测试落地连接（仅测试一次）")
    test(ob)
    print("将切换以下节点：")
    for p,_ in prepared:print(" -",p.stem)
    print("统一落地：",name)
    if not confirm(f"确认切换以上 {len(prepared)} 个节点？每个节点会短暂重启"):
        print("已取消，未修改节点");return
    succeeded=[]
    failed=[]
    for p,new in prepared:
        try:
            print("正在切换：",p.stem)
            apply(p,new)
            succeeded.append(p.stem)
        except (RuntimeError,OSError,subprocess.SubprocessError) as e:
            failed.append((p.stem,str(e)))
            print("失败：",p.stem,str(e))
            print("已停止后续切换，避免继续影响其他节点")
            break
    print("\n批量执行结果：成功",len(succeeded),"失败",len(failed),
          "未处理",len(prepared)-len(succeeded)-len(failed))
    if succeeded:print("已切换：",", ".join(succeeded))
    if failed:
        print("失败节点：",failed[0][0],"原因：",failed[0][1])
        print("已成功切换的节点不会自动恢复；可在菜单中逐个恢复直连。")
    else:
        print("全部切换完成；请逐个通过客户端验证出口 IP。")

def attach_selected(p,c,name,ob):
    route=c.get("route",{})
    if route.get("rules") or route.get("rule_set") or route.get("final") not in (None,"direct","direct-out"):
        abort("已有自定义路由，请先恢复或人工检查")
    if any(x.get("tag")==ob["tag"] for x in c.get("outbounds",[])):
        abort("出站标签冲突")
    print("测试落地连通性（不会修改现有节点）")
    test(ob)
    new=copy.deepcopy(c)
    new.setdefault("outbounds",[]).append(ob)
    new["route"]=dict(route,final=ob["tag"])
    with tempfile.TemporaryDirectory() as d:
        p2=pathlib.Path(d)/"check.json"
        save(p2,new)
        check(p2)
    print("配置检查通过；只有输入 YES 才会切换。")
    if confirm(f"切换 {p.stem} 至 {name}？将短暂重启此节点"):
        apply(p,new)
        print("下一步：客户端保持原节点链接，检查出口 IP 是否为落地 IP。")
    else:
        print("已取消，现有节点未修改。")

def detach():
    p,c=node();tag=c.get("route",{}).get("final","")
    if not tag.startswith("relay-"):abort("此节点未使用本模块的中转")
    new=copy.deepcopy(c);new["outbounds"]=[o for o in c["outbounds"] if o.get("tag")!=tag]
    new["route"]["final"]="direct" if any(o.get("tag")=="direct" for o in new["outbounds"]) else "direct-out"
    with tempfile.TemporaryDirectory() as d:
        q=pathlib.Path(d)/"check.json";save(q,new);check(q)
    if confirm(f"恢复 {p.stem} 直连？将短暂重启此节点"):apply(p,new)
def show():
    for name,ob in sorted(load(STORE,{}).items()):print("落地",name,ob["type"],ob["server"],ob["server_port"])
    for p,c in items():print("节点",p.stem,"出口",c.get("route",{}).get("final","默认直连"))
def delete():
    name,_=landing()
    if any(c.get("route",{}).get("final")=="relay-"+name for _,c in items()):abort("落地仍在使用")
    if confirm("删除落地 "+name):
        db=load(STORE,{});del db[name];save(STORE,db)
def main():
    if os.geteuid()!=0:abort("需要 root")
    if not shutil.which("sing-box") or not shutil.which("curl"):abort("需要 sing-box 和 curl")
    while True:
        print("\n=== 中转出口管理 ===\n1 添加落地 URI (SS/HY2/TUIC/VLESS Reality/AnyTLS)\n2 查看路由\n3 为已有节点设置落地\n4 恢复直连\n5 删除落地\n6 一键配置中转（推荐）\n7 批量配置多个节点使用同一落地\n0 返回")
        v=ask("请选择")
        if v=="0":return
        try:{"1":add,"2":show,"3":attach,"4":detach,"5":delete,"6":wizard,"7":batch_wizard}[v]()
        except KeyError:print("无效选项")
        except (RuntimeError,ValueError,OSError,subprocess.SubprocessError) as e:print("失败：",e)
if __name__=="__main__":
    try:
        if len(sys.argv)>1 and sys.argv[1]=="--wizard":
            if os.geteuid()!=0:abort("需要 root")
            wizard()
        elif len(sys.argv)>1 and sys.argv[1]=="--batch":
            if os.geteuid()!=0:abort("需要 root")
            batch_wizard()
        elif len(sys.argv)>1 and sys.argv[1]=="--restore":
            if os.geteuid()!=0:abort("需要 root")
            detach()
        else:
            main()
    except (KeyboardInterrupt,EOFError):print("\n退出")
