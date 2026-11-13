#!/usr/bin/env python3
"""Neburst four-inbound switch with timed rollback. No changes unless 'activate' is explicitly run."""
import argparse,datetime,hashlib,json,os,pathlib,shutil,subprocess,sys
LIVE=pathlib.Path('/etc/sing-box/config.json')
ROOT=pathlib.Path('/root/neburst-relay-preflight')
STATE=ROOT/'switch-state.json'
EXPECTED={'hy2-in':('hysteria2',26071),'tuic-in':('tuic',20960),'vless-in':('vless',17465),'anytls-in':('anytls',12517)}
TIMER='neburst-relay-auto-rollback'
def call(*args):return subprocess.run(args,text=True,capture_output=True)
def fail(msg):raise RuntimeError(msg)
def digest(b):return hashlib.sha256(b).hexdigest()
def atomic_write(path,data):
    tmp=path.with_name(path.name+'.tmp')
    with open(tmp,'wb') as f:
        os.fchmod(f.fileno(),0o600);f.write(data);f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)
def load_state():
    if not STATE.exists():fail('没有待处理的切换状态')
    return json.loads(STATE.read_text())
def check_service():
    result=call('systemctl','show','sing-box','-p','ExecStart','--value','--no-pager')
    if result.returncode or '/etc/sing-box/config.json' not in result.stdout:fail('sing-box.service 配置路径不符合预期')
def validate(live,cand):
    base=json.loads(live);new=json.loads(cand)
    actual={x.get('tag'):(x.get('type'),x.get('listen_port')) for x in base.get('inbounds',[])}
    if actual!=EXPECTED:fail('当前四入站已变化，停止')
    if len(base.get('outbounds',[]))!=1 or base['outbounds'][0].get('tag')!='direct-out' or base['outbounds'][0].get('type')!='direct':fail('原始出站变化')
    if (base.get('route') or {}).get('rules'):fail('原始路由已有规则')
    if new.get('inbounds')!=base.get('inbounds'):fail('候选配置修改了入站')
    expected=json.loads(live)
    outs=new.get('outbounds',[])
    if len(outs)!=2 or outs[0]!=base['outbounds'][0]:fail('候选出站异常')
    hy=outs[1]
    if not (hy.get('type')=='hysteria2' and hy.get('tag')=='akile-hy2-out' and hy.get('server')=='45.202.246.227' and hy.get('server_port')==21460 and hy.get('password') and hy.get('tls',{}).get('server_name')=='singbox.local'):fail('落地节点不符合预期')
    expected['outbounds'].append(hy)
    expected['route']={'rules':[{'inbound':list(EXPECTED),'action':'route','outbound':'akile-hy2-out'}],'final':'direct-out'}
    if new!=expected:fail('候选配置存在其他改动')
def prepare(args):
    check_service()
    if STATE.exists():fail('存在切换状态，先核查')
    cand=pathlib.Path(args.candidate).resolve()
    if not cand.is_file() or cand.parent!=ROOT:fail('候选文件必须来自预检目录')
    live=LIVE.read_bytes();candidate=cand.read_bytes()
    validate(live,candidate)
    backups=sorted(ROOT.glob('config.backup-*.json'))
    if not any(b.read_bytes()==live for b in backups):fail('找不到与正式配置一致的预检备份')
    r=call('sing-box','check','-c',str(cand))
    if r.returncode:fail('候选配置检查失败: '+r.stderr[-700:])
    print('PASS: 入站完全不变、仅新增落地出站与四入站路由')
    print('PASS: 原配置匹配备份；候选 sing-box check 通过')
    print('候选文件:',cand)
    print('正式配置 SHA256:',digest(live))
    print('候选配置 SHA256:',digest(candidate))
    print('未修改正式配置，未重启服务')
def activate(args):
    check_service()
    if STATE.exists():fail('已有待确认切换，拒绝重复操作')
    cand=pathlib.Path(args.candidate).resolve()
    if not cand.is_file() or cand.parent!=ROOT:fail('候选文件不在预检目录')
    live=LIVE.read_bytes();candidate=cand.read_bytes()
    validate(live,candidate)
    if not any(p.read_bytes()==live for p in ROOT.glob('config.backup-*.json')):fail('预检备份与现配置不一致')
    r=call('sing-box','check','-c',str(cand))
    if r.returncode:fail('候选检查失败: '+r.stderr[-700:])
    if not args.confirm_disruption:fail('必须显式添加 --confirm-disruption 才会重启')
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup=ROOT/('switch-backup-'+stamp+'.json')
    atomic_write(backup,live)
    state={'backup':str(backup),'original_sha256':digest(live),'candidate_sha256':digest(candidate),'status':'pending'}
    atomic_write(STATE,json.dumps(state).encode())
    # Timer is armed BEFORE changing config, so SSH disconnection does not defeat rollback.
    r=call('systemd-run','--unit='+TIMER,'--on-active=180s','/usr/bin/python3',str(pathlib.Path(__file__).resolve()),'rollback','--automatic')
    if r.returncode:
        STATE.unlink(missing_ok=True);fail('自动回滚计时器创建失败，未切换: '+r.stderr[-600:])
    try:
        if LIVE.read_bytes()!=live:fail('正式配置在切换期间被外部修改')
        atomic_write(LIVE,candidate)
        r=call('systemctl','restart','sing-box.service')
        if r.returncode:fail('重启失败: '+r.stderr[-600:])
        r=call('systemctl','is-active','--quiet','sing-box.service')
        if r.returncode:fail('服务未处于 active')
        print('服务已启动。180 秒内验证四节点并运行 confirm；否则自动回滚。')
        print('确认命令: python3 '+str(pathlib.Path(__file__).resolve())+' confirm')
    except Exception:
        rollback(argparse.Namespace(automatic=True))
        raise
def rollback(args):
    if not STATE.exists():
        print('无待回滚状态');return
    state=load_state()
    if state.get('status')!='pending':fail('状态不是 pending')
    backup=pathlib.Path(state['backup'])
    original=backup.read_bytes()
    if digest(original)!=state['original_sha256']:fail('备份校验失败，停止自动操作')
    current=LIVE.read_bytes()
    if digest(current) not in (state['original_sha256'],state['candidate_sha256']):fail('正式配置已被第三方修改，停止覆盖')
    if digest(current)!=state['original_sha256']:
        atomic_write(LIVE,original)
        r=call('systemctl','restart','sing-box.service')
        if r.returncode:fail('已恢复配置，但重启失败: '+r.stderr[-500:])
    state['status']='rolled_back'
    atomic_write(STATE,json.dumps(state).encode())
    print('已恢复原始配置，回滚完成')
def confirm(args):
    state=load_state()
    if state.get('status')!='pending':fail('没有待确认切换')
    if digest(LIVE.read_bytes())!=state['candidate_sha256']:fail('当前配置不匹配候选，不能确认')
    if call('systemctl','is-active','--quiet','sing-box.service').returncode:fail('服务未运行')
    # Stop timer before marking confirmed. Timer cannot be trusted as the only safety mechanism.
    r=call('systemctl','stop',TIMER+'.timer')
    if r.returncode:fail('停止自动回滚计时器失败: '+r.stderr[-500:])
    state['status']='confirmed'
    atomic_write(STATE,json.dumps(state).encode())
    print('已确认并停止自动回滚计时器；保留备份')
def main():
    if os.geteuid()!=0:fail('请使用 root')
    ROOT.mkdir(mode=0o700,parents=True,exist_ok=True);os.chmod(ROOT,0o700)
    p=argparse.ArgumentParser()
    sub=p.add_subparsers(dest='action',required=True)
    for name in ('prepare','activate'):
        q=sub.add_parser(name);q.add_argument('--candidate',required=True)
        if name=='activate':q.add_argument('--confirm-disruption',action='store_true')
    sub.add_parser('confirm')
    q=sub.add_parser('rollback');q.add_argument('--automatic',action='store_true')
    args=p.parse_args()
    {'prepare':prepare,'activate':activate,'confirm':confirm,'rollback':rollback}[args.action](args)
if __name__=='__main__':
    try:main()
    except Exception as e:print('ERROR:',e,file=sys.stderr);sys.exit(1)
