#!/usr/bin/env python3
"""Manage only isolated landing services created by landing_manager.py."""
import pathlib,subprocess,shutil,datetime,tarfile,os,sys
BASE=pathlib.Path("/etc/singbox-deploy-v2")
NODES=BASE/"nodes"
UNITS=pathlib.Path("/etc/systemd/system")
BACKUPS=BASE/"backups"
def run(*args):
    return subprocess.run(args,check=True)
def entries():
    result=[]
    for cfg in sorted(NODES.glob("*.json")):
        name=cfg.stem
        unit=UNITS/("singbox-landing-"+name+".service")
        if unit.is_file() and (NODES/(name+".link")).is_file():
            result.append((name,cfg,unit))
    return result
def choose():
    e=entries()
    if not e:
        print("没有由本项目创建的独立落地节点");return None
    for i,(name,_,unit) in enumerate(e,1):
        r=subprocess.run(["systemctl","is-active",unit.name],capture_output=True,text=True)
        print(f"{i}. {name} | {r.stdout.strip()}")
    raw=input("选择序号（回车返回）: ").strip()
    if not raw:return None
    if not raw.isdigit() or not 1<=int(raw)<=len(e):raise RuntimeError("序号无效")
    return e[int(raw)-1]
def backup(name,cfg,unit):
    BACKUPS.mkdir(parents=True,exist_ok=True)
    BACKUPS.chmod(0o700)
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest=BACKUPS/(name+"-"+stamp+".tar.gz")
    with tarfile.open(dest,"x:gz") as t:
        for p in (cfg,NODES/(name+".link"),unit):
            t.add(p,arcname=p.relative_to("/"))
    dest.chmod(0o600)
    print("已备份（含凭据）:",dest)
def main():
    if os.geteuid()!=0:raise RuntimeError("需要 root")
    if not shutil.which("systemctl"):raise RuntimeError("需要 systemd")
    while True:
        print("\n=== 落地节点管理 ===\n1 查看节点状态\n2 停用落地节点\n3 启用落地节点\n4 删除落地节点（先备份）\n0 返回")
        choice=input("选择: ").strip()
        if choice=="0":return
        if choice=="1":
            choose();continue
        if choice not in ("2","3","4"):
            print("无效选项");continue
        selected=choose()
        if not selected:continue
        name,cfg,unit=selected
        if choice=="2":
            print("警告：若中转机仍指向此落地节点，会导致其代理连接失败。")
            if input("输入 STOP 确认停用: ")!="STOP":continue
            run("systemctl","disable","--now",unit.name)
        elif choice=="3":
            run("sing-box","check","-c",str(cfg))
            run("systemctl","enable","--now",unit.name)
        else:
            print("警告：删除仅限本项目独立创建的落地节点；请先恢复所有使用它的中转机。")
            if input("输入 DELETE 确认删除: ")!="DELETE":continue
            backup(name,cfg,unit)
            run("systemctl","disable","--now",unit.name)
            unit.unlink()
            cfg.unlink()
            (NODES/(name+".link")).unlink()
            run("systemctl","daemon-reload")
        print("操作完成")
if __name__=="__main__":
    try:main()
    except (RuntimeError,OSError,subprocess.CalledProcessError,EOFError,KeyboardInterrupt) as e:
        print("操作中止:",e,file=sys.stderr);sys.exit(1)
