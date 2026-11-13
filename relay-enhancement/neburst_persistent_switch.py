#!/usr/bin/env python3
"""Persistent Neburst relay: stage -> activate (600s safety) -> keep forever; restore manually."""
import argparse,datetime,hashlib,json,os,pathlib,subprocess,sys
ROOT=pathlib.Path('/root/neburst-relay-preflight')
LIVE=pathlib.Path('/etc/sing-box/config.json')
STATE=ROOT/'persistent-state.json'
TIMER='neburst-persistent-rollback'
EXPECTED={'hy2-in':('hysteria2',26071),'tuic-in':('tuic',20960),'vless-in':('vless',17465),'anytls-in':('anytls',12517)}
def run(*cmd):return subprocess.run(cmd,text=True,capture_output=True)
def sha(b):return hashlib.sha256(b).hexdigest()
def abort(s):raise RuntimeError(s)
def write(path,data):
    tmp=path.with_name(path.name+'.new')
    with open(tmp,'wb') as f:
        os.fchmod(f.fileno(),0o600);f.write(data);f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)
def state():return json.loads(STATE.read_text()) if STATE.exists() else None
def save(s):write(STATE,(json.dumps(s,indent=2)+'\n').encode())
def service_check():
    r=run('systemctl','show','sing-box','-p','ExecStart','--value','--no-pager')
    if r.returncode or '/etc/sing-box/config.json' not in r.stdout:abort('服务启动配置路径不匹配')
def check_candidate(original,candidate):
    a=json.loads(original);b=json.loads(candidate)
    if {i.get('tag'):(i.get('type'),i.get('listen_port')) for i in a.get('inbounds',[])}!=EXPECTED:abort('原入站不符合预期')
    if len(a.get('outbounds',[]))!=1 or a['outbounds'][0].get('type')!='direct' or a['outbounds'][0].get('tag')!='direct-out':abort('原出站变化')
    if (a.get('route') or {}).get('rules') or (a.get('route') or {}).get('final') not in (None,'direct-out'):abort('原路由变化')
    if b.get('inbounds')!=a.get('inbounds'):abort('候选修改入站')
    outs=b.get('outbounds',[])
    if len(outs)!=2 or outs[0]!=a['outbounds'][0]:abort('候选出站异常')
    h=outs[1]
    if not (h.get('tag')=='akile-hy2-out' and h.get('type')=='hysteria2' and h.get('server')=='45.202.246.227' and h.get('server_port')==21460 and h.get('password') and h.get('tls',{}).get('server_name')=='singbox.local'):abort('落地参数不符')
    expected=json.loads(original)
    expected['outbounds'].append(h)
    expected['route']={'rules':[{'inbound':list(EXPECTED),'action':'route','outbound':'akile-hy2-out'}],'final':'direct-out'}
    if b!=expected:abort('候选含未授权改动')
def timer_stop():
    run('systemctl','stop',TIMER+'.timer')
def get_candidate(path):
    p=pathlib.Path(path).resolve()
    if p.parent!=ROOT or not p.name.startswith('config.candidate-') or not p.is_file():abort('候选文件不在预检目录')
    return p,p.read_bytes()
def preflight(args):
    service_check()
    s=state()
    if s and s['status'] in ('pending','persistent'):abort('已在中转状态，请先检查')
    original=LIVE.read_bytes();p,candidate=get_candidate(args.candidate)
    check_candidate(original,candidate)
    if not any(b.read_bytes()==original for b in ROOT.glob('config.backup-*.json')):abort('缺少匹配的原配置备份')
    r=run('sing-box','check','-c',str(p))
    if r.returncode:abort('sing-box check 失败: '+r.stderr[-500:])
    print('PASS 原始配置和候选配置匹配；未修改或重启')
    print('原 SHA256:',sha(original),'候选 SHA256:',sha(candidate))
def activate(args):
    preflight(args)
    if not args.confirm_disruption:abort('必须显式授权重启')
    original=LIVE.read_bytes();p,candidate=get_candidate(args.candidate)
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup=ROOT/('persistent-backup-'+stamp+'.json')
    write(backup,original)
    s={'status':'pending','backup':str(backup),'original_sha256':sha(original),'candidate_sha256':sha(candidate)}
    save(s)
    r=run('systemd-run','--unit='+TIMER,'--on-active=600s','/usr/bin/python3',str(pathlib.Path(__file__).resolve()),'restore','--automatic')
    if r.returncode:
        STATE.unlink();abort('回滚计时器启动失败，正式配置未修改: '+r.stderr[-500:])
    try:
        if LIVE.read_bytes()!=original:abort('原配置已被其他程序修改')
        write(LIVE,candidate)
        r=run('systemctl','restart','sing-box.service')
        if r.returncode or run('systemctl','is-active','--quiet','sing-box.service').returncode:abort('新配置启动失败: '+r.stderr[-500:])
    except Exception:
        restore(argparse.Namespace(automatic=True,confirm_disruption=True))
        raise
    print('已切换，600秒安全窗口。验证通过后运行 keep，永久保留；否则自动恢复。')
def keep(args):
    s=state()
    if not s or s['status']!='pending':abort('没有待确认的切换')
    if sha(LIVE.read_bytes())!=s['candidate_sha256']:abort('正式配置不匹配候选')
    if run('systemctl','is-active','--quiet','sing-box.service').returncode:abort('服务未运行')
    # Mark persistent first, so an already-triggering rollback will not overwrite it.
    s['status']='persistent';save(s)
    timer_stop()
    print('长期中转模式已启用；没有定时回滚。以后手动执行 restore。')
def restore(args):
    s=state()
    if not s:abort('没有备份状态')
    if s['status'] not in ('pending','persistent'):abort('当前状态不是中转')
    if args.automatic and s['status']!='pending':
        print('长期模式已确认，跳过过期回滚');return
    if not args.automatic and not args.confirm_disruption:abort('手动恢复需 --confirm-disruption')
    backup=pathlib.Path(s['backup'])
    original=backup.read_bytes()
    if sha(original)!=s['original_sha256']:abort('备份校验失败')
    current=LIVE.read_bytes()
    if sha(current) not in (s['candidate_sha256'],s['original_sha256']):abort('正式配置被其他程序修改，拒绝覆盖')
    if sha(current)!=s['original_sha256']:
        write(LIVE,original)
        r=run('systemctl','restart','sing-box.service')
        if r.returncode:abort('原配置已恢复，但服务重启失败: '+r.stderr[-500:])
    s['status']='restored';save(s)
    timer_stop()
    print('已恢复 Neburst 原始直连配置，原始备份仍保留')
def status(args):
    s=state()
    print('状态:',s['status'] if s else '未初始化')
    print('当前配置 SHA256:',sha(LIVE.read_bytes()))
    print('服务:',run('systemctl','is-active','sing-box').stdout.strip())
    print('计时器:',run('systemctl','is-active',TIMER+'.timer').stdout.strip())
def main():
    if os.geteuid()!=0:abort('必须 root')
    ROOT.mkdir(mode=0o700,parents=True,exist_ok=True)
    p=argparse.ArgumentParser()
    sub=p.add_subparsers(dest='cmd',required=True)
    for name in ('preflight','activate'):
        q=sub.add_parser(name);q.add_argument('--candidate',required=True)
        if name=='activate':q.add_argument('--confirm-disruption',action='store_true')
    sub.add_parser('keep')
    q=sub.add_parser('restore');q.add_argument('--automatic',action='store_true');q.add_argument('--confirm-disruption',action='store_true')
    sub.add_parser('status')
    args=p.parse_args()
    {'preflight':preflight,'activate':activate,'keep':keep,'restore':restore,'status':status}[args.cmd](args)
if __name__=='__main__':
    try:main()
    except Exception as e:print('ERROR:',e,file=sys.stderr);sys.exit(1)
