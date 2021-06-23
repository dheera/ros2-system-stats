#!/usr/bin/env python3

import json
import socket
import psutil
import rclpy
from rclpy.node import Node
import re
import sys
import time
import subprocess

from std_msgs.msg import String, Int32, Int64, Float32
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue
from sensor_msgs.msg import Temperature

def mean(list):
    return sum(list)/len(list)

class SystemStatsNode(Node):
    def __init__(self, node_name = "system_stats_node"):
        super().__init__(node_name = node_name)
        self.log = self.get_logger()
        self.clock = self.get_clock()

        if int(psutil.__version__.split(".")[0]) < 5:
            self.log.error("Please install psutil>=5.0.0")
            exit(1)

        self.declare_parameter('interval', 5.0)
        self.declare_parameter('gpu', False)
        self.gpu = self.get_parameter("gpu")._value # nvidia only for now; requires nvidia-smi

        self.timer = self.create_timer(self.get_parameter('interval')._value, self.on_timer)

        self.pub_psutil = self.create_publisher(DiagnosticArray, "diagnostics", 10)

        self.pub_cpu_temp = self.create_publisher(Temperature, "system/cpu/temp", 10)
        self.pub_cpu_usage = self.create_publisher(Float32, "system/cpu/usage", 10)
        self.pub_disk_usage = self.create_publisher(Float32, "system/disk/usage", 10)
        self.pub_net_bytes_recv= self.create_publisher(Int64, "system/net/bytes_recv", 10)
        self.pub_net_bytes_sent= self.create_publisher(Int64, "system/net/bytes_sent", 10)
        self.pub_mem_usage_virtual= self.create_publisher(Float32, "system/mem/usage_virtual", 10)
        self.pub_mem_usage_swap= self.create_publisher(Float32, "system/mem/usage_swap", 10)
    
        if self.gpu:
            self.pub_gpu_temp = self.create_publisher(Temperature, "system/gpu/temp", 10)
            self.pub_gpu_power_draw = self.create_publisher(Float32, "system/gpu/power_draw", 10)
            self.pub_gpu_power_state = self.create_publisher(String, "system/gpu/power_state", 10)

    def on_timer(self):
        p = psutil.Process()

        status = {"cpu":{}, "net":{}, "mem":{}, "disk": {}}

        status_cpu = DiagnosticStatus()
        status_cpu.name = "CPU"
        status_net = DiagnosticStatus()
        status_net.name = "Network"
        status_mem = DiagnosticStatus()
        status_mem.name = "Memory"
        status_disk = DiagnosticStatus()
        status_disk.name = "Disk"

        if self.gpu:
            status_gpu = DiagnosticStatus()
            status_gpu.name = "GPU"

        with p.oneshot():
            sensors_temperatures = psutil.sensors_temperatures()
            if 'coretemp' in sensors_temperatures:
                cpu_coretemp = mean(list(map(lambda x:x.current, sensors_temperatures['coretemp'])))
                status_cpu.values.append(KeyValue(key="coretemp", value=str(cpu_coretemp)))
                self.pub_cpu_temp.publish(Temperature(temperature=cpu_coretemp))
                
            cpu_usage = mean(psutil.cpu_percent(percpu=True))
            status_cpu.values.append(KeyValue(key="usage", value=str(cpu_usage)))
            if self.pub_cpu_usage.get_subscription_count() > 0:
                self.pub_cpu_usage.publish(Float32(data=cpu_usage))

            disk_usage = psutil.disk_usage('/').percent
            status_disk.values.append(KeyValue(key="usage", value=str(disk_usage)))
            if self.pub_disk_usage.get_subscription_count() > 0:
                self.pub_disk_usage.publish(Float32(data=disk_usage))

            net_bytes_sent = psutil.net_io_counters().bytes_sent
            net_bytes_recv = psutil.net_io_counters().bytes_recv
            status_net.values.append(KeyValue(key="bytes_sent", value=str(net_bytes_sent)))
            status_net.values.append(KeyValue(key="bytes_recv", value=str(net_bytes_recv)))
            if self.pub_net_bytes_sent.get_subscription_count() > 0:
                self.pub_net_bytes_sent.publish(Int64(data=net_bytes_sent))
            if self.pub_net_bytes_recv.get_subscription_count() > 0:
                self.pub_net_bytes_recv.publish(Int64(data=net_bytes_recv))

            net_if_addrs = psutil.net_if_addrs()
            for k in net_if_addrs:
                net_if_addrs[k] = list(filter(lambda x: x.family == socket.AF_INET, net_if_addrs[k]))
                net_if_addrs[k] = list(map(lambda x: x.address, net_if_addrs[k]))
            status_net.values.append(KeyValue(key="if_addrs", value=str(net_if_addrs)))

            mem_usage_virtual = psutil.virtual_memory().percent
            mem_usage_swap = psutil.swap_memory().percent
            status_mem.values.append(KeyValue(key="usage_virtual", value=str(mem_usage_virtual)))
            status_mem.values.append(KeyValue(key="usage_swap", value=str(mem_usage_swap)))
            if self.pub_mem_usage_virtual.get_subscription_count() > 0:
                self.pub_mem_usage_virtual.publish(Float32(data=mem_usage_virtual))
            if self.pub_mem_usage_swap.get_subscription_count() > 0:
                self.pub_mem_usage_swap.publish(Float32(data=mem_usage_swap))

        if self.gpu:
            nvinfo =  subprocess.Popen(['nvidia-smi', '-q', '-x'], stdout=subprocess.PIPE, stderr=subprocess.PIPE).communicate()

            try:
                for line in nvinfo[0].decode().split('\n'):
                    if '<gpu_temp>' in line and ' C' in line:
                        gpu_temp = float(re.search('<gpu_temp>(.*) C</gpu_temp>', line).group(1))
                        status_gpu.values.append(KeyValue(key="temp", value=str(gpu_temp)))
                        if self.pub_gpu_temp.get_subscription_count() > 0:
                            self.pub_gpu_temp.publish(Temperature(temperature=gpu_temp))
                    if '<power_draw>' in line and ' W' in line:
                        gpu_power_draw = float(re.search('<power_draw>(.*) W</power_draw>', line).group(1))
                        status_gpu.values.append(KeyValue(key="power_draw", value=str(gpu_power_draw)))
                        if self.pub_gpu_power_draw.get_subscription_count() > 0:
                            self.pub_gpu_power_draw.publish(Float32(data=gpu_power_draw))
                    if '<power_state>' in line:
                        gpu_power_state = str(re.search('<power_state>(.*)</power_state>', line).group(1))
                        status_gpu.values.append(KeyValue(key="power_state", value=str(gpu_power_state)))
                        if self.pub_gpu_power_state.get_subscription_count() > 0:
                            self.pub_gpu_power_state.publish(String(data=gpu_power_state))

            except (AttributeError, ValueError) as e:
                rospy.logwarn("error updating gpu statistics")
                status_gpu.values.append(KeyValue(key="temp", value=""))
                status_gpu.values.append(KeyValue(key="power_draw", value=""))
                status_gpu.values.append(KeyValue(key="power_state", value=""))

        msg = DiagnosticArray()
        msg.status = [status_cpu, status_net, status_mem, status_disk]
        if self.gpu:
            msg.status.append(status_gpu)

        self.pub_psutil.publish(msg)

def main(args=None):
    rclpy.init(args=args)
    node = SystemStatsNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
