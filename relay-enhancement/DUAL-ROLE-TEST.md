# 五协议双角色测试版（独立服务，不覆盖旧节点）

## 落地机：AkileCloud

先检查 `sing-box version`、`ss -lntu`。使用独立入口，不修改 `/etc/sing-box/config.json`、`/etc/hysteria/config.yaml` 或现有 systemd 服务。

```bash
curl -fL --retry 2 -o /root/install-landing-v2.sh https://raw.githubusercontent.com/louxiaxiolei/singbox-deploy/feature/relay-five-protocols-test/install-landing-v2.sh
bash -n /root/install-landing-v2.sh && bash /root/install-landing-v2.sh
```

菜单依次创建 SS、HY2、TUIC、VLESS Reality、AnyTLS 节点，每个节点需输入独立未占用端口与公网 IP/域名。新增服务名为 `singbox-landing-协议-端口.service`，配置在 `/etc/singbox-deploy-v2/nodes`，链接在同名 `.link` 文件中（含凭据）。成功后按提示放行云安全组 TCP/UDP 端口。

TLS 三协议当前使用专用自签名证书，分享链接带 `insecure=1`，仅供测试；生产环境应换成可信证书。AnyTLS 是 TLS，不是 Reality。落地服务出口默认 direct。

## 中转机：已有本项目 LM 的 VPS

```bash
curl -fL --retry 2 -o /root/install-relay-v2.sh https://raw.githubusercontent.com/louxiaxiolei/singbox-deploy/feature/relay-five-protocols-test/install-relay-v2.sh
bash -n /root/install-relay-v2.sh && bash /root/install-relay-v2.sh
relay-manager
```

先选 1 导入落地机生成的 URI，再选 3，选择本项目已存在的独立入站节点。程序会使用临时本地代理实际检测落地出口 IP，配置校验通过且输入 YES 后才切换该入站的出站。选 4 恢复直连。

**重要限制**：中转模块当前不负责创建新的中转入站，必须先有 `/etc/singbox-deploy/nodes/*.json` 和对应正在运行的 `singbox-deploy-*.service`。不支持第三方安装器的 `/etc/sing-box/config.json`。中转节点 URI 应与中转 VPS 的入口对应，落地机生成的 URI 仅在中转机导入，不应误当成中转节点分享。

## 验证

```bash
systemctl list-units --all 'singbox-landing-*' --no-pager
find /etc/singbox-deploy-v2/nodes -maxdepth 1 -name '*.json' -print
```

未在真实 VPS 做端到端验证；先创建一个节点，测试成功再添加剩余四种。不要把带凭据的 .link 内容发到公开聊天或 issue。
