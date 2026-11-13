#!/usr/bin/env python3
"""Landing-side read-only audit. Never writes or restarts services."""
import json,os,pathlib,subprocess
def run(*args):
    try:
        p=subprocess.run(args,capture_output=True,text=True,timeout=8)
        return p.stdout.strip() if p.returncode==0 else "不可用"
    except (OSError,subprocess.TimeoutExpired):return "不可用"
print("=== 落地机安全检查（只读）===")
print("主机:",run("hostname"))
print("sing-box:",run("sing-box","version").splitlines()[:1])
print("相关服务:")
for line in run("systemctl","list-units","--all","--type=service","--no-legend","--no-pager").splitlines():
    if any(x in line.lower() for x in ("sing-box","singbox","hysteria","xray")):
        print(" ",line[:180])
print("配置位置（只显示存在性，不读取密钥）:")
for path in ("/etc/sing-box/config.json","/etc/singbox-deploy/nodes","/etc/hysteria/config.yaml","/etc/hysteria/config.json"):
    p=pathlib.Path(path)
    print(" ",path,"存在" if p.exists() else "不存在")
print("监听端口（仅数字）:")
for line in run("ss","-H","-lntu").splitlines()[:80]:
    cols=line.split()
    if len(cols)>4:print(" ",cols[0],cols[4])
print("本工具不会安装、重启或修改任何服务。")
