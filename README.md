# 阿里云 ECS 保活监控指南

## 一、功能概述

本项目实现阿里云 ECS 实例的自动化监控与保活，主要功能：

| 功能 | 说明 |
|------|------|
| **CDT 流量监控** | 监控阿里云 CDT 流量使用量，防止流量超标产生额外费用 |
| **流量超限自动关机** | 当流量超过阈值时，自动停止实例止损 |
| **实例停止自动启动** | 当检测到实例停止时，自动启动恢复服务 |
| **飞书消息通知** | 通过飞书发送告警通知和每日日报 |
| **每日运行报表** | 每天定时发送多机汇总状态与流量使用报表（北京时间） |
| **多实例支持** | 所有配置项支持逗号分隔，单脚本同时监控多台 ECS，故障隔离 |

---

## 二、配置清单

### 2.1 需要配置的 GitHub Secrets

在 GitHub 仓库 → `Settings` → `Secrets and variables` → `Actions` 中添加以下变量：

| Secret 名称 | 必须 | 说明 | 示例值 |
|-------------|------|------|--------|
| `ALIYUN_ACCESS_KEY_ID` | ✅ | 阿里云 AccessKey ID（多个用逗号分隔） | `LTAI5txxxxxx` 或 `LTAI5tA,LTAI5tB` |
| `ALIYUN_ACCESS_KEY_SECRET` | ✅ | 阿里云 AccessKey Secret（多个用逗号分隔） | `xxxxx` 或 `secretA,secretB` |
| `ALIYUN_REGION` | ✅ | ECS 实例所在区域（多个用逗号分隔） | `ap-northeast-1` 或 `cn-hongkong,ap-northeast-1` |
| `ECS_INSTANCE_ID` | ✅ | 要监控的实例 ID（多个用逗号分隔） | `i-bp1xxx` 或 `i-bp1xxx,i-bp2yyy` |
| `CDT_TRAFFIC_LIMIT_GB` | ✅ | 流量阈值 GB（多个用逗号分隔） | `180` 或 `180,200` |
| `FEISHU_APP_ID` | ✅ | 飞书应用 App ID | `cli_xxxxxxxxxxxx` |
| `FEISHU_APP_SECRET` | ✅ | 飞书应用 App Secret | `xxxxxxxxxxxxxxxx` |
| `FEISHU_USER_OPEN_ID` | ✅ | 接收通知的飞书用户 Open ID | `ou_xxxxxxxxxxxxxxxx` |
| `INSTANCE_NAME` | ❌ | 实例显示名称（多个用逗号分隔） | `东京服务器` 或 `东京,香港` |
| `REPORT_HOUR` | ❌ | 每日日报发送小时（北京时间，默认 9，多个用逗号分隔） | `9` 或 `9,18` |

> **多实例规则**：6 项以 `,` 分隔的配置（AK/SK/Region/InstanceID/Limit/Name），数量必须一致或为 1。
> - 配 1 个值：所有实例共享（例如同账号同区域多台机器只需 AK/SK/Region 各填一个）
> - 配 N 个值：按位置一一对应（例如跨账号每台机器各自的 AK/SK）
> - 数量不匹配会启动失败并发送告警

---

## 三、各配置项获取教程

### 3.1 阿里云 AccessKey（必须）

1. 登录阿里云控制台：https://console.aliyun.com
2. 鼠标悬停右上角头像 → `AccessKey管理`
3. 选择「使用子用户 AccessKey」
4. 点击「创建用户」，勾选「编程访问」
5. 记录生成的 `AccessKey ID` 和 `AccessKey Secret`
6. **重要**：为该用户添加权限策略，参考下方「最小权限配置」

#### 最小权限策略（JSON）

```json
{
  "Version": "1",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ecs:DescribeInstances",
        "ecs:DescribeInstanceStatus",
        "ecs:StartInstance",
        "ecs:StopInstance"
      ],
      "Resource": "acs:ecs:*:*:instance/<你的实例ID>"
    },
    {
      "Effect": "Allow",
      "Action": [
        "bssopenapi:QueryInstanceBill"
      ],
      "Resource": "*"
    }
  ]
}
```

> 将 `<你的实例ID>` 替换为你的实际 ECS 实例 ID（如 `i-bp123456789`）

---

### 3.2 阿里云地域 Region

| 区域 | Region ID |
|------|-----------|
| 华北2（北京） | `cn-beijing` |
| 华北3（张家口） | `cn-zhangjiakou` |
| 华东1（杭州） | `cn-hangzhou` |
| 华东2（上海） | `cn-shanghai` |
| 华南1（深圳） | `cn-shenzhen` |
| 香港 | `cn-hongkong` |
| 新加坡 | `ap-southeast-1` |
| 东京 | `ap-northeast-1` |
| 硅谷 | `us-west-1` |
| 弗吉尼亚 | `us-east-1` |

获取方式：ECS 控制台 → 实例列表 → 查看实例详情中的「地域」

---

### 3.3 ECS 实例 ID

1. 登录阿里云 ECS 控制台：https://ecs.console.aliyun.com
2. 进入「实例列表」
3. 复制「实例 ID」列的值（以 `i-` 开头）

---

### 3.4 飞书应用配置（必须）

#### 3.4.1 获取 App ID 和 App Secret

1. 打开飞书开放平台：https://open.feishu.cn/
2. 进入「应用开发」→「创建应用」→「企业自建应用」
3. 填写应用名称（如「阿里云监控」）并创建
4. 在应用详情页面获取：
   - `App ID`：类似 `cli_xxxxxxxxxxxx`
   - `App Secret`：类似 `xxxxxxxxxxxxxxxx`

#### 3.4.2 添加应用权限

在应用详情 → `权限管理` 中添加：
- `im:message:send_as_bot` - 发送消息
- `im:chat:create` - 创建群聊

#### 3.4.3 获取你的 Open ID

**方法1（推荐）：** 给机器人发消息

1. 在飞书中搜索并打开你的应用
2. 给应用发送一条消息（如 "测试"）
3. 运行以下命令获取 Open ID：

```bash
# 获取应用 token
TOKEN=$(curl -s -X POST "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal" \
  -H "Content-Type: application/json; charset=utf-8" \
  -d '{"app_id": "你的APP_ID", "app_secret": "你的APP_SECRET"}' | python3 -c "import json,sys; print(json.load(sys.stdin).get('tenant_access_token',''))")

# 查看应用收到的消息（需要先发消息）
curl -s "https://open.feishu.cn/open-api/im/v1/messages?receive_id_type=user_id&container_id_type=app" \
  -H "Authorization: Bearer $TOKEN"
```

**方法2：**

在飞书中打开：https://api.feishu.cn/toolkit/tips

---

## 四、配置步骤

### 4.1 Fork 或使用本仓库

可以直接使用本仓库，或 fork 到自己的 GitHub 账号下。

### 4.2 配置 GitHub Secrets

1. 进入仓库 → `Settings` → `Secrets and variables` → `Actions`
2. 点击「New repository secret」
3. 按上方表格逐个添加配置项
4. 建议按以下顺序添加：

```
1. ALIYUN_ACCESS_KEY_ID
2. ALIYUN_ACCESS_KEY_SECRET
3. ALIYUN_REGION
4. ECS_INSTANCE_ID
5. CDT_TRAFFIC_LIMIT_GB
6. FEISHU_APP_ID
7. FEISHU_APP_SECRET
8. FEISHU_USER_OPEN_ID
9. INSTANCE_NAME (可选)
10. REPORT_HOUR (可选，默认9)
```

### 4.3 验证配置

1. 进入仓库 → `Actions`
2. 点击「Aliyun ECS Monitor」
3. 点击「Run workflow」→「Run workflow」
4. 等待 1-2 分钟执行完成
5. 查看「Actions run」日志确认无报错
6. 检查飞书是否收到测试消息

---

## 五、配置示例

### 5.1 单机示例

| Secret 名称 | 示例值 | 说明 |
|-------------|--------|------|
| `ALIYUN_ACCESS_KEY_ID` | `LTAI5t1234567890abcde` | 阿里云 AccessKey |
| `ALIYUN_ACCESS_KEY_SECRET` | `abcd1234EFGH5678ijkL9012` | 阿里云 AccessKey Secret |
| `ALIYUN_REGION` | `ap-northeast-1` | 东京区域 |
| `ECS_INSTANCE_ID` | `i-bp1234567890abcdef` | ECS 实例 ID |
| `CDT_TRAFFIC_LIMIT_GB` | `180` | 流量阈值 180GB |
| `FEISHU_APP_ID` | `cli_xxxxxxxxxxxx` | 飞书应用 ID |
| `FEISHU_APP_SECRET` | `xxxxxxxxxxxxxxxx` | 飞书应用密钥 |
| `FEISHU_USER_OPEN_ID` | `ou_xxxxxxxxxxxxxxxx` | 飞书用户 OpenID |
| `INSTANCE_NAME` | `东京ECS-01` | 实例显示名称 |
| `REPORT_HOUR` | `9` | 每天 9 点（北京时间）发送日报 |

### 5.2 多机示例（同账号 2 台）

| Secret 名称 | 示例值 |
|-------------|--------|
| `ALIYUN_ACCESS_KEY_ID` | `LTAI5t1234567890abcde` |
| `ALIYUN_ACCESS_KEY_SECRET` | `abcd1234EFGH5678ijkL9012` |
| `ALIYUN_REGION` | `ap-northeast-1` |
| `ECS_INSTANCE_ID` | `i-bp1xxx,i-bp2yyy` |
| `CDT_TRAFFIC_LIMIT_GB` | `180,200` |
| `INSTANCE_NAME` | `东京01,东京02` |

### 5.3 多机示例（跨账号 2 台）

| Secret 名称 | 示例值 |
|-------------|--------|
| `ALIYUN_ACCESS_KEY_ID` | `LTAI5tAcc1,LTAI5tAcc2` |
| `ALIYUN_ACCESS_KEY_SECRET` | `secretA,secretB` |
| `ALIYUN_REGION` | `cn-hongkong,ap-northeast-1` |
| `ECS_INSTANCE_ID` | `i-bp1xxx,i-bp2yyy` |
| `CDT_TRAFFIC_LIMIT_GB` | `180,200` |
| `INSTANCE_NAME` | `香港01,东京01` |

---

## 六、实现原理

### 6.1 整体架构

```
┌─────────────────────────────────────────────────────────┐
│                    GitHub Actions                        │
│  ┌─────────────────────────────────────────────────────┐ │
│  │  monitor.py (每5分钟执行一次)                        │ │
│  │                                                       │ │
│  │  1. 加载配置 (从 Secrets 环境变量)                   │ │
│  │  2. 调用阿里云 API 查询流量和实例状态                │ │
│  │  3. 判断逻辑：                                        │ │
│  │     - 流量超标 → 停止实例                            │ │
│  │     - 实例停止 → 启动实例                            │ │
│  │     - 到配置时间 → 发送日报                          │ │
│  │  4. 飞书通知 (根据配置发送给用户)                     │ │
│  │  5. 保存状态到缓存文件                               │ │
│  └─────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────┐
│                      阿里云 API                          │
│  • CDT 流量查询 (ListCdtInternetTraffic)                │
│  • 实例状态查询 (DescribeInstances)                     │
│  • 启动实例 (StartInstance)                             │
│  • 停止实例 (StopInstance)                              │
└─────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────┐
│                       飞书                               │
│  • 获取应用 AccessToken                                  │
│  • 发送消息给用户 (Open ID)                              │
└─────────────────────────────────────────────────────────┘
```

### 6.2 状态缓存机制

- 使用 `actions/cache` 保存状态文件（固定 key `monitor-state-v1`，自动覆盖）
- 按 `instance_id` 维度记录每个事件上次通知时间戳（冷却机制）
- 多实例每台独立 try/except + 落盘，单台失败不影响其它

### 6.3 冷却时间

| 事件类型 | 冷却时间 |
|----------|----------|
| 启动失败 | 1小时 |
| 流量超标 | 24小时 |
| 恢复运行 | 1小时 |
| 启动成功 | 1小时 |

### 6.4 日报发送逻辑

1. 每5分钟检查一次：当前小时（**北京时间 UTC+8**） >= `REPORT_HOUR` 中最早一项
2. 检查 `last_report_date` 是否为今天，已发送则跳过
3. 未发送则生成多机汇总日报并发送，落盘 `last_report_date`

> 触发使用 `>=` 而非 `==`，避免 cron 延迟导致漏报；当天只发一次

### 6.5 多实例与限流

- 实例间 `sleep 1s`，避免触发阿里云 OpenAPI QPS 限流
- 单台失败时单独发送 `[实例名] 实例处理异常` 告警
- 日报汇总所有机器的运行/停止/异常数量

---

## 七、常见问题

### Q1: 启动实例时报错 "Operation denied"
A: 检查 RAM 权限是否正确配置，确保有 `StartInstance` 权限

### Q2: 流量查询失败
A: 确认 ECS 实例已开通 CDT 流量包，且 AccessKey 有 `bssopenapi` 权限

### Q3: 飞书消息发送失败
A: 检查 App ID/Secret 是否正确，应用是否有 `im:message:send_as_bot` 权限

### Q4: Actions 执行失败
A: 查看 Actions 日志确认具体错误，常见原因：Secrets 配置错误、权限不足

---

## 八、注意事项

1. **安全第一**：所有敏感信息（AccessKey、App Secret）必须存储在 GitHub Secrets 中，切勿硬编码
2. **最小权限**：建议创建专用的 RAM 子用户，只授予必要的 API 权限
3. **测试环境**：首次配置建议先在测试实例上验证
4. **监控日志**：定期查看 Actions 运行日志确认工作正常

---

## 九、仓库地址

https://github.com/hizzt/aliyun-monitor

如有问题欢迎提交 Issue！