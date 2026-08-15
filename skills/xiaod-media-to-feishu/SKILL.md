---
name: xiaod-media-to-feishu
description: 将公开音视频链接、本地媒体、字幕、逐字稿或用户有权访问的飞书内容整理成分享式中文长稿，完成断点续跑、本地质检、飞书知识库交付、访问验证和安全清理。用户说“链接转文档”“转录整理”“放到飞书”“整理妙记/会议”或要求小D处理媒体时使用。
---

# 小D-链接转录助手

## 开始

先运行 `xiaod-doctor`。全部通过后再处理任务；有失败项时只修对应配置。登录、扫码、授权和配对由用户本人完成，其余步骤由 Agent 执行。

仅调用本机已配置的 CLI。让凭据、应用标识、账号标识、资源标识和授权链接留在本机私有配置中；Skill、命令、日志、成稿和回复只使用运行时返回值，不固化这些内容。

## 状态机

- 每个任务使用 `work/<job-id>/`，最终稿写入 `outputs/<title>.md`。
- 在 `work/<job-id>/status.json` 记录来源、阶段和已生成文件；完成一步立即更新。
- 从最后成功阶段继续，不重复下载、转录或远端写入。
- 运行超过一分钟时报告当前阶段。缓存持续增长表示仍在工作；连续五分钟无增长才重试一次。

## 1. 获取正文

记录来源、标题、时长、语言和访问条件。按以下顺序选择：人工或官方逐字稿/字幕 → 飞书已有转录 → 平台字幕 → 本地 ASR。简介和章节只用于核对元数据与术语。

飞书逐字稿先读目录；遇到“关键词 / 文字记录”结构时，读取 `lark-cli` 自带的最新指南，保存完整 Markdown 到任务目录，不把长正文刷入聊天。

按需执行：

```bash
xiaod-media-pipeline inspect SOURCE
xiaod-media-pipeline subtitles URL --output-dir work/JOB/source
xiaod-media-pipeline youtube-transcript URL --output-dir work/JOB/source
xiaod-media-pipeline download URL --output-dir work/JOB/source
xiaod-media-pipeline convert INPUT --output work/JOB/source/asr-input.wav
xiaod-media-pipeline transcribe INPUT --output-dir work/JOB/asr --language zh
```

只处理公开或用户明确授权的单条内容。保留原始 TXT/JSON 转录直至交付闭环；失败时保留全部文件。

## 2. 分享式提纯

产出“分享式提纯版原文”，不是摘要：

- 删除时间戳、说话人标签、寒暄、口水话、噪音、重复和残句。
- 核对人名、公司、产品、地名、术语、日期和数字；不确定项标记待核对。
- 保留原意、语气、案例、数字、类比、限定条件、判断链和重要原话。
- 先建立少量大主题，再逐段提纯；全局去重并恢复跨段逻辑。
- 标题具体且来自正文；重要判断适度加粗。
- 不新增事实、不外推、不替原文下结论。

## 3. 本地验收

```bash
xiaod-media-pipeline qc outputs/成稿.md
```

自动检查通过后，再核对案例、数字、专名、乱码、重复、标题密度和跨段逻辑。未通过时只修本地稿。

## 4. 飞书交付

1. 只使用 `lark-cli-user`，先读取其内置 `lark-markdown` 与 `lark-wiki` 指南。
2. 所有知识库和文档命令显式使用 `--as user`。
3. 从本机私有配置读取目标知识库名称；默认名称为“音视频转录整理”。按名称精确匹配，零个或多个匹配均停止并报告。
4. 从工作区相对 Markdown 路径创建文档，再将文档迁入目标知识库。等待异步任务完成。
5. 回读知识库节点和文档目录，确认所属知识库、标题层级、正文结构和链接访问均正确。

创建、迁入、目录回读或访问验证任一步失败时，回复“部分完成”，保留本地文件并从失败阶段继续。只有文档确实位于目标知识库且可访问时才能回复“完成”。

## 5. 清理

仅在本地 QC、知识库入库、目录回读和访问验证全部成功后执行：

```bash
xiaod-media-pipeline cleanup work/JOB --output outputs/成稿.md --wiki-url "已验证链接"
xiaod-media-pipeline cleanup work/JOB --output outputs/成稿.md --wiki-url "已验证链接" --apply
```

先预览再删除。只清理 `work/` 的一个直接子目录；保留最终 Markdown。禁止清理失败任务、未验证任务、共享目录、根目录或符号链接。

## 回复

- **完成**：给出必要质量说明、释放空间和知识库链接。
- **部分完成**：说明最后成功阶段、失败阶段和唯一下一步。
- **阻塞**：说明真实错误和用户必须完成的一个动作。
