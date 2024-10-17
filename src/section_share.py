import os
import json
import subprocess
import requests
import re
from PySide6.QtCore import (
    Qt,
    Signal,
    Slot,
    QThread,
    QThreadPool,
    QRunnable,
    QTimer,
    QMetaObject,
    QObject,
)
from PySide6.QtWidgets import (
    QVBoxLayout,
    QLabel,
    QSpacerItem,
    QSizePolicy,
    QTableWidgetItem,
    QHeaderView,
    QFrame,
    QStackedWidget,
    QWidget,
)
from qfluentwidgets import (
    PushButton,
    PrimaryPushButton,
    MessageBox,
    SegmentedWidget,
    FluentIcon as FIF,
    TableWidget,
)

from .common import CLOUDFLARED, CONFIG_FILE, get_resource_path
from .ui import *


class SlotsRefreshWorker(QRunnable):
    def __init__(self, worker_url, callback):
        super().__init__()
        self.worker_url = worker_url
        self.callback = callback

    def run(self):
        try:
            response = requests.get(f"{self.worker_url}/health")
            data = response.json()
            if data["status"] == "ok":
                slots_idle = data.get("slots_idle", "未知")
                slots_processing = data.get("slots_processing", "未知")
                status = f"在线slot数量: 空闲 {slots_idle}, 处理中 {slots_processing}"
            else:
                status = "在线slot数量: 获取失败"
        except Exception as e:
            status = f"在线slot数量: 获取失败 - {str(e)}"
        self.callback(status)


class RankingRefreshWorker(QRunnable):
    class Signals(QObject):
        result = Signal(object)

    def __init__(self, worker_url):
        super().__init__()
        self.worker_url = worker_url
        self.signals = self.Signals()

    def run(self):
        try:
            response = requests.get(f"{self.worker_url}/ranking")
            data = response.json()
            if isinstance(data, dict):
                self.signals.result.emit(data)
            else:
                self.signals.result.emit({"error": "数据格式错误"})
        except Exception as e:
            self.signals.result.emit({"error": f"获取失败 - {str(e)}"})


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
        self.timer = QTimer()
        self.timer.timeout.connect(self.check_and_update)

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
        QTimer.singleShot(10000, self.check_tunnel_url)

        # Start health check and metrics update
        self.timer.start(5000)  # 每5秒检查一次

    def check_and_update(self):
        if not self.check_local_health_status():
            self.health_check_failed.emit()
            self.stop()
        else:
            self.update_metrics()

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
        self.timer.stop()
        if self.cloudflared_process:
            self.cloudflared_process.terminate()
            try:
                self.cloudflared_process.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                self.cloudflared_process.kill()
            self.cloudflared_process = None


class CFShareSection(QFrame):
    def __init__(self, title, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.setObjectName(title.replace(" ", "-"))
        self.title = title

        self._init_ui()
        self.load_settings()
        self.worker = None

    def _init_ui(self):
        # 创建标签页切换控件
        pivot = SegmentedWidget()
        stacked_widget = QStackedWidget()

        # 创建不同的页面
        self.share_page = QWidget()
        self.metrics_page = QWidget()
        self.ranking_page = QWidget()

        self.init_share_page()
        self.init_metrics_page()
        self.init_ranking_page()

        def add_sub_interface(widget: QWidget, object_name, text):
            widget.setObjectName(object_name)
            stacked_widget.addWidget(widget)
            pivot.addItem(
                routeKey=object_name,
                text=text,
                onClick=lambda: stacked_widget.setCurrentWidget(widget),
            )

        add_sub_interface(self.share_page, "share_page", "共享设置")
        add_sub_interface(self.metrics_page, "metrics_page", "本地数据统计")
        add_sub_interface(self.ranking_page, "ranking_page", "在线排名")

        pivot.setCurrentItem(stacked_widget.currentWidget().objectName())

        self.setLayout(
            UiCol(
                pivot,
                stacked_widget,
            )
        )

    def init_share_page(self):
        layout = QVBoxLayout(self.share_page)
        layout.setContentsMargins(0, 0, 0, 0)  # 设置内部边距

        self.refresh_slots_button = PushButton(FIF.SYNC, "刷新在线数量")
        self.refresh_slots_button.clicked.connect(self.refresh_slots)

        self.save_button = PushButton(FIF.SAVE, "保存")
        self.save_button.clicked.connect(self.save_settings)

        self.stop_button = PushButton(FIF.CLOSE, "下线")
        self.stop_button.clicked.connect(self.stop_cf_share)
        self.stop_button.setEnabled(False)

        self.start_button = PrimaryPushButton(FIF.PLAY, "上线")
        self.start_button.clicked.connect(self.start_cf_share)

        layout.addWidget(
            UiButtonGroup(
                self.refresh_slots_button,
                self.save_button,
                self.stop_button,
                self.start_button,
            )
        )

        self.worker_url_input = UiLineEdit("输入WORKER_URL", "https://sakura-share.one")
        layout.addLayout(UiOptionRow("链接", self.worker_url_input))

        self.tg_token_input = UiLineEdit("可选，从@SakuraShareBot获取，用于统计贡献")
        layout.addLayout(UiOptionRow("令牌", self.tg_token_input))

        self.status_label = QLabel("状态: 未运行")
        layout.addWidget(self.status_label)

        self.slots_status_label = QLabel("在线slot数量: 未知")
        layout.addWidget(self.slots_status_label)

        # 添加说明文本
        description = QLabel()
        description.setText(
            """
            <html>
            <body>
            <h3>说明</h3>
            <p>这是一个一键分享你本地部署的Sakura模型给其他用户（成为帕鲁）的工具，服务端部署请按照下面的仓库的文档进行。</p>
            <p>注意：</p>
            <ol>
                <li><span style='color: #AA0000; font-weight: bold;'>在线排名功能暂时不可用，请耐心等待服务端升级。</span></li>
                <li>请确保本地服务已启动。</li>
                <li>请确保「链接」正确。</li>
                <li>如无特殊需求，请使用默认的链接。此链接是由共享脚本开发者本人维护的。</li>
                <li>目前仅支持Windows系统，其他系统请自行更改脚本。</li>
                <li>目前仅支持一种模型：
                    <ul>
                        <li>sakura-14b-qwen2.5-v1.0-iq4xs.gguf</li>
                    </ul>
                </li>
                <li>当你不想成为帕鲁的时候，也可以通过这个链接来访问其他帕鲁的模型，但不保证服务的可用性与稳定性。</li>
            </ol>
            <p>关于贡献统计：</p>
            <ol>
                <li>贡献统计是可选的，如果你不希望参与贡献统计，可以不填写「令牌」。</li>
                <li>贡献统计需要你从<a href='https://t.me/SakuraShareBot'>@SakuraShareBot</a>获取「令牌（Token）」，并在此处填写。</li>
                <li>可以在「在线排名」标签中查看贡献排名。</li>
                <li>具体说明请参考<a href='https://github.com/1PercentSync/sakura-share'>Sakura Share</a>。</li>
            </ol>
            </body>
            </html>
            """
        )
        description.setTextFormat(Qt.RichText)
        description.setOpenExternalLinks(True)
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

    def init_metrics_page(self):
        layout = QVBoxLayout(self.metrics_page)
        layout.setContentsMargins(0, 0, 0, 0)  # 设置内部边距

        self.metrics_table = TableWidget(self)
        self.metrics_table.setColumnCount(2)
        self.metrics_table.setHorizontalHeaderLabels(["指标", "值"])
        self.metrics_table.verticalHeader().setVisible(False)
        self.metrics_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        metrics_data = [
            ("提示词 tokens 总数", "暂无数据"),
            ("提示词处理总时间", "暂无数据"),
            ("生成的 tokens 总数", "暂无数据"),
            ("生成处理总时间", "暂无数据"),
            ("llama_decode() 调用总次数", "暂无数据"),
            ("每次 llama_decode() 调用的平均忙碌槽位数", "暂无数据"),
            ("提示词平均吞吐量", "暂无数据"),
            ("生成平均吞吐量", "暂无数据"),
            ("KV-cache 使用率", "暂无数据"),
            ("KV-cache tokens", "暂无数据"),
            ("正在处理的请求数", "暂无数据"),
            ("延迟的请求数", "暂无数据"),
        ]

        self.metrics_table.setRowCount(len(metrics_data))
        for row, (metric, value) in enumerate(metrics_data):
            self.metrics_table.setItem(row, 0, QTableWidgetItem(metric))
            self.metrics_table.setItem(row, 1, QTableWidgetItem(value))

        layout.addWidget(self.metrics_table)

        tooltips = {
            "提示词 tokens 总数": "已处理的提示词 tokens 总数",
            "提示词处理总时间": "提示词处理的总时间",
            "生成的 tokens 总数": "已生成的 tokens 总数",
            "生成处理总时间": "生成处理的总时间",
            "llama_decode() 调用总次数": "llama_decode() 函数的总调用次数",
            "每次 llama_decode() 调用的平均忙碌槽位数": "每次 llama_decode() 调用时的平均忙碌槽位数",
            "提示词平均吞吐量": "提示词的平均处理速度",
            "生成平均吞吐量": "生成的平均速度",
            "KV-cache 使用率": "KV-cache 的使用率（1 表示 100% 使用）",
            "KV-cache tokens": "KV-cache 中的 token 数量",
            "正在处理的请求数": "当前正在处理的请求数",
            "延迟的请求数": "被延迟的请求数",
        }

        for row in range(self.metrics_table.rowCount()):
            metric_item = self.metrics_table.item(row, 0)
            if metric_item:
                metric_item.setToolTip(tooltips.get(metric_item.text(), ""))

    def init_ranking_page(self):
        layout = QVBoxLayout(self.ranking_page)
        layout.setContentsMargins(0, 0, 0, 0)  # 设置内部边距

        self.ranking_table = TableWidget(self)
        self.ranking_table.setColumnCount(2)
        self.ranking_table.setHorizontalHeaderLabels(["用户名", "计数"])
        self.ranking_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        layout.addWidget(self.ranking_table)

        self.refresh_ranking_button = PushButton(FIF.SYNC, "刷新排名", self)
        self.refresh_ranking_button.clicked.connect(self.refresh_ranking)
        layout.addWidget(self.refresh_ranking_button)

    @Slot()
    def start_cf_share(self):
        worker_url = self.worker_url_input.text().strip()
        if not worker_url:
            MessageBox("错误", "请输入WORKER_URL", self).exec_()
            return
        port = self.main_window.run_server_section.port_input.text().strip()
        if not port:
            MessageBox("错误", "请在运行面板中设置端口号", self).exec_()
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
            QMetaObject.invokeMethod(self.worker, "stop", Qt.QueuedConnection)
            self.worker.wait()
            self.worker = None

        if self.tunnel_url:
            self.take_node_offline()
            self.tunnel_url = None

        self.status_label.setText("状态: 未运行")
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)

        self.status_label.setText("状态: 未运行")
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)

    @Slot(dict)
    def update_metrics_display(self, metrics):
        for row in range(self.metrics_table.rowCount()):
            metric_item = self.metrics_table.item(row, 0)
            value_item = self.metrics_table.item(row, 1)
            if metric_item and value_item:
                metric_text = metric_item.text()
                key = self.get_metric_key(metric_text)
                if key in metrics:
                    value = metrics[key]
                    if key in ["prompt_tokens_total", "tokens_predicted_total"]:
                        value_item.setText(f"{value:.0f} tokens")
                    elif key in [
                        "prompt_seconds_total",
                        "tokens_predicted_seconds_total",
                    ]:
                        value_item.setText(f"{value:.2f} 秒")
                    elif key == "n_decode_total":
                        value_item.setText(f"{value:.0f} 次")
                    elif key == "n_busy_slots_per_decode":
                        value_item.setText(f"{value:.2f}")
                    elif key in ["prompt_tokens_seconds", "predicted_tokens_seconds"]:
                        value_item.setText(f"{value:.2f} tokens/s")
                    elif key == "kv_cache_usage_ratio":
                        value_item.setText(f"{value*100:.2f}%")
                    elif key == "kv_cache_tokens":
                        value_item.setText(f"{value:.0f} tokens")
                    elif key in ["requests_processing", "requests_deferred"]:
                        value_item.setText(f"{value:.0f}")
                    else:
                        value_item.setText(f"{value:.2f}")

    def get_metric_key(self, metric_text):
        key_map = {
            "提示词 tokens 总数": "prompt_tokens_total",
            "提示词处理总时间": "prompt_seconds_total",
            "生成的 tokens 总数": "tokens_predicted_total",
            "生成处理总时间": "tokens_predicted_seconds_total",
            "llama_decode() 调用总次数": "n_decode_total",
            "每次 llama_decode() 调用的平均忙碌槽位数": "n_busy_slots_per_decode",
            "提示词平均吞吐量": "prompt_tokens_seconds",
            "生成平均吞吐量": "predicted_tokens_seconds",
            "KV-cache 使用率": "kv_cache_usage_ratio",
            "KV-cache tokens": "kv_cache_tokens",
            "正在处理的请求数": "requests_processing",
            "延迟的请求数": "requests_deferred",
        }
        return key_map.get(metric_text, "")

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

    @Slot()
    def refresh_slots(self):
        worker_url = self.worker_url_input.text().strip()
        if not worker_url:
            self.slots_status_label.setText("在线slot数量: 获取失败 - WORKER_URL为空")
            return

        self.refresh_slots_button.setEnabled(False)
        self.slots_status_label.setText("在线slot数量: 正在获取...")

        worker = SlotsRefreshWorker(worker_url, self.update_slots_status)
        QThreadPool.globalInstance().start(worker)

    @Slot(str)
    def update_slots_status(self, status):
        self.slots_status_label.setText(status)
        self.refresh_slots_button.setEnabled(True)

    @Slot()
    def refresh_ranking(self):
        worker_url = self.worker_url_input.text().strip()
        if not worker_url:
            MessageBox("错误", "请输入WORKER_URL", self).exec_()
            return

        self.refresh_ranking_button.setEnabled(False)

        worker = RankingRefreshWorker(worker_url)
        worker.signals.result.connect(self.update_ranking)
        QThreadPool.globalInstance().start(worker)

    @Slot(object)
    def update_ranking(self, ranking_data):
        if "error" in ranking_data:
            MessageBox("错误", f"获取排名失败: {ranking_data['error']}", self).exec_()
        else:
            self.ranking_table.setRowCount(0)
            for username, count in sorted(
                ranking_data.items(), key=lambda item: int(item[1]), reverse=True
            ):
                row = self.ranking_table.rowCount()
                self.ranking_table.insertRow(row)
                self.ranking_table.setItem(row, 0, QTableWidgetItem(username))
                self.ranking_table.setItem(row, 1, QTableWidgetItem(str(count)))

        self.refresh_ranking_button.setEnabled(True)

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
            json_data = {
                "url": self.tunnel_url,
                "tg_token": self.tg_token_input.text().strip() or None,
            }
            json_data = {k: v for k, v in json_data.items() if v is not None}

            api_response = requests.post(
                f"{self.worker.worker_url}/register-node",
                json=json_data,
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

    def __del__(self):
        if self.worker:
            self.worker.stop()
            self.worker.wait()
