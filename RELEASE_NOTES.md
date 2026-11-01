# Sol.trusted_identity 0.4.1

- 取消固定专属称呼；绑定账号称呼默认留空，由使用者填写。
- 每个群聊关注账号可单独编辑QQ与可选称呼，最多50条；重复账号拒绝保存。
- 原qq_numbers名单自动迁移为QQ与空称呼，显式新空列表优先；兼容Host配置处理顺序。
- 称呼仅在本次回复目标核验命中后提供；Planner不预判身份或称呼。
- 验证环境：Host1.3.19 / SDK2.21.0；22项测试通过，另验证Host旧配置迁移路径与对象数组配置结构。
- 账号/称呼默认空、来源未确认、插件默认关闭；升级请保留自己的配置。

下载本Release附带的portable.zip，在MaiBot插件管理页安装。已安装同ID时接口拒绝覆盖，先备份并按宿主更新流程操作。

作者标记与MIT许可沿用Sol；修改、测试、文档及打包由AI（Codex / DeepSeek Harness）协助；非原作者官方审阅认证。项目仓库：https://github.com/MWT-D0ZUV/Sol_trusted_identity。本次仅补齐发布地址与文档，功能及版本仍为0.4.0。
