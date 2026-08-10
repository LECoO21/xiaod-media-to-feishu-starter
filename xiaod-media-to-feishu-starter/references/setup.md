# 首次安装与配置

本安装包仅支持 Apple Silicon Mac，不携带任何模型或飞书账号信息。

## 安装

双击 `install.command`；如果 macOS 阻止双击，则在本 Skill 目录运行：

```bash
python3 scripts/install.py
```

安装器会创建独立 Hermes Profile、工作目录、Python 环境和三个命令：

- `xiaod`：启动小D；
- `xiaod-doctor`：检查配置；
- `xiaod-media-pipeline`：本地媒体处理。

## 只需配置两项

1. 运行 `xiaod setup`，按 Hermes 提示配置自己的模型服务。
2. 按本机飞书 CLI 的登录提示，授权自己的飞书账号。

不要把密钥、Token、Cookie、应用标识、账号标识或授权链接写入 Skill、聊天或共享文件。

配置后运行：

```bash
xiaod-doctor
```

全部显示 `✓` 后运行 `xiaod chat`，直接发送公开音视频链接、本地文件路径、飞书文档、妙记或会议内容即可。

首次本地转录会下载公开模型文件，时间取决于网络。观察到缓存持续增长时继续等待；连续五分钟无增长时停止当前任务并重试，已下载缓存会保留。
