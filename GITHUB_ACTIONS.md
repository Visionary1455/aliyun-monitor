# 阿里云 ECS 监控 - GitHub Actions 部署指南

## 概述

本项目实现阿里云 ECS 实例的 CDT 流量监控，支持：
- 流量超限自动关机
- 实例停止时自动启动
- 飞书机器人告警通知
- 每5分钟自动检查
- **多实例监控**（同账号/跨账号皆可，逗号分隔配置，故障隔离）
- **每日汇总日报**（北京时间）

## 架构

```
GitHub Actions (定时/手动)
       │
       ▼
  阿里云 API (查询流量/控制实例)
       │
       ▼
   飞书告警
```

## Secrets 配置

在 GitHub 仓库的 `Settings` → `Secrets and variables` → `Actions` 中添加以下 Secrets：

### 必需配置

| Secret 名称 | 说明 | 示例值 |
|-------------|------|--------|
| `ALIYUN_ACCESS_KEY_ID` | 阿里云 AccessKey ID（多实例用 `,` 分隔） | `LTAI5t**` 或 `LTAI5tA,LTAI5tB` |
| `ALIYUN_ACCESS_KEY_SECRET` | 阿里云 AccessKey Secret（多实例用 `,` 分隔） | **请创建 RAM 子用户** |
| `ALIYUN_REGION` | ECS 实例区域（多实例用 `,` 分隔） | `cn-hongkong` |
| `ECS_INSTANCE_ID` | 要监控的实例 ID（多实例用 `,` 分隔） | `i-bp1**` 或 `i-bp1**,i-bp2**` |
| `FEISHU_USER_OPEN_ID` | 接收通知的飞书用户 Open ID | `ou_**` |

### 可选配置

| Secret 名称 | 说明 | 默认值 |
|-------------|------|--------|
| `CDT_TRAFFIC_LIMIT_GB` | 流量阈值 GB（多实例用 `,` 分隔） | 180 |
| `INSTANCE_NAME` | 实例显示名称（多实例用 `,` 分隔） | ECS-Monitor |
| `REPORT_HOUR` | 日报小时（北京时间 UTC+8，多个用 `,` 分隔） | 9 |
| `FEISHU_APP_ID` | 飞书应用 App ID | cli_********** |
| `FEISHU_APP_SECRET` | 飞书应用 App Secret | ******** |
| `FEISHU_CHAT_ID` | 飞书群聊 ID | (可选) |

### 多实例配置规则

6 项以逗号分隔的配置（AK/SK/Region/InstanceID/Limit/Name）数量必须 **一致或为 1**：
- **1 个值**：所有实例共享（典型：同账号同区域多台机器，AK/SK/Region 各填一个）
- **N 个值**：按位置一一对应（典型：跨账号每台机器各自的 AK/SK）
- 数量不匹配启动时会失败并通过飞书告警

## 阿里云 RAM 权限配置 (重要!)

### 步骤1: 创建 RAM 子用户

1. 登录阿里云控制台 → RAM 访问控制 → 用户 → 创建用户
2. 勾选"编程访问"，获取 AccessKey ID 和 Secret

### 步骤2: 创建自定义权限策略

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

> 将 `<你的实例ID>` 替换为你的实际 ECS 实例 ID

### 步骤3: 授权给子用户

将自定义策略绑定到创建的子用户。

## 飞书机器人配置

### 获取 App ID 和 Secret

1. 打开 https://open.feishu.cn/
2. 创建企业自建应用
3. 在"应用凭证"中获取 App ID 和 App Secret

### 添加机器人权限

在应用详情 → 权限管理 中添加：
- `im:message:send_as_bot` - 发送消息
- `im:chat:create` - 创建群聊

### 获取 Chat ID (可选)

如果需要发送到特定群聊：
1. 在群聊中添加机器人
2. 使用 API 获取群聊 ID：`https://open.feishu.cn/open-apis/im/v1/chats?member_id_type=user_id`

## 使用方法

### 1. 推送代码到 GitHub

```bash
git add .
git commit -m "Add GitHub Actions monitor"
git push origin main
```

### 2. 配置 Secrets

在 GitHub 仓库设置中添加上述 Secrets。

### 3. 验证

- 手动触发：仓库 → Actions → Aliyun ECS Monitor → Run workflow
- 查看日志确认执行成功

### 4. 接收告警

配置完成后，当发生以下情况时会收到飞书通知：
- 流量超限自动关机
- 流量正常时启动实例
- 启动/停止操作失败

## 工作流说明

| 触发方式 | 说明 |
|----------|------|
| schedule | 每5分钟自动执行 |
| workflow_dispatch | 手��触发 (仓库 → Actions → Run workflow) |
| repository_dispatch | API 触发 |

## 文件结构

```
aliyun_monitor/
├── .github/
│   └── workflows/
│       ├── monitor.yml      # GitHub Actions 工作流
│       └── monitor.py       # 监控脚本
├── src/
│   ├── monitor.py           # 服务器端监控脚本
│   └── report.py            # 日报生成脚本
├── install.sh               # 服务器安装脚本
└── README.md                # 本文档
```

## 常见问题

### Q: 启动实例时报错"Operation denied"
A: 检查 RAM 权限是否正确配置，确保有 StartInstance 权限。

### Q: 流量查询失败
A: 确认 ECS 实例已开通 CDT 流量包，且 AccessKey 有 bssopenapi 权限。

### Q: 飞书消息发送失败
A: 检查 App ID/Secret 是否正确，应用是否有 im:message:send_as_bot 权限。

### Q: 多实例配置数量不匹配
A: 启动时会以飞书告警提示。检查 6 项逗号分隔配置（AK/SK/Region/ID/Limit/Name）数量必须一致或为 1。

### Q: 日报发送时间不对
A: `REPORT_HOUR` 按 **北京时间 (UTC+8)** 解析。触发条件 `current_hour >= min(REPORT_HOUR)` 且当天未发，避免 cron 延迟漏报。

## 安全建议

1. **不要使用主账号 AccessKey** - 创建 RAM 子用户
2. **最小权限原则** - 只授权需要的 API 操作
3. **定期轮换密钥** - 定期更新 AccessKey
4. **启用通知冷却** - 避免重复告警打扰