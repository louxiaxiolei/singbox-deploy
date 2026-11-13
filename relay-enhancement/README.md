# 五协议中转测试版

支持 SS（不含插件）、HY2、TUIC、VLESS TCP Reality、AnyTLS TLS 落地出站。AnyTLS 不等同于 AnyTLS Reality。

**仅支持本仓库创建的 `/etc/singbox-deploy/nodes/*.json` 独立节点**，不修改第三方脚本的 `/etc/sing-box/config.json`。切换时只重启所选节点。首次测试请使用空闲 VPS。

## 一键安装

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/louxiaxiolei/singbox-deploy/feature/relay-five-protocols-test/install-relay-test.sh)
LM
```

前提：已通过本项目安装 LM，服务器有 python3、curl、sing-box 和 systemd。安装器仅备份并修改本机 LM 菜单，不重启节点；`LM → 13` 进入中转管理。先添加落地 URI，再测试出口并选择某个入站切换；失败会尝试回滚。客户端仍需验证出口。

**限制：** 尚未在实际 VPS 上端到端测试；未加入新建入站时的中转选项；不支持 SS plugin、VLESS 非 TCP Reality；TLS insecure=1 不验证证书。落地 URI 与私钥保存在本机权限 0600 的文件中，不要公开。测试分支不覆盖 main。
