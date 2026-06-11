# Cloudflare Workers Cron 触发器部署指南

## 用途

GitHub Actions 的 `schedule` 触发是 **best-effort**，实际间隔常达 1-4 小时甚至跳过。
本 Worker 每 5 分钟主动调用 GitHub API 触发 `workflow_dispatch`，**精度 < 15 秒**。

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

业务代码（`monitor.py`）一行不动。GH 原 `schedule` 保留作为兜底（即使 CF 挂了 1 小时还能跑一次）。

---

## ⚠️ 安全前置说明

**本仓库是公开仓库**。Worker 代码不包含任何真实的 owner/repo/PAT，所有敏感信息都需要部署者在 Cloudflare Dashboard 中以 **Secret** / **Variable** 形式配置。

切勿将以下内容提交到任何公开仓库：
- GitHub PAT
- 具体的 owner/repo（虽然不算敏感，但建议作为 Secret 配置）
- TRIGGER_TOKEN

---

## 一、必须配置的项

部署本 Worker 前，必须准备好以下两项：

| 项 | 类型 | 获取方式 |
|----|------|---------|
| **GitHub PAT** (`GH_PAT`) | Secret | 见下方「准备 GitHub PAT」 |
| **GitHub 仓库** (`GH_REPO`) | Secret | 你的目标仓库，格式 `owner/repo`，例如 `myname/my-monitor-repo` |

可选配置：

| 项 | 类型 | 默认值 | 说明 |
|----|------|--------|------|
| `GH_REF` | Variable | `main` | 触发哪个分支 |
| `GH_WORKFLOW` | Variable | `monitor.yml` | 触发哪个 workflow 文件 |
| `TRIGGER_TOKEN` | Secret | 无 | 配置后才能用 `/trigger` HTTP 入口；不配则 HTTP 入口完全禁用 |

---

## 二、准备 GitHub PAT（必须）

1. 打开 https://github.com/settings/personal-access-tokens/new
2. 填写：
   - **Token name**: `cf-worker-gh-dispatcher`（或任意名字）
   - **Expiration**: 建议 90 days（到期前重新生成轮换）
   - **Resource owner**: 你的 GitHub 账号或组织
   - **Repository access**: `Only select repositories` → 勾选你要触发的那一个仓库
   - **Repository permissions**:
     - `Actions`: **Read and write** ⭐ 必勾
     - `Contents`: Read-only
     - `Metadata`: Read-only（自动）
     - **其它权限全部不勾**（最小权限原则）
3. 点击 `Generate token`，**立即复制保存**（只显示一次）
4. 格式示例：`github_pat_11AAAAAAA0xxxxxxxxxxxxxxxxxxx...`

**为什么是 fine-grained 而不是 classic？**
- 可以精确到「仅这一个仓库」+「仅 Actions write」
- 即使泄漏，攻击者只能触发本仓库 workflow，不能读代码、不能改代码、不能动其它仓库
- 强制设置过期时间

---

## 三、部署 Worker

### 方式 A：Dashboard 部署（推荐，无需安装 wrangler）

#### Step 1: 创建 Worker

1. 打开 https://dash.cloudflare.com → 左侧 `Workers & Pages`
2. 点击 `Create application` → `Create Worker`
3. 名字填 `gh-workflow-dispatcher`（或任意名）→ `Deploy`

#### Step 2: 粘贴代码

1. 部署完成后点 `Edit code`
2. 把本目录 `worker.js` 全部内容粘贴进去
3. 点 `Save and Deploy`

#### Step 3: 配置 Secrets 和 Variables（**关键步骤，不能跳过**）

回到 Worker 详情页 → `Settings` → `Variables and Secrets`

**必须添加的 Secrets**（点 `Add` 选择 Type=Secret）：

| Name | Value 示例 | 说明 |
|------|-----------|------|
| `GH_PAT` | `github_pat_11AAAAA...` | 你刚才创建的 PAT |
| `GH_REPO` | `myname/my-monitor-repo` | 你的仓库 owner/name |

**可选 Secret**：

| Name | Value 示例 | 说明 |
|------|-----------|------|
| `TRIGGER_TOKEN` | 随便编一个长字符串如 `xK8nP2vQ9mR4tY7w` | 配置后才能用 HTTP `/trigger` 接口；不需要 HTTP 触发就别配 |

**可选 Variables**（点 `Add` 选择 Type=Plaintext，可改可不改）：

| Name | Value | 说明 |
|------|-------|------|
| `GH_REF` | `main` | 触发分支 |
| `GH_WORKFLOW` | `monitor.yml` | workflow 文件名 |

#### Step 4: 配置 Cron 触发器

1. `Settings` → `Triggers` → `Cron Triggers` → `Add Cron Trigger`
2. 表达式：`*/5 * * * *`
3. 保存

### 方式 B：wrangler CLI（需要 Node.js 16+）

```bash
cd cf-worker

# 安装 wrangler（一次性）
npm install -g wrangler

# 登录 CF
wrangler login

# 设置必填 secrets（每条单独执行，敏感值不要在 shell 历史里）
wrangler secret put GH_PAT
# 粘贴 PAT 回车

wrangler secret put GH_REPO
# 输入 owner/repo 回车

# 可选 secret
wrangler secret put TRIGGER_TOKEN

# 部署（cron 由 wrangler.toml 中 [triggers].crons 决定）
wrangler deploy
```

---

## 四、验证

### 1. 立即手动触发一次（推荐先做这步）

**方法 A：HTTP 接口（需配置了 `TRIGGER_TOKEN`）**

```bash
curl -X POST https://gh-workflow-dispatcher.xxxxx.workers.dev/trigger \
  -H "Authorization: Bearer 你的TRIGGER_TOKEN"
```

返回 `triggered` 即成功。

**方法 B：CF Dashboard 模拟 Cron**

Worker 详情页 → `Triggers` → 找到 Cron 那条 → 点 `Send Event`（如果有这个按钮）

### 2. 查看 Worker 日志

CF Dashboard → Worker → `Logs` → `Begin log stream`

成功日志：
```
[OK] dispatch myname/my-monitor-repo@main monitor.yml (cron=manual)
```

常见失败：
| 日志 | 原因 | 修复 |
|------|------|------|
| `GH_PAT 未配置` | 没加 Secret | 加 `GH_PAT` |
| `GH_REPO 未配置` | 没加 Secret | 加 `GH_REPO` |
| `[FAIL] HTTP 401` | PAT 错或失效 | 检查 PAT 是否复制完整 |
| `[FAIL] HTTP 403` | PAT 权限不够 | 确认勾选了 Actions: Read and write |
| `[FAIL] HTTP 404` | repo 或 workflow 写错 | 检查 `GH_REPO`、`GH_WORKFLOW` |
| `[FAIL] HTTP 422` | workflow 没启用 `workflow_dispatch` | 检查 yml 是否有 `on.workflow_dispatch` |

### 3. 确认 GitHub 收到触发

打开你目标仓库的 `Actions` 页面，应该有一条新 `workflow_dispatch` run，触发者是你的 PAT 名字。

### 4. 观察 5 分钟定时

等 5-10 分钟，刷新 Actions 列表，应该出现新 run。如果 1 小时内都没有新 run，回到 Logs 排查。

---

## 五、安全特性

| 特性 | 实现方式 |
|------|---------|
| PAT 不在代码/wrangler.toml 中 | 通过 CF Secret 注入运行时 |
| PAT 仅最小权限 | fine-grained，单仓库 + 仅 Actions:write |
| PAT 强制过期 | fine-grained 必填过期日期，建议 90 天轮换 |
| HTTP `/trigger` 默认禁用 | 未配置 `TRIGGER_TOKEN` 时返回 403 |
| HTTP `/trigger` 需要鉴权 | 配置后必须带正确 Bearer token |
| 即使 PAT 泄漏 | 最大损失：被人触发跑空，仍无法读/改代码 |

---

## 六、监控与维护

- **CF 端**：Dashboard → Worker → `Metrics` 查看请求成功率
- **GitHub 端**：Actions 列表观察是否每 5 min 出现新 run
- **PAT 到期**：日历提醒 80 天后重建 PAT 并更新 `GH_PAT` Secret

## 七、关闭/卸载

- **临时关闭定时**：Dashboard → Triggers → 删除 Cron Trigger
- **彻底卸载 Worker**：Workers & Pages → 选中 → Delete
- **撤销 PAT**：https://github.com/settings/personal-access-tokens → Revoke

## 八、成本

| 项目 | 用量 | Free 限额 | 占比 |
|------|------|-----------|------|
| 请求/天 | 288 (12/h × 24) | 100,000 | 0.3% |
| CPU 时间/请求 | < 1ms | 10ms | 10% |
| 出站流量/天 | < 100KB | 无限制 | - |
| 费用 | **¥0** | - | - |

---

## 九、常见问题

### Q: 我已经有别的 Worker 在用，会冲突吗？
A: Free 计划 100k 请求/天是账号共享的，本 Worker 占 288 个，剩余 99.7% 给其它用。

### Q: 加了 CF 后 GitHub schedule 还要不要？
A: 建议保留作为兜底。CF 挂了 GH 至少还能 1-4 小时跑一次。
   等 CF 稳定运行 1 周后可以考虑禁用 GH schedule。

### Q: cron 表达式按什么时区解析？
A: **UTC**。`*/5 * * * *` 这种间隔类不受时区影响，但 `0 1 * * *` 会按 UTC 1:00 触发（北京 9:00）。

### Q: 多触发了会重复执行业务逻辑吗？
A: 不会。`monitor.py` 内部有 cooldown 机制和状态文件去重，重复触发幂等。

### Q: Worker 部署完成后多久能跑第一次 cron？
A: 配置 cron trigger 后，下一个对齐的整 5 分钟点（如 12:05, 12:10）就会触发。
