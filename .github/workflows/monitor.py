#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
阿里云 ECS CDT 流量监控 - GitHub Actions 版本
支持飞书告警
"""

import os
import json
import time
import logging
import requests
from aliyunsdkcore.client import AcsClient
from aliyunsdkcore.request import CommonRequest
from aliyunsdkecs.request.v20140526.StartInstanceRequest import StartInstanceRequest
from aliyunsdkecs.request.v20140526.StopInstanceRequest import StopInstanceRequest
from aliyunsdkecs.request.v20140526.DescribeInstancesRequest import DescribeInstancesRequest

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 状态文件路径 (GitHub Actions 使用临时目录)
STATE_FILE = os.environ.get('STATE_FILE', '/tmp/monitor_state.json')

# 冷却时间配置
NOTIFY_COOLDOWN = 3600           # 普通事件 1 小时冷却
OVERLIMIT_COOLDOWN = 86400       # 流量超标 24 小时冷却

# 启动配置
START_WAIT_TIMEOUT = 120         # 等待启动超时(秒)
START_POLL_INTERVAL = 10         # 轮询间隔(秒)

# ---------- 配置加载 ----------
def load_config():
    """从环境变量加载配置"""
    required = [
        'ALIYUN_ACCESS_KEY_ID',
        'ALIYUN_ACCESS_KEY_SECRET',
        'ALIYUN_REGION',
        'ECS_INSTANCE_ID',
    ]
    for var in required:
        if not os.environ.get(var):
            logger.error(f"缺少必需环境变量: {var}")
            return None

    return {
        'ak': os.environ.get('ALIYUN_ACCESS_KEY_ID'),
        'sk': os.environ.get('ALIYUN_ACCESS_KEY_SECRET'),
        'region': os.environ.get('ALIYUN_REGION'),
        'instance_id': os.environ.get('ECS_INSTANCE_ID'),
        'traffic_limit': int(os.environ.get('CDT_TRAFFIC_LIMIT_GB', '180')),
        'feishu_app_id': os.environ.get('FEISHU_APP_ID'),
        'feishu_app_secret': os.environ.get('FEISHU_APP_SECRET'),
        'name': os.environ.get('INSTANCE_NAME', 'ECS-Monitor'),
    }

# ---------- 飞书通知 ----------
def get_feishu_access_token():
    """获取飞书应用 access_token"""
    app_id = os.environ.get('FEISHU_APP_ID')
    app_secret = os.environ.get('FEISHU_APP_SECRET')

    if not app_id or not app_secret:
        logger.warning("飞书配置缺失，跳过通知")
        return None

    try:
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        headers = {"Content-Type": "application/json; charset=utf-8"}
        data = {"app_id": app_id, "app_secret": app_secret}
        resp = requests.post(url, json=data, timeout=10)
        result = resp.json()

        if result.get("code") == 0:
            return result.get("tenant_access_token")
        else:
            logger.error(f"获取飞书token失败: {result}")
            return None
    except Exception as e:
        logger.error(f"获取飞书token异常: {e}")
        return None


def send_feishu_message(title, message, color_status="green"):
    """发送飞书消息"""
    access_token = get_feishu_access_token()
    if not access_token:
        return

    # 颜色映射
    colors = {
        "green": "#00C471",
        "red": "#F5222D",
        "orange": "#FA8C16",
    }
    color = colors.get(color_status, "#00C471")

    icon = "✅" if color_status == "green" else "⚠️"

    # 构建富文本消息
    msg_content = {
        "zh_cn": {
            "title": f"{icon} {title}",
            "content": [
                [
                    {"tag": "text", "text": f"实例: {os.environ.get('INSTANCE_NAME', 'ECS-Monitor')}\n"},
                    {"tag": "text", "text": f"消息: {message}\n"},
                    {"tag": "text", "text": f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}"}
                ]
            ]
        }
    }

    try:
        # 获取接收者 ID (可选，这里发送给所有人)
        # 如果需要发给特定用户，需要先获取 user_id
        url = "https://open.feishu.cn/open-apis/im/v1/messages"
        params = {"receive_id_type": "chat_id"}
        # 这里使用应用自身的能力发送消息 (需要配置应用权限)
        # 简单版：使用 webhook 方式发送

        # 备用方案：使用应用消息发送
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=utf-8"
        }

        # 发送应用消息到群聊或用户
        # 这里使用简化的文本消息发送
        message_data = {
            "receive_id": os.environ.get('FEISHU_CHAT_ID', ''),
            "msg_type": "text",
            "content": json.dumps({"text": f"{icon} *{title}*\n\n{message}"})
        }

        # 如果配置了chat_id，发送到群
        if os.environ.get('FEISHU_CHAT_ID'):
            resp = requests.post(url, params=params, headers=headers, json=message_data, timeout=10)
            logger.info(f"飞书消息发送响应: {resp.text}")
        else:
            logger.info("未配置 FEISHU_CHAT_ID，跳过发送")

    except Exception as e:
        logger.error(f"飞书消息发送失败: {e}")


def send_feishu_alert(title, message, color_status="green"):
    """发送飞书告警 (兼容旧接口)"""
    send_feishu_message(title, message, color_status)

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
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
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


def get_cdt_traffic(ak, sk):
    """获取 CDT 流量使用量"""
    try:
        # 使用 cn-hangzhou 区域查询 CDT
        client = AcsClient(ak, sk, 'cn-hangzhou')

        req = CommonRequest()
        req.set_domain('cdt.aliyuncs.com')
        req.set_version('2021-08-13')
        req.set_action_name('ListCdtInternetTraffic')
        req.set_method('POST')
        req.set_connect_timeout(5000)
        req.set_read_timeout(15000)

        resp = client.do_action_with_exception(req)
        data = json.loads(resp.decode('utf-8'))

        total_bytes = sum(d.get('Traffic', 0) for d in data.get('TrafficDetails', []))
        return total_bytes / (1024 ** 3)  # 转换为 GB
    except Exception as e:
        logger.error(f"获取CDT流量失败: {e}")
        return None

# ---------- 核心逻辑 ----------
def check_and_act(config, state):
    """检查并执行操作"""
    ak = config['ak']
    sk = config['sk']
    region = config['region']
    instance_id = config['instance_id']
    name = config['name']
    limit = config['traffic_limit']

    # 创建阿里���客户端
    try:
        client = AcsClient(ak, sk, region)
    except Exception as e:
        logger.error(f"创建阿里云客户端失败: {e}")
        return

    # 1. 获取流量
    logger.info("查询 CDT 流量...")
    curr_gb = get_cdt_traffic(ak, sk)
    if curr_gb is None:
        logger.error("无法获取流量数据")
        if can_notify(state, instance_id, 'query_failed'):
            send_feishu_alert("流量查询失败", "无法获取 CDT 流量数据", "red")
            mark_notified(state, instance_id, 'query_failed')
        return

    logger.info(f"当前流量: {curr_gb:.2f} GB, 阈值: {limit} GB")

    # 2. 获取实例状态
    status = get_instance_status(client, instance_id)
    logger.info(f"实例状态: {status}")

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
                        break
                    elif real_status == "Stopped":
                        logger.warning("启动被拒绝，可能资源不足")
                        break

                if started:
                    logger.info("✅ 实例已启动")
                    if can_notify(state, instance_id, 'resumed'):
                        send_feishu_alert("实例已启动", f"流量: {curr_gb:.2f}GB\n状态: 运行中 ✅", "green")
                        mark_notified(state, instance_id, 'resumed')
                else:
                    logger.warning("启动超时")
                    if can_notify(state, instance_id, 'start_failed'):
                        send_feishu_alert("启动失败", f"流量: {curr_gb:.2f}GB\n启动超时", "red")
                        mark_notified(state, instance_id, 'start_failed')

            except Exception as e:
                logger.error(f"启动实例失败: {e}")
                if can_notify(state, instance_id, 'start_failed'):
                    send_feishu_alert("启动失败", f"流量: {curr_gb:.2f}GB\n错误: {str(e)}", "red")
                    mark_notified(state, instance_id, 'start_failed')

        elif status == "Running":
            logger.info("实例运行中，流量正常 ✅")
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

                if can_notify(state, instance_id, 'overlimit', OVERLIMIT_COOLDOWN):
                    send_feishu_alert("流量超标已关机", f"当前流量: {curr_gb:.2f}GB\n阈值: {limit}GB\n已执行关机 ✅", "red")
                    mark_notified(state, instance_id, 'overlimit')

            except Exception as e:
                logger.error(f"停止实例失败: {e}")
                if can_notify(state, instance_id, 'stop_failed'):
                    send_feishu_alert("关机失败", f"流量: {curr_gb:.2f}GB\n错误: {str(e)}", "red")
                    mark_notified(state, instance_id, 'stop_failed')

        else:
            logger.info(f"已停止 - 流量: {curr_gb:.2f}GB")
            if can_notify(state, instance_id, 'overlimit', OVERLIMIT_COOLDOWN):
                send_feishu_alert("流量超标提醒", f"当前流量: {curr_gb:.2f}GB\n阈值: {limit}GB\n状态: 已保持关机", "orange")
                mark_notified(state, instance_id, 'overlimit')


def main():
    logger.info("=" * 50)
    logger.info("阿里云 ECS 监控开始")
    logger.info("=" * 50)

    # 加载配置
    config = load_config()
    if not config:
        logger.error("配置加载失败")
        return

    # 加载状态
    state = load_state()

    # 执行监控
    check_and_act(config, state)

    # 保存状态
    save_state(state)

    logger.info("监控完成")


if __name__ == "__main__":
    main()