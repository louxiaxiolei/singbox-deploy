singbox-deploy

轻量级 sing-box 一键部署与管理脚本。

支持 Alpine Linux、Debian、Ubuntu 和 Rocky Linux，主要用于部署 VLESS + Reality 节点，兼容普通 VPS 和 NAT VPS。

一键安装

使用 SSH 登录 VPS，切换到 root 用户后执行：

bash <(wget -qO- https://raw.githubusercontent.com/louxiaxiolei/singbox-deploy/main/install.sh)

主要功能

* 自动识别 Linux 系统及 CPU 架构
* 自动检测 VPS 公网 IP
* 支持 VLESS + Reality 协议
* 支持 NAT VPS 自定义公网映射端口
* 自动生成节点分享链接
* 针对低内存 VPS 进行基础优化

使用说明

1. 使用 SSH 登录服务器。
2. 以 root 用户运行一键安装命令。
3. 按菜单提示安装 VLESS + Reality。
4. NAT VPS 需要确认公网 TCP 端口映射。
5. 安装完成后保存生成的节点链接。

注意事项

目前脚本仍处于测试阶段，部分系统可能需要额外配置 sing-box 软件源。公网 IP 自动检测也不保证能够识别所有 NAT VPS 的 SSH 入口地址。
