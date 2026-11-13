#!/usr/bin/env python3
"""Neburst four-inbound relay preflight: backup, candidate, isolated test; NEVER apply/restart."""
import datetime,getpass,hashlib,json,os,pathlib,shutil,socket,subprocess,sys,tempfile,time,urllib.parse
LIVE=pathlib.Path('/etc/sing-box/config.json')
EXPECTED={'hy2-in':('hysteria2',26071),'tuic-in':('tuic',20960),'vless-in':('vless',17465),'anytls-in':('anytls',12517)}
ROOT=pathlib.Path('/root/neburst-relay-preflight')
def run(args):return subprocess.run(args,text=True,capture_output=True)
def stop(msg):raise RuntimeError(msg)
def main():
    if os.geteuid()!=0:stop('请用 root')
    for c in ('sing-box','curl','systemctl'):
        if not shutil.which(c):stop('缺少 '+c)
    if not LIVE.is_file():stop('原配置不存在')
    svc=run(['systemctl','show','sing-box','-p','ExecStart','--value','--no-pager'])
    if svc.returncode or '/etc/sing-box/config.json' not in svc.stdout:stop('实际服务配置路径不同')
    original=LIVE.read_bytes();data=json.loads(original)
    actual={x.get('tag'):(x.get('type'),x.get('listen_port')) for x in data.get('inbounds',[])}
    if actual!=EXPECTED:stop('四入站与预期不一致: '+repr(actual))
    if len(data.get('outbounds',[]))!=1 or data['outbounds'][0].get('tag')!='direct-out' or data['outbounds'][0].get('type')!='direct':stop('出站与预期不同')
    route=data.get('route') or {}
    if route.get('final') not in (None,'direct-out') or route.get('rules'):stop('存在自定义路由，停止')
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    ROOT.mkdir(mode=0o700,parents=True,exist_ok=True);os.chmod(ROOT,0o700)
    backup=ROOT/('config.backup-'+stamp+'.json')
    backup.write_bytes(original);os.chmod(backup,0o600)
    print('原始配置已备份:',backup,flush=True)
    raw=getpass.getpass('粘贴 AkileCloud HY2 21460 链接（不回显）: ').strip()
    u=urllib.parse.urlsplit(raw)
    if u.scheme not in ('hy2','hysteria2') or u.hostname!='45.202.246.227' or u.port!=21460 or not u.username:stop('HY2 链接地址或密码不符合预期')
    q=urllib.parse.parse_qs(u.query);sni=q.get('sni',['singbox.local'])[0]
    if sni!='singbox.local':stop('SNI 不符')
    outbound={'type':'hysteria2','tag':'akile-hy2-out','server':u.hostname,'server_port':u.port,'password':urllib.parse.unquote(u.username),'tls':{'enabled':True,'server_name':sni,'insecure':True}}
    candidate=json.loads(original)
    candidate['outbounds'].append(outbound)
    candidate['route']={'rules':[{'inbound':list(EXPECTED),'action':'route','outbound':'akile-hy2-out'}],'final':'direct-out'}
    target=ROOT/('config.candidate-'+stamp+'.json')
    target.write_text(json.dumps(candidate,ensure_ascii=False,indent=2)+'\n');os.chmod(target,0o600)
    print('候选配置:',target)
    print('原配置 SHA256:',hashlib.sha256(original).hexdigest())
    ck=run(['sing-box','check','-c',str(target)])
    if ck.returncode:stop('候选配置检查失败: '+(ck.stderr or ck.stdout)[-1200:])
    print('候选配置检查 PASS',flush=True)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    test={'log':{'level':'warn'},'inbounds':[{'type':'mixed','tag':'test-in','listen':'127.0.0.1','listen_port':port}],'outbounds':[outbound],'route':{'final':'akile-hy2-out'}}
    with tempfile.TemporaryDirectory(prefix='neburst-relay-test-') as tmp:
        p=pathlib.Path(tmp)/'test.json';p.write_text(json.dumps(test));os.chmod(p,0o600)
        ck=run(['sing-box','check','-c',str(p)])
        if ck.returncode:stop('临时配置检查失败: '+ck.stderr[-800:])
        proc=subprocess.Popen(['sing-box','run','-c',str(p)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            time.sleep(2)
            if proc.poll() is not None:stop('临时客户端启动失败')
            r=run(['curl','--noproxy','','--proxy',f'http://127.0.0.1:{port}','--connect-timeout','8','--max-time','20','-sS','-o','/dev/null','-w','%{http_code}','https://www.cloudflare.com/cdn-cgi/trace'])
            if r.returncode or r.stdout.strip()!='200':stop('跨 VPS 测试失败: HTTP='+r.stdout.strip()+' '+r.stderr[-300:])
            print('独立跨 VPS 测试 HTTP 200 PASS',flush=True)
        finally:
            proc.terminate()
            try:proc.wait(timeout=5)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()
    if LIVE.read_bytes()!=original:stop('正式配置被外部修改，请核查')
    print('正式配置未修改，未重启 sing-box.service。等待用户另行确认正式切换。')
if __name__=='__main__':
    try:main()
    except (RuntimeError,ValueError,KeyError,OSError) as e:print('停止:',e,file=sys.stderr);sys.exit(1)
    except (KeyboardInterrupt,EOFError):print('用户取消',file=sys.stderr);sys.exit(130)
