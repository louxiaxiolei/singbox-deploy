#!/usr/bin/env python3
import pathlib,os,sys,shutil,time,subprocess
if os.geteuid()!=0: sys.exit("需要 root")
src=pathlib.Path(__file__).with_name("relay_manager.py")
target=pathlib.Path("/usr/local/lib/singbox-deploy/install.sh")
module=target.with_name("relay_manager.py")
if not src.is_file() or not target.is_file(): sys.exit("未发现原 LM 安装或增强模块；未修改")
s=target.read_text()
if "13. 中转管理" in s:
    shutil.copy2(src,module);module.chmod(0o700);print("菜单已存在，模块已更新");sys.exit(0)
needle="12. 故障诊断\\n0. 退出"
case="12) diagnose;; 0) exit;;"
if needle not in s or case not in s:sys.exit("原菜单结构不匹配，拒绝修改")
new=s.replace(needle,"12. 故障诊断\\n13. 中转管理\\n0. 退出",1).replace(case,"12) diagnose;; 13) python3 /usr/local/lib/singbox-deploy/relay_manager.py;; 0) exit;;",1)
backup=target.with_name("install.sh.before-relay-"+time.strftime("%Y%m%d-%H%M%S"))
shutil.copy2(target,backup);backup.chmod(0o600)
pending=target.with_name(".install.sh.relay-pending")
if pending.exists():sys.exit("临时文件已存在，拒绝覆盖")
try:
    pending.write_text(new);pending.chmod(0o700)
    subprocess.run(["bash","-n",str(pending)],check=True)
    shutil.copy2(src,module);module.chmod(0o700)
    os.replace(pending,target)
except Exception:
    pending.unlink(missing_ok=True);raise
print("LM 中转菜单安装成功；未重启代理。原脚本备份:",backup)
