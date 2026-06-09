#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
阿里云 ECS 日报生成 - GitHub Actions 版本
每天早上9点发送服务器运行情况和流量使用情况
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
from aliyunsdkecs.request.v20140526.DescribeInstancesRequest import DescribeInstancesRequest
from aliyunsdkecs.request.v20140526.DescribeInstanceMonitorDataRequest import DescribeInstanceMonitorDataRequest

# 确保 UTF-8 编码
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

# 日志配置
LOG_FILE = os.environ.get('LOG_FILE', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'report.log'))

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.handlers.clear()

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(console_handler)

try:
    file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(file_handler)
except Exception as e:
    logger.warning(f"无法创建日志文件: {e}")


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


def get_feishu_access_token():
    """获取飞书应用 access_token"""
    app_id = os.environ.get('FEISHU_APP_ID')
    app_secret = os.environ.get('FEISHU_APP_SECRET')

    if not app_id or not app_secret:
        logger.warning("飞书配置缺失")
        return None, None

    try:
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        data = {"app_id": app_id, "app_secret": app_secret}
        resp = requests.post(url, json=data, timeout=10)
        result = resp.json()

        if result.get("code") == 0:
            return result.get("tenant_access_token"), app_id
        else:
            logger.error(f"获取飞书token失败: {result}")
            return None, None
    except Exception as e:
        logger.error(f"获取飞书token异常: {e}")
        return None, None


def send_feishu_report(title, content_lines):
    """发送飞书日报"""
    access_token, app_id = get_feishu_access_token()
    if not access_token:
        logger.warning("无法获取飞书 access_token")
        return False

    # ��建���文本内容
    content = []
    for line in content_lines:
        content.append([{"tag": "text", "text": line}])

    msg_data = {
        "zh_cn": {
            "title": title,
            "content": content
        }
    }

    try:
        url = "https://open.feishu.cn/open-apis/im/v1/messages"
        params = {"receive_id_type": "app_id"}

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=utf-8"
        }

        message_data = {
            "receive_id": app_id,
            "msg_type": "post",
            "content": json.dumps(msg_data)
        }

        resp = requests.post(url, params=params, headers=headers, json=message_data, timeout=10)
        result = resp.json()

        logger.info(f"飞书日报发送响应: {result}")

        if result.get("code") == 0:
            logger.info("飞书日报发送成功")
            return True
        else:
            logger.warning(f"飞书日报发送失败: {result.get('msg')}")
            return False

    except Exception as e:
        logger.error(f"飞书日报发送异常: {e}")
        return False


def get_instance_info(client, instance_id):
    """获取实例基本信息"""
    try:
        req = DescribeInstancesRequest()
        req.set_InstanceIds(json.dumps([instance_id]))
        resp = client.do_action_with_exception(req)
        data = json.loads(resp.decode('utf-8'))
        instances = data.get("Instances", {}).get("Instance", [])
        if instances:
            inst = instances[0]
            return {
                'status': inst.get('Status'),
                'cpu': inst.get('Cpu'),
                'memory': inst.get('Memory'),
                'ip': inst.get('VpcAttributes', {}).get('PrivateIpAddress', [''])[0],
                'public_ip': inst.get('PublicIpAddress', {}).get('IpAddress', [''])[0] if inst.get('PublicIpAddress') else '无',
                'name': inst.get('InstanceName', instance_id),
                'creation_time': inst.get('CreationTime'),
            }
        return None
    except Exception as e:
        logger.error(f"获取实例信息失败: {e}")
        return None


def get_instance_monitor(client, instance_id):
    """获取实例监控数据 (CPU/内存)"""
    try:
        # 获取过去24小时的监控数据
        end_time = datetime.now()
        start_time = end_time - timedelta(hours=24)

        req = DescribeInstanceMonitorDataRequest()
        req.set_InstanceId(instance_id)
        req.set_StartTime(start_time.strftime('%Y-%m-%dT%H:%M:%SZ'))
        req.set_EndTime(end_time.strftime('%Y-%m-%dT%H:%M:%SZ'))
        req.set_Period(3600)  # 每小时

        resp = client.do_action_with_exception(req)
        data = json.loads(resp.decode('utf-8'))

        monitor_data = data.get('MonitorData', [])
        if monitor_data:
            # 计算平均值
            cpu_avg = sum(m.get('CPU', 0) for m in monitor_data) / len(monitor_data)
            mem_avg = sum(m.get('Memory', 0) for m in monitor_data) / len(monitor_data)
            return {
                'cpu_avg': round(cpu_avg, 1),
                'memory_avg': round(mem_avg, 1),
                'samples': len(monitor_data)
            }
        return None
    except Exception as e:
        logger.warning(f"获取监控数据失败: {e}")
        return None


def get_cdt_traffic(ak, sk, region):
    """获取 CDT 流量使用量"""
    international_regions = [
        'cn-hongkong', 'ap-southeast-1', 'ap-southeast-2', 'ap-southeast-3',
        'ap-northeast-1', 'us-west-1', 'us-east-1', 'eu-central-1',
        'eu-west-1', 'me-east-1'
    ]

    cdt_region = 'cn-hangzhou' if region not in international_regions else region

    try:
        client = AcsClient(ak, sk, cdt_region)

        req = CommonRequest()
        req.set_domain('cdt.aliyuncs.com')
        req.set_version('2021-08-13')
        req.set_action_name('ListCdtInternetTraffic')
        req.set_method('POST')

        resp = client.do_action_with_exception(req)
        data = json.loads(resp.decode('utf-8'))

        traffic_details = data.get('TrafficDetails', [])
        total_bytes = sum(d.get('Traffic', 0) for d in traffic_details)
        return total_bytes / (1024 ** 3)  # GB
    except Exception as e:
        logger.error(f"获取CDT流量失败: {e}")
        return None


def generate_report(config):
    """生成日报"""
    ak = config['ak']
    sk = config['sk']
    region = config['region']
    instance_id = config['instance_id']
    name = config['name']
    limit = config['traffic_limit']

    logger.info("开始生成日报...")

    # 创建客户端
    client = AcsClient(ak, sk, region)

    # 1. 获取实例信息
    logger.info("获取实例信息...")
    instance_info = get_instance_info(client, instance_id)
    if not instance_info:
        logger.error("无法获取实例信息")
        return False

    # 2. 获取监控数据
    logger.info("获取监控数据...")
    monitor_data = get_instance_monitor(client, instance_id)

    # 3. 获取流量
    logger.info("获取流量数据...")
    curr_gb = get_cdt_traffic(ak, sk, region)
    if curr_gb is None:
        curr_gb = 0

    # 4. 构建日报内容
    today = datetime.now().strftime('%Y-%m-%d')
    lines = []

    # 标题
    lines.append(f"📊 ECS 日报 - {today}")

    # 基本信息
    lines.append(f"实例名称: {name}")
    lines.append(f"实例ID: {instance_id}")
    lines.append(f"实例状态: {'🟢 运行中' if instance_info.get('status') == 'Running' else '🔴 已停止'}")

    # 配置信息
    lines.append(f"CPU: {instance_info.get('cpu')}核")
    lines.append(f"内存: {instance_info.get('memory')}MB")
    lines.append(f"私网IP: {instance_info.get('ip')}")
    lines.append(f"公网IP: {instance_info.get('public_ip')}")

    # 流量信息
    usage_pct = (curr_gb / limit * 100) if limit > 0 else 0
    if usage_pct >= 90:
        status_emoji = "🔴"
    elif usage_pct >= 70:
        status_emoji = "🟡"
    else:
        status_emoji = "🟢"

    lines.append(f"流量使用: {curr_gb:.2f}GB / {limit}GB ({usage_pct:.1f}%) {status_emoji}")

    # 监控数据
    if monitor_data:
        lines.append(f"CPU平均使用率: {monitor_data.get('cpu_avg')}%")
        lines.append(f"内存平均使用率: {monitor_data.get('memory_avg')}%")
    else:
        lines.append("CPU/内存数据: 暂无可用")

    # 生成时间
    lines.append(f"报表生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 5. 发送飞书
    title = f"📊 {name} 日报 - {today}"
    return send_feishu_report(title, lines)


def main():
    logger.info("=" * 50)
    logger.info("阿里云 ECS 日报生成开始")
    logger.info("=" * 50)

    config = load_config()
    if not config:
        logger.error("配置加载失败")
        return

    success = generate_report(config)

    if success:
        logger.info("日报生成并发送成功")
    else:
        logger.error("日报生成或发送失败")


if __name__ == "__main__":
    main()