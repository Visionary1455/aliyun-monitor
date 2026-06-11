# Cloudflare Workers Cron 触发器部署指南

## 用途

GitHub Actions 的 `schedule` 触发是 **best-effort**，实际间隔常达 1-4 小时甚至跳过。
本 Worker 每 5 分钟主动调用 GitHub API 触发 `monitor.yml`，**精度 < 15 秒**。

## 架构

```
Cloudflare Workers Cron (*/5 * * * * UTC)
            │
            ▼  POST + Bearer PAT
GitHub Actions workflow_dispatch
            │
            ▼
monitor.py 执行实际监控
```

`monitor.py` 一行不动。GH 原 `schedule` 保留作为兜底（即使 CF 挂了 1 小时还能跑一次）。

## 一、准备 GitHub PAT

1. 打开 https://github.com/settings/personal-access-tokens/new
2. 填写：
   - **Token name**: `cf-worker-aliyun-monitor`
   - **Expiration**: 90 days（到期前重新生成）
   - **Resource owner**: 你的 GitHub 账号
   - **Repository access**: Only select repositories → 勾选 `aliyun-monitor`
   - **Repository permissions**:
     - `Actions`: **Read and write**
     - `Contents`: Read-only
     - `Metadata`: Read-only (自动)
     - 其它全部不勾
3. 点击 `Generate token`，**立即复制保存**（只显示一次）

## 二、部署 Worker

### 方式 A：Dashboard 部署（推荐，无需安装 wrangler）

1. 打开 https://dash.cloudflare.com → 左侧 `Workers & Pages`
2. 点击 `Create application` → `Create Worker`
3. 名字填 `aliyun-monitor-trigger` → `Deploy`
4. 部署后点 `Edit code`，把 `worker.js` 全部内容粘贴进去 → `Save and Deploy`
5. 回到 Worker 详情页 → `Settings` → `Variables and Secrets`
   - 添加 **Secret**: `GH_PAT` = 你的 PAT（`github_pat_xxx...`）
   - 添加 **Variable** (非加密): `GH_REPO` = `hizzt/aliyun-monitor`
   - 添加 **Variable**: `GH_REF` = `main`
   - 添加 **Variable**: `GH_WORKFLOW` = `monitor.yml`
6. `Settings` → `Triggers` → `Cron Triggers` → `Add Cron Trigger`
   - 表达式: `*/5 * * * *`
   - 保存

### 方式 B：wrangler CLI（需要 Node.js）

```bash
cd cf-worker

# 安装 wrangler（一次性）
npm install -g wrangler

# 登录
wrangler login

# 设置 secret
wrangler secret put GH_PAT
# 粘贴 PAT 回车

# 部署
wrangler deploy
```

## 三、验证

### 立即手动触发一次

打开 Worker URL（dashboard 上会显示，类似 `https://aliyun-monitor-trigger.xxxxx.workers.dev`），访问：

```
https://aliyun-monitor-trigger.xxxxx.workers.dev/trigger
```

返回 `triggered` 即成功。

### 查看日志

CF Dashboard → Worker → `Logs` → `Begin log stream`

应该看到：
```
[OK] dispatch hizzt/aliyun-monitor@main monitor.yml (cron=manual)
```

### 确认 GitHub 收到触发

打开 https://github.com/hizzt/aliyun-monitor/actions

应该有一条新 `workflow_dispatch` run，由 `cf-worker-aliyun-monitor` 这个 PAT 触发。

### 观察 5 分钟定时

等 5-10 分钟，确认 GitHub Actions 列表出现新的 `workflow_dispatch` 类型 run。

## 四、安全说明

- ✅ PAT 是 fine-grained，仅 `aliyun-monitor` 仓库 `Actions: write` 权限
- ✅ PAT 存 CF Secret（加密）
- ✅ `/trigger` HTTP 入口可选配置 `TRIGGER_TOKEN` 防止被人滥用调用
- ✅ 即使 PAT 泄漏，攻击者只能触发本仓库 workflow，无法读代码、改代码
- ✅ PAT 90 天过期，强制定期轮换

## 五、监控与告警

CF Workers 失败不会影响 monitor.py 执行（GH schedule 兜底）。
如果想监控 Worker 自身：

- CF Dashboard → Worker → `Metrics` 查看请求成功率
- 设置 CF Notifications（账号级邮件告警）

## 六、关闭/卸载

- **临时关闭**：Dashboard → Triggers → 删除 Cron Trigger
- **彻底卸载**：Workers & Pages → 选中 Worker → Delete
- **撤销 PAT**：https://github.com/settings/personal-access-tokens → Revoke

## 七、成本

| 项目 | 用量 | Free 限额 | 剩余 |
|------|------|-----------|------|
| 请求/天 | 288 (12/h × 24) | 100,000 | 99.7% |
| CPU 时间 | < 1ms × 288 | 10ms × 100k | 几乎为 0 |
| 费用 | **¥0** | - | - |

## 常见问题

### Q: CF Worker 跑了，但 GH 没出现新 run
A: 检查 PAT 是否正确（Logs 会显示 HTTP 401/403），权限是否包含 Actions Write。

### Q: CF Worker logs 看到 422
A: 仓库名/分支/workflow 文件名错了，或 workflow 没启用 `workflow_dispatch`。

### Q: GH Actions 现在跑得太频繁了
A: 调整 cron 间隔为 `*/10 * * * *`（10 分钟），改完 `Save and Deploy`。

### Q: 想停 GH 原 schedule，只用 CF 触发
A: 修改仓库 `.github/workflows/monitor.yml`，删除 `on.schedule` 段即可。
   建议先观察 CF Worker 稳定运行 1 周后再禁用。
