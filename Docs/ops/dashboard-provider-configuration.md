# Dashboard 服务组配置运维

## 部署后的配置入口

部署新版 Dashboard 后，外部服务凭据只能通过 Dashboard 的服务组页面更新。不要用
`scp` 覆盖生产 `.env` 中的单个 URL、模型或 Key，也不要手动执行独立的
`supervisorctl restart arteta_bot` 来让单字段改动生效。

每次应用服务组时，Dashboard 会保存旧 `.env`、原子写入整组字段，并自动重启
`arteta_bot`。重启失败会还原旧文件并尝试恢复旧进程配置。

## 部署检查

1. 上传并部署 Dashboard API、前端构建产物和机器人运行时改动。
2. 保留 `/opt/arteta_bot/.env.prod`、SQLite、Chroma、prompt 和其他运行时数据，不要用部署包覆盖它们。
3. 重启 Dashboard 服务，使新 API 路由和前端资源生效。
4. 打开 Dashboard 的服务配置页，确认七个服务组均可见且 Key 只显示脱敏状态。
5. 用非生产或可安全验证的供应商配置执行一次验证和应用，确认 `arteta_bot` 自动重启。
6. 检查状态与日志：

```bash
supervisorctl status arteta_bot arteta_dashboard
supervisorctl tail -100 arteta_bot
supervisorctl tail -100 arteta_dashboard
```

## 故障处理

当服务组应用失败时，先查看 Dashboard 页面显示的恢复状态，再检查 Supervisor
状态和最近日志。不要通过重新输入旧 Key 的方式抢救；页面已在首次重启失败时自动恢复旧 `.env`。

如果恢复重启也失败，先确认 `arteta_bot` 的 Supervisor 配置和权限，再检查
`/opt/arteta_bot/.env.prod` 是否保留了预期旧值。不要把 `.env.prod` 内容贴入日志、工单或提交记录。
