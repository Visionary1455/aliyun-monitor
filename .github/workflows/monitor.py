#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
阿里云 ECS CDT 流量监控 - GitHub Actions 版本
支持飞书告警和日报
"""

import os
import sys
import json
import time
import logging
import requests
from datetime import datetime, timedelta
from aliyunsdkcore.client import AcsClient
from aliyunsdkcore.request import CommonRequest
from aliyunsdkecs.request.v20140526.StartInstanceRequest import StartInstanceRequest
from aliyunsdkecs.request.v20140526.StopInstanceRequest import StopInstanceRequest
from aliyunsdkecs.request.v20140526.DescribeInstancesRequest import DescribeInstancesRequest

# 确保 UTF-8 编码
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

# 日志文件路径
LOG_FILE = os.environ.get('LOG_FILE', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'monitor.log'))

# 配置日志 - 同时输出到 stdout 和文件
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# 清除之前的 handlers
logger.handlers.clear()

# 控制台输出
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(console_handler)

# 文件输出
try:
    log_dir = os.path.dirname(LOG_FILE)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)
    file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(file_handler)
except Exception as e:
    logger.warning(f"无法创建日志文件: {e}")

# 状态文件路径 (使用 GitHub HOME 目录，跨 step 可保持)
STATE_FILE = os.environ.get('STATE_FILE', os.path.expanduser('~/monitor_state.json'))

# 冷却时间配置
NOTIFY_COOLDOWN = 3600           # 普通事件 1 小时冷却
OVERLIMIT_COOLDOWN = 86400       # 流量超标 24 小时冷却

# 启动配置
START_WAIT_TIMEOUT = 120         # 等待启动超时(秒)
START_POLL_INTERVAL = 10         # 轮询间隔(秒)

# ---------- 配置加载 ----------
def _expand(value, n, default='', field=''):
    """
    展开逗号分隔字段：
    - 1 个值：所有实例共享
    - N 个值：按位置一一对应
    - 其他：报错（避免静默错位）
    """
    if value is None or value == '':
        return [default] * n
    parts = [v.strip() for v in str(value).split(',')]
    if len(parts) == 1:
        return parts * n
    if len(parts) == n:
        return parts
    raise ValueError(
        f"{field} 数量不匹配：实例数={n}，{field} 配置数={len(parts)}，应为 1（共享）或 {n}（一一对应）"
    )


def load_instances():
    """加载多实例配置（逗号分隔，按位置对齐）。返回 list[dict] 或 None。"""
    raw_ids = os.environ.get('ECS_INSTANCE_ID', '')
    if not raw_ids.strip():
        logger.error("缺少必需环境变量: ECS_INSTANCE_ID")
        return None

    ids = [x.strip() for x in raw_ids.split(',') if x.strip()]
    n = len(ids)
    if n == 0:
        logger.error("ECS_INSTANCE_ID 为空")
        return None

    try:
        aks     = _expand(os.environ.get('ALIYUN_ACCESS_KEY_ID'),     n, field='ALIYUN_ACCESS_KEY_ID')
        sks     = _expand(os.environ.get('ALIYUN_ACCESS_KEY_SECRET'), n, field='ALIYUN_ACCESS_KEY_SECRET')
        regions = _expand(os.environ.get('ALIYUN_REGION'),            n, field='ALIYUN_REGION')
        limits  = _expand(os.environ.get('CDT_TRAFFIC_LIMIT_GB', '180'), n, '180', field='CDT_TRAFFIC_LIMIT_GB')
        names   = _expand(os.environ.get('INSTANCE_NAME', ''),        n, '', field='INSTANCE_NAME')
    except ValueError as e:
        logger.error(f"配置错误: {e}")
        return None

    # 校验必填
    for i in range(n):
        if not aks[i] or not sks[i] or not regions[i]:
            logger.error(f"第 {i+1} 台实例 {ids[i]} 缺少 AK/SK/REGION 配置")
            return None

    instances = []
    for i in range(n):
        try:
            limit_val = float(limits[i])
        except ValueError:
            logger.error(f"第 {i+1} 台实例 {ids[i]} 的 LIMIT 不是有效数字: {limits[i]}")
            return None
        instances.append({
            'ak': aks[i],
            'sk': sks[i],
            'region': regions[i],
            'instance_id': ids[i],
            'traffic_limit': limit_val,
            'name': names[i] or f'ECS-{i+1}',
        })
    return instances

# ---------- 飞书通知 ----------
def get_feishu_access_token():
    """获取飞书应用 access_token"""
    # 使用正确的飞书应用配置
    app_id = os.environ.get('FEISHU_APP_ID')
    app_secret = os.environ.get('FEISHU_APP_SECRET')

    if not app_id or not app_secret:
        logger.warning("飞书配置缺失，跳过通知")
        return None, None

    try:
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        headers = {"Content-Type": "application/json; charset=utf-8"}
        data = {"app_id": app_id, "app_secret": app_secret}
        resp = requests.post(url, json=data, timeout=10)
        result = resp.json()

        if result.get("code") == 0:
            logger.info("飞书 access_token 获取成功")
            return result.get("tenant_access_token"), app_id
        else:
            logger.error(f"获取飞书token失败: {result}")
            return None, None
    except Exception as e:
        logger.error(f"获取飞书token异常: {e}")
        return None, None


def send_feishu_message(title, message, color_status="green"):
    """发送飞书消息给用户"""
    access_token, app_id = get_feishu_access_token()
    if not access_token:
        logger.warning("无法获取飞书 access_token")
        return

    icons = {"green": "✅", "red": "🔴", "orange": "⚠️", "blue": "📊"}
    icon = icons.get(color_status, "ℹ️")
    full_message = f"{icon} {title}\n{'─' * 20}\n{message}"

    # 从环境变量获取用户 open_id，如果没有则使用默认值
    user_open_id = os.environ.get('FEISHU_USER_OPEN_ID')

    try:
        url = "https://open.feishu.cn/open-apis/im/v1/messages"
        params = {"receive_id_type": "open_id"}

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=utf-8"
        }

        # 发送给用户 (使用 open_id)
        message_data = {
            "receive_id": user_open_id,
            "msg_type": "text",
            "content": json.dumps({"text": full_message})
        }

        resp = requests.post(url, params=params, headers=headers, json=message_data, timeout=10)
        result = resp.json()

        logger.info(f"飞书API响应: {result}")

        if result.get("code") == 0:
            logger.info(f"飞书消息发送成功: {title}")
        else:
            logger.warning(f"飞书消息发送失败: code={result.get('code')}, msg={result.get('msg')}")

    except Exception as e:
        logger.error(f"飞书消息发送异常: {e}")


def send_feishu_alert(title, message, color_status="green"):
    """发送飞书告警"""
    send_feishu_message(title, message, color_status)


def build_message(config, curr_gb=None, status_text=None, extra_lines=None):
    """构建统一格式的消息体"""
    lines = []
    lines.append(f"实例名称: {config.get('name', '-')}")
    lines.append(f"实例ID:   {config.get('instance_id', '-')}")
    if status_text is not None:
        lines.append(f"实例状态: {status_text}")
    if curr_gb is not None:
        limit = config.get('traffic_limit', 0)
        lines.append(f"流量使用: {curr_gb:.2f}GB / {limit}GB")
    if extra_lines:
        lines.append("─" * 20)
        lines.extend(extra_lines)
    lines.append(f"时间:     {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    return '\n'.join(lines)


STATUS_MAP = {
    'Running': '运行中 🟢',
    'Stopped': '已停止 ⚪',
    'Starting': '启动中 🟡',
    'Stopping': '停止中 🟡',
}


def status_label(status):
    return STATUS_MAP.get(status, status or '未知')

# ---------- 状态缓存 ----------
def load_state():
    """加载状态文件"""
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"加载状态文件失败: {e}")
    return {}


def save_state(state):
    """保存状态文件"""
    try:
        state_dir = os.path.dirname(STATE_FILE)
        if state_dir and not os.path.exists(state_dir):
            os.makedirs(state_dir, exist_ok=True)
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        logger.info(f"状态已保存到: {STATE_FILE}")
    except Exception as e:
        logger.error(f"保存状态文件失败: {e}")


def can_notify(state, instance_id, event_key, cooldown=None):
    """判断是否可以发送通知"""
    if cooldown is None:
        cooldown = NOTIFY_COOLDOWN
    last_ts = state.get(instance_id, {}).get(event_key, 0)
    return (time.time() - last_ts) >= cooldown


def mark_notified(state, instance_id, event_key):
    """标记已通知"""
    state.setdefault(instance_id, {})[event_key] = time.time()

# ---------- 阿里云 API ----------
def get_instance_status(client, instance_id):
    """获取实例状态"""
    try:
        req = DescribeInstancesRequest()
        req.set_InstanceIds(json.dumps([instance_id]))
        resp = client.do_action_with_exception(req)
        data = json.loads(resp.decode('utf-8'))
        instances = data.get("Instances", {}).get("Instance", [])
        if instances:
            return instances[0].get("Status")
        return None
    except Exception as e:
        logger.error(f"获取实例状态失败: {e}")
        return None


def get_instance_info_for_report(client, instance_id):
    """获取实例信息（用于日报）"""
    try:
        req = DescribeInstancesRequest()
        req.set_InstanceIds(json.dumps([instance_id]))
        resp = client.do_action_with_exception(req)
        data = json.loads(resp.decode('utf-8'))
        instances = data.get("Instances", {}).get("Instance", [])
        if instances:
            inst = instances[0]
            # PrivateIpAddress 是 {"IpAddress": ["x.x.x.x"]} 结构
            private_ip_obj = inst.get('VpcAttributes', {}).get('PrivateIpAddress', {})
            private_ips = private_ip_obj.get('IpAddress', []) if isinstance(private_ip_obj, dict) else []
            return {
                'status': inst.get('Status'),
                'cpu': inst.get('Cpu'),
                'memory': inst.get('Memory'),
                'ip': private_ips[0] if private_ips else '',
            }
        return {}
    except Exception as e:
        logger.error(f"获取实例信息失败: {e}")
        return {}


def get_cdt_traffic(ak, sk, region):
    """获取 CDT 流量使用量"""
    # 根据区域选择 CDT 端点
    international_regions = [
        'cn-hongkong', 'ap-southeast-1', 'ap-southeast-2', 'ap-southeast-3',
        'ap-northeast-1', 'us-west-1', 'us-east-1', 'eu-central-1',
        'eu-west-1', 'me-east-1'
    ]

    if region in international_regions:
        # 国际区使用对应的 CDT 端点
        cdt_region = region
    else:
        # 国内区使用 cn-hangzhou
        cdt_region = 'cn-hangzhou'

    logger.info(f"使用 CDT 区域: {cdt_region}")

    try:
        client = AcsClient(ak, sk, cdt_region)

        req = CommonRequest()
        req.set_domain('cdt.aliyuncs.com')
        req.set_version('2021-08-13')
        req.set_action_name('ListCdtInternetTraffic')
        req.set_method('POST')
        req.set_connect_timeout(5000)
        req.set_read_timeout(15000)

        resp = client.do_action_with_exception(req)
        data = json.loads(resp.decode('utf-8'))

        logger.info(f"CDT API 返回: {json.dumps(data, ensure_ascii=False)[:200]}")

        # 解析流量数据
        traffic_details = data.get('TrafficDetails', [])
        if not traffic_details:
            logger.warning("CDT 流量详情为空，可能没有流量消耗")
            return 0.0

        total_bytes = sum(d.get('Traffic', 0) for d in traffic_details)
        return total_bytes / (1024 ** 3)  # 转换为 GB
    except Exception as e:
        logger.error(f"获取CDT流量失败: {e}")
        return None

# ---------- 核心逻辑 ----------
def _alert(config, title, *args, **kwargs):
    """带机器名前缀的告警"""
    name = config.get('name', '')
    full_title = f"[{name}] {title}" if name else title
    send_feishu_alert(full_title, *args, **kwargs)


def check_and_act(config, state):
    """检查并执行操作。返回 (curr_gb, status) 供日报使用"""
    ak = config['ak']
    sk = config['sk']
    region = config['region']
    instance_id = config['instance_id']
    name = config['name']
    limit = config['traffic_limit']

    # 创建阿里云客户端
    client = AcsClient(ak, sk, region)

    # 1. 获取流量
    logger.info("查询 CDT 流量...")
    curr_gb = get_cdt_traffic(ak, sk, region)
    if curr_gb is None:
        logger.error("无法获取流量数据")
        if can_notify(state, instance_id, 'query_failed'):
            _alert(config,
                "流量查询失败",
                build_message(config, extra_lines=["原因: 无法获取 CDT 流量数据"]),
                "red",
            )
            mark_notified(state, instance_id, 'query_failed')
        return None, None

    logger.info(f"当前流量: {curr_gb:.2f} GB, 阈值: {limit} GB")

    # 2. 获取实例状态
    status = get_instance_status(client, instance_id)
    logger.info(f"实例状态: {status}")

    if status is None:
        logger.error("无法获取实例状态")
        if can_notify(state, instance_id, 'status_failed'):
            _alert(config,
                "无法获取实例状态",
                build_message(config, curr_gb, extra_lines=["原因: 实例不存在或 AK/SK 无权限"]),
                "red",
            )
            mark_notified(state, instance_id, 'status_failed')
        return curr_gb, None

    # 3. 决策逻辑
    if curr_gb < limit:
        # 流量正常
        if status == "Stopped":
            logger.info("流量正常，尝试启动实例...")
            try:
                start_req = StartInstanceRequest()
                start_req.set_InstanceId(instance_id)
                client.do_action_with_exception(start_req)
                logger.info("启动指令已发送")

                # 轮询等待启动
                started = False
                waited = 0
                while waited < START_WAIT_TIMEOUT:
                    time.sleep(START_POLL_INTERVAL)
                    waited += START_POLL_INTERVAL
                    real_status = get_instance_status(client, instance_id)
                    logger.info(f"等待启动... 状态: {real_status} ({waited}s)")

                    if real_status == "Running":
                        started = True
                        status = "Running"
                        break
                    elif real_status == "Stopped":
                        logger.warning("启动被拒绝，可能资源不足")
                        break

                if started:
                    logger.info("实例已启动")
                    if can_notify(state, instance_id, 'resumed'):
                        _alert(config,
                            "实例已自动启动",
                            build_message(config, curr_gb, status_label("Running"),
                                          extra_lines=["触发原因: 流量低于阈值，恢复服务"]),
                            "green",
                        )
                        mark_notified(state, instance_id, 'resumed')
                else:
                    logger.warning("启动超时")
                    if can_notify(state, instance_id, 'start_failed'):
                        _alert(config,
                            "实例启动失败",
                            build_message(config, curr_gb, status_label(get_instance_status(client, instance_id)),
                                          extra_lines=["原因: 启动超时（120秒未变为 Running）"]),
                            "red",
                        )
                        mark_notified(state, instance_id, 'start_failed')

            except Exception as e:
                logger.error(f"启动实例失败: {e}")
                if can_notify(state, instance_id, 'start_failed'):
                    _alert(config,
                        "实例启动失败",
                        build_message(config, curr_gb, status_label(status),
                                      extra_lines=[f"错误: {str(e)}"]),
                        "red",
                    )
                    mark_notified(state, instance_id, 'start_failed')

        elif status == "Running":
            logger.info("实例运行中，流量正常")
        else:
            logger.info(f"实例状态: {status}，不干预")

    else:
        # 流量超标
        if status == "Running":
            logger.info(f"流量超标({curr_gb:.2f}GB >= {limit}GB)，正在停止...")
            try:
                stop_req = StopInstanceRequest()
                stop_req.set_InstanceId(instance_id)
                client.do_action_with_exception(stop_req)
                logger.info("实例已停止")
                status = "Stopped"

                if can_notify(state, instance_id, 'overlimit', OVERLIMIT_COOLDOWN):
                    _alert(config,
                        "流量超标已关机",
                        build_message(config, curr_gb, status_label("Stopped"),
                                      extra_lines=["触发原因: 流量达到阈值，已自动关机"]),
                        "red",
                    )
                    mark_notified(state, instance_id, 'overlimit')

            except Exception as e:
                logger.error(f"停止实例失败: {e}")
                if can_notify(state, instance_id, 'stop_failed'):
                    _alert(config,
                        "实例关机失败",
                        build_message(config, curr_gb, status_label(status),
                                      extra_lines=[f"错误: {str(e)}"]),
                        "red",
                    )
                    mark_notified(state, instance_id, 'stop_failed')

        else:
            logger.info(f"已停止 - 流量: {curr_gb:.2f}GB")
            if can_notify(state, instance_id, 'overlimit', OVERLIMIT_COOLDOWN):
                _alert(config,
                    "流量超标提醒",
                    build_message(config, curr_gb, status_label(status),
                                  extra_lines=["说明: 流量已超标，保持关机状态"]),
                    "orange",
                )
                mark_notified(state, instance_id, 'overlimit')

    return curr_gb, status


def send_daily_report(instances, results, state):
    """发送多机汇总日报。results: list of (config, curr_gb, status)"""
    today = datetime.now().strftime('%Y-%m-%d')

    lines = [f"📅 日期: {today}", ""]
    running = stopped = unknown = 0
    for idx, (cfg, curr_gb, status) in enumerate(results, 1):
        if status == 'Running':
            icon, running = '🟢', running + 1
        elif status == 'Stopped':
            icon, stopped = '⚪', stopped + 1
        else:
            icon, unknown = '⚠️', unknown + 1

        gb_text = f"{curr_gb:.2f}" if curr_gb is not None else '?'
        limit = cfg.get('traffic_limit', 0)
        lines.append(f"[{idx}] {cfg['name']}  {icon}  {gb_text} / {limit} GB")

    lines.append("")
    lines.append(f"─────────────────")
    lines.append(f"共 {len(results)} 台 · 运行 {running} · 停止 {stopped}" +
                 (f" · 异常 {unknown}" if unknown else ""))
    lines.append(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    send_feishu_message(f"每日运行日报 - {today}", '\n'.join(lines), "blue")
    state['last_report_date'] = today
    logger.info("日报发送成功")


def main():
    logger.info("=" * 50)
    logger.info("阿里云 ECS 监控开始")
    logger.info("=" * 50)

    # 加载多实例配置
    instances = load_instances()
    if not instances:
        send_feishu_alert("监控错误", "配置加载失败，请检查 Secrets 配置", "red")
        sys.exit(1)

    logger.info(f"共 {len(instances)} 台实例待处理")

    # 加载状态
    state = load_state()

    # 1. 逐台执行（独立 try/except，故障隔离）
    results = []  # [(config, curr_gb, status)]
    fail_count = 0
    for idx, inst in enumerate(instances, 1):
        logger.info(f"========== [{idx}/{len(instances)}] {inst['name']} ({inst['instance_id']}) ==========")
        try:
            curr_gb, status = check_and_act(inst, state)
            results.append((inst, curr_gb, status))
        except Exception as e:
            fail_count += 1
            logger.exception(f"[{inst['name']}] 处理失败")
            results.append((inst, None, None))
            try:
                send_feishu_alert(
                    f"[{inst['name']}] 实例处理异常",
                    build_message(inst, extra_lines=[f"错误: {str(e)}"]),
                    "red",
                )
            except Exception:
                logger.exception("飞书告警发送也失败")
        finally:
            # 每台处理完立即落盘，避免单台失败丢失前面状态
            save_state(state)

    # 2. 日报（独立 try/except，不影响监控结果）
    try:
        report_hour = os.environ.get('REPORT_HOUR', '9')
        try:
            target_hours = [int(h.strip()) for h in report_hour.split(',')]
        except ValueError:
            target_hours = [9]

        current_hour = datetime.now().hour
        if current_hour in target_hours:
            today = datetime.now().strftime('%Y-%m-%d')
            if state.get('last_report_date') != today:
                logger.info("发送日报时间到，生成并发送日报...")
                send_daily_report(instances, results, state)
                save_state(state)
    except Exception as e:
        logger.exception(f"日报发送失败: {e}")

    logger.info(f"监控完成: 成功 {len(instances)-fail_count}/{len(instances)}")
    if fail_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()