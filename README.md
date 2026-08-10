# 小D链接转飞书文档・小白版

一个面向 Apple Silicon Mac 的可安装 Skill：把公开音视频、本地媒体、字幕、逐字稿或飞书内容整理成分享式中文长稿，并完成质量检查、飞书知识库交付、访问验证和中间文件清理。

## 功能

- 优先使用现成字幕或逐字稿，必要时运行本地 ASR；
- 去除时间戳、口水话和转录噪音，校正专名并保留完整论证；
- 本地质量检查通过后再创建飞书文档；
- 验证知识库目录与访问权限后才报告完成；
- 成功交付后自动清理大体积中间文件；
- 记录任务阶段，失败后从最后成功步骤继续。

## 安装

先安装 Hermes CLI 和飞书 CLI，然后：

1. 下载并解压 Release 中的安装包；
2. 双击 `install.command`；
3. 运行 `xiaod setup`，配置自己的模型服务；
4. 按飞书 CLI 提示登录自己的账号；
5. 运行 `xiaod-doctor`；
6. 全部通过后运行 `xiaod chat`，直接发送链接或文件路径。

也可以在 Skill 目录运行：

```bash
python3 scripts/install.py
```

## 安全

仓库不包含任何个人 API Key、Token、Cookie、账号、应用标识、知识库标识、授权链接或机器绝对路径。安装器不会读取或复制这些内容，只检查所需 CLI 是否已由使用者本人完成配置。

请勿提交 `.env`、本地工作目录、转录文件或授权信息。

## 目录

```text
xiaod-media-to-feishu-starter/
├── SKILL.md
├── install.command
├── agents/openai.yaml
├── references/setup.md
└── scripts/
    ├── install.py
    ├── doctor.py
    └── media_pipeline.py
```

## 许可

[MIT License](LICENSE)
