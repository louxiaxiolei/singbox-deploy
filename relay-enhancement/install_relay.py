#!/usr/bin/env python3
"""Install an independent relay-manager command; never patch the original LM."""
import os,pathlib,shutil,subprocess,sys,time
if os.geteuid()!=0:sys.exit("需要 root")
src=pathlib.Path(__file__).with_name("relay_manager.py")
lm=pathlib.Path("/usr/local/lib/singbox-deploy/install.sh")
dest=pathlib.Path("/usr/local/bin/relay-manager")
if not src.is_file() or not lm.is_file():sys.exit("未发现原 LM 或模块；未修改")
subprocess.run([sys.executable,"-m","py_compile",str(src)],check=True)
if dest.exists():
    backup=dest.with_name("relay-manager.before-"+time.strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(dest,backup);backup.chmod(0o600)
    print("旧模块备份:",backup)
temp=dest.with_name(".relay-manager-pending")
if temp.exists():sys.exit("发现残留临时文件；未修改")
try:
    shutil.copy2(src,temp);temp.chmod(0o700)
    os.replace(temp,dest)
finally:
    temp.unlink(missing_ok=True)
print("安装完成：执行 relay-manager 进入中转管理。原 LM 未修改，代理服务未重启。")
