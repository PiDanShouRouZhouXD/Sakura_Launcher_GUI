import os
import json
import subprocess
import requests
import re
import time
from PySide6.QtCore import Qt, Signal, Slot, QThread
from PySide6.QtWidgets import (
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QGroupBox,
    QSpacerItem,
    QSizePolicy,
)
from qfluentwidgets import (
    PushButton,
    PrimaryPushButton,
    MessageBox,
    FluentIcon as FIF,
)

from .common import CLOUDFLARED, CONFIG_FILE, RunSection, get_resource_path
from .ui import *


class CFShareWorker(QThread):
    tunnel_url_found = Signal(str)
    error_occurred = Signal(str)
    health_check_failed = Signal()
    metrics_updated = Signal(dict)

    def __init__(self, port, worker_url):
        super().__init__()
        self.port = port
        self.worker_url = worker_url
        self.cloudflared_process = None
        self.tunnel_url = None
        self.is_running = False

    def run(self):
        self.is_running = True
        cloudflared_path = get_resource_path(CLOUDFLARED)
        self.cloudflared_process = subprocess.Popen(
            [
                cloudflared_path,
                "tunnel",
                "--url",
                f"http://localhost:{self.port}",
                "--metrics",
                "localhost:8081",
            ]
        )

        # Wait for tunnel URL
        time.sleep(10)
        self.check_tunnel_url()

        # Start health check and metrics update
        while self.is_running:
            if not self.check_local_health_status():
                self.health_check_failed.emit()
                break
            self.update_metrics()
            time.sleep(5)

    def check_tunnel_url(self):
        try:
            metrics_response = requests.get("http://localhost:8081/metrics")
            tunnel_url_match = re.search(
                r"(https://.*?\.trycloudflare\.com)", metrics_response.text
            )
            if tunnel_url_match:
                self.tunnel_url = tunnel_url_match.group(1)
                self.tunnel_url_found.emit(self.tunnel_url)
            else:
                self.error_occurred.emit("Failed to get tunnel URL")
        except Exception as e:
            self.error_occurred.emit(f"Error checking tunnel URL: {str(e)}")

    def check_local_health_status(self):
        health_url = f"http://localhost:{self.port}/health"
        try:
            response = requests.get(health_url)
            data = response.json()
            return data["status"] in ["ok", "no slot available"]
        except Exception:
            return False

    def update_metrics(self):
        try:
            response = requests.get(f"http://localhost:{self.port}/metrics", timeout=5)
            if response.status_code == 200:
                metrics = self.parse_metrics(response.text)
                self.metrics_updated.emit(metrics)
            else:
                self.error_occurred.emit(
                    f"Error updating metrics: HTTP status {response.status_code}"
                )
        except requests.RequestException as e:
            self.error_occurred.emit(f"Error updating metrics: {str(e)}")
        except Exception as e:
            self.error_occurred.emit(f"Unexpected error updating metrics: {str(e)}")

    def parse_metrics(self, metrics_text):
        metrics = {}
        for line in metrics_text.split("\n"):
            if line.startswith("#") or not line.strip():
                continue
            try:
                key, value = line.split(" ")
                metrics[key.split(":")[-1]] = float(value)
            except ValueError:
                # 如果无法解析某一行,跳过该行
                continue
        return metrics

    def stop(self):
        self.is_running = False
        if self.cloudflared_process:
            self.cloudflared_process.terminate()
            try:
                self.cloudflared_process.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                self.cloudflared_process.kill()
            self.cloudflared_process = None


class CFShareSection(RunSection):
    def __init__(self, title, main_window, parent=None):
        super().__init__(title, main_window, parent)
        self._init_ui()
        self.load_settings()
        self.worker = None

    def _init_ui(self):
        layout = QVBoxLayout()

        buttons_group = QGroupBox("")
        buttons_layout = QHBoxLayout()

        self.start_button = PrimaryPushButton(FIF.PLAY, "上线", self)
        self.start_button.clicked.connect(self.start_cf_share)
        self.start_button.setFixedSize(110, 30)
        buttons_layout.addWidget(self.start_button)

        self.stop_button = PushButton(FIF.CLOSE, "下线", self)
        self.stop_button.clicked.connect(self.stop_cf_share)
        self.stop_button.setEnabled(False)
        self.stop_button.setFixedSize(110, 30)
        buttons_layout.addWidget(self.stop_button)

        self.save_button = PushButton(FIF.SAVE, "保存", self)
        self.save_button.clicked.connect(self.save_settings)
        self.save_button.setFixedSize(110, 30)
        buttons_layout.addWidget(self.save_button)

        self.refresh_slots_button = PushButton(FIF.SYNC, "刷新在线数量", self)
        self.refresh_slots_button.clicked.connect(self.refresh_slots)
        self.refresh_slots_button.setFixedSize(150, 30)
        buttons_layout.addWidget(self.refresh_slots_button)

        buttons_layout.setAlignment(Qt.AlignRight)
        buttons_group.setStyleSheet(
            """ QGroupBox {border: 0px solid darkgray; background-color: #202020; border-radius: 8px;}"""
        )
        buttons_group.setLayout(buttons_layout)
        layout.addWidget(buttons_group)

        layout.addWidget(QLabel("WORKER_URL:"))
        self.worker_url_input = UiLineEdit(
            self, "输入WORKER_URL", "https://sakura-share.one"
        )
        layout.addWidget(self.worker_url_input)

        self.status_label = QLabel("状态: 未运行")
        layout.addWidget(self.status_label)

        self.slots_status_label = QLabel("在线slot数量: 未知")
        layout.addWidget(self.slots_status_label)

        # 更新指标
        self.metrics_labels = {
            "prompt_tokens_total": QLabel("提示词 tokens 总数: 暂无数据"),
            "prompt_seconds_total": QLabel("提示词处理总时间: 暂无数据"),
            "tokens_predicted_total": QLabel("生成的 tokens 总数: 暂无数据"),
            "tokens_predicted_seconds_total": QLabel("生成处理总时间: 暂无数据"),
            "n_decode_total": QLabel("llama_decode() 调用总次数: 暂无数据"),
            "n_busy_slots_per_decode": QLabel(
                "每次 llama_decode() 调用的平均忙碌槽位数: 暂无数据"
            ),
            "prompt_tokens_seconds": QLabel("提示词平均吞吐量: 暂无数据"),
            "predicted_tokens_seconds": QLabel("生成平均吞吐量: 暂无数据"),
            "kv_cache_usage_ratio": QLabel("KV-cache 使用率: 暂无数据"),
            "kv_cache_tokens": QLabel("KV-cache tokens: 暂无数据"),
            "requests_processing": QLabel("正在处理的请求数: 暂无数据"),
            "requests_deferred": QLabel("延迟的请求数: 暂无数据"),
        }

        tooltips = {
            "prompt_tokens_total": "已处理的提示词 tokens 总数",
            "prompt_seconds_total": "提示词处理的总时间",
            "tokens_predicted_total": "已生成的 tokens 总数",
            "tokens_predicted_seconds_total": "生成处理的总时间",
            "n_decode_total": "llama_decode() 函数的总调用次数",
            "n_busy_slots_per_decode": "每次 llama_decode() 调用时的平均忙碌槽位数",
            "prompt_tokens_seconds": "提示词的平均处理速度",
            "predicted_tokens_seconds": "生成的平均速度",
            "kv_cache_usage_ratio": "KV-cache 的使用率（1 表示 100% 使用）",
            "kv_cache_tokens": "KV-cache 中的 token 数量",
            "requests_processing": "当前正在处理的请求数",
            "requests_deferred": "被延迟的请求数",
        }

        metrics_title = QLabel("\n数据统计")
        metrics_title.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(metrics_title)

        for key, label in self.metrics_labels.items():
            label.setToolTip(tooltips[key])
            layout.addWidget(label)

        description = QLabel()
        description.setText(
            """
        <html>
        <body>
        <h3>说明</h3>
        <p>这是一个一键分享你本地部署的Sakura模型给其他用户（成为帕鲁）的工具，服务端部署请按照下面的仓库的文档进行。</p>
        <ol>
            <li>请确保本地服务已启动。</li>
            <li>请确保WORKER_URL正确。<br>
            <span>如无特殊需求，请使用默认的WORKER_URL，此链接是由共享脚本开发者本人维护的。</span></li>
            <li>目前仅支持Windows系统，其他系统请自行更改脚本。</li>
            <li>目前仅支持以下两种模型（服务端有模型指纹检查）：
                <ul>
                    <li>sakura-14b-qwen2beta-v0.9.2-iq4xs</li>
                    <li>sakura-14b-qwen2beta-v0.9.2-q4km</li>
                </ul>
            </li>
            <li>当你不想成为帕鲁的时候，也可以通过这个链接来访问其他帕鲁的模型，但不保证服务的可用性与稳定性。</li>
        </ol>
        </body>
        </html>
        """
        )
        description.setTextFormat(Qt.RichText)
        description.setWordWrap(True)
        description.setStyleSheet(
            """
            QLabel {
                border-radius: 5px;
                padding: 15px;
            }
        """
        )
        layout.addWidget(description)

        sakura_share_url = "https://github.com/1PercentSync/sakura-share"
        link = QLabel(f"<a href='{sakura_share_url}'>点击前往仓库</a>")
        link.setOpenExternalLinks(True)
        link.setAlignment(Qt.AlignCenter)
        link.setStyleSheet(
            """
            QLabel {
                padding: 10px;
            }
        """
        )
        layout.addWidget(link)

        layout.addItem(QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding))

        self.setLayout(layout)

    @Slot()
    def start_cf_share(self):
        worker_url = self.worker_url_input.text().strip()
        if not worker_url:
            MessageBox("错误", "请输入WORKER_URL", self).exec_()
            return
        port = self.main_window.run_server_section.port_input.text().strip()
        if not port:
            MessageBox("错误", "请在运行server面板中设置端口号", self).exec_()
            return
        if not self.check_local_health_status():
            MessageBox(
                "错误", "本地服务未启动或未正常运行，请先启动本地服务", self
            ).exec_()
            return

        self.worker = CFShareWorker(port, worker_url)
        self.worker.tunnel_url_found.connect(self.on_tunnel_url_found)
        self.worker.error_occurred.connect(self.on_error)
        self.worker.health_check_failed.connect(self.stop_cf_share)
        self.worker.metrics_updated.connect(self.update_metrics_display)
        self.worker.start()

        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)

    @Slot(str)
    def on_tunnel_url_found(self, tunnel_url):
        self.tunnel_url = tunnel_url
        self.main_window.log_info(f"Tunnel URL: {self.tunnel_url}")
        self.register_node()
        self.status_label.setText(f"状态: 运行中 - {self.tunnel_url}")
        self.main_window.createSuccessInfoBar("成功", "已经成功启动分享。")

    @Slot(str)
    def on_error(self, error_message):
        self.main_window.log_info(error_message)
        self.stop_cf_share()

    @Slot()
    def stop_cf_share(self):
        if self.worker:
            self.worker.stop()
            self.worker.wait()
            self.worker = None

        if self.tunnel_url:
            self.take_node_offline()
            self.tunnel_url = None

        self.status_label.setText("状态: 未运行")
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)

    @Slot(dict)
    def update_metrics_display(self, metrics):
        for key, label in self.metrics_labels.items():
            if key in metrics:
                value = metrics[key]
                if key in ["prompt_tokens_total", "tokens_predicted_total"]:
                    label.setText(f"{label.text().split(':')[0]}: {value:.0f} tokens")
                elif key in ["prompt_seconds_total", "tokens_predicted_seconds_total"]:
                    label.setText(f"{label.text().split(':')[0]}: {value:.2f} 秒")
                elif key == "n_decode_total":
                    label.setText(f"{label.text().split(':')[0]}: {value:.0f} 次")
                elif key == "n_busy_slots_per_decode":
                    label.setText(f"{label.text().split(':')[0]}: {value:.2f}")
                elif key in ["prompt_tokens_seconds", "predicted_tokens_seconds"]:
                    label.setText(f"{label.text().split(':')[0]}: {value:.2f} tokens/s")
                elif key == "kv_cache_usage_ratio":
                    label.setText(f"{label.text().split(':')[0]}: {value*100:.2f}%")
                elif key == "kv_cache_tokens":
                    label.setText(f"{label.text().split(':')[0]}: {value:.0f} tokens")
                elif key in ["requests_processing", "requests_deferred"]:
                    label.setText(f"{label.text().split(':')[0]}: {value:.0f}")
                else:
                    label.setText(f"{label.text().split(':')[0]}: {value:.2f}")
            else:
                # 如果某个指标不存在,保持原来的文本
                pass

    def save_settings(self):
        settings = {"worker_url": self.worker_url_input.text().strip()}
        if not os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump({}, f, ensure_ascii=False, indent=4)

        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config_data = json.load(f)
            config_data.update(settings)

        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config_data, f, ensure_ascii=False, indent=4)

    def load_settings(self):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                settings = json.load(f)
        except FileNotFoundError:
            return
        except json.JSONDecodeError:
            return
        self.worker_url_input.setText(
            settings.get("worker_url", "https://sakura-share.one")
        )

    def refresh_slots(self):
        worker_url = self.worker_url_input.text().strip()
        if not worker_url:
            self.slots_status_label.setText("在线slot数量: 获取失败 - WORKER_URL为空")
            return

        try:
            response = requests.get(f"{worker_url}/health")
            data = response.json()
            if data["status"] == "ok":
                slots_idle = data.get("slots_idle", "未知")
                slots_processing = data.get("slots_processing", "未知")
                self.slots_status_label.setText(
                    f"在线slot数量: 空闲 {slots_idle}, 处理中 {slots_processing}"
                )
            else:
                self.slots_status_label.setText("在线slot数量: 获取失败")
        except Exception as e:
            self.slots_status_label.setText(f"在线slot数量: 获取失败 - {str(e)}")

    def check_local_health_status(self):
        port = self.main_window.run_server_section.port_input.text().strip()
        health_url = f"http://localhost:{port}/health"
        try:
            response = requests.get(health_url)
            data = response.json()
            if data["status"] in ["ok", "no slot available"]:
                return True
            else:
                self.main_window.log_info(
                    f"Local health status: Not healthy - {data['status']}"
                )
                return False
        except Exception as e:
            self.main_window.log_info(f"Error checking local health status: {str(e)}")
            return False

    def register_node(self):
        try:
            api_response = requests.post(
                f"{self.worker.worker_url}/register-node",
                json={"url": self.tunnel_url},
                headers={"Content-Type": "application/json"},
            )
            self.main_window.log_info(f"API Response: {api_response.text}")
        except Exception as e:
            self.main_window.log_info(f"Error registering node: {str(e)}")

    def take_node_offline(self):
        try:
            offline_response = requests.post(
                f"{self.worker.worker_url}/delete-node",
                json={"url": self.tunnel_url},
                headers={"Content-Type": "application/json"},
            )
            self.main_window.log_info(f"Offline Response: {offline_response.text}")
        except Exception as e:
            self.main_window.log_info(f"Error taking node offline: {str(e)}")
