import logging
import os
import json
import subprocess
import requests
import re
import time
from PySide6.QtCore import (
    Qt,
    Signal,
    Slot,
    QThreadPool,
    QRunnable,
    QTimer,
    QObject,
    QMetaObject,
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


class NodeRegistrationWorker(QRunnable):
    class Signals(QObject):
        finished = Signal(bool, str)
        status_update = Signal(str)

    def __init__(self, cf_share_section, tunnel_url):
        super().__init__()
        self.cf_share_section = cf_share_section
        self.tunnel_url = tunnel_url
        self.signals = self.Signals()

    def run(self):
        max_retries = 3
        for attempt in range(max_retries):
            self.signals.status_update.emit(
                f"正在注册节点 (尝试 {attempt + 1}/{max_retries})..."
            )
            register_status = self.cf_share_section.register_node()
            if register_status:
                self.signals.finished.emit(True, f"运行中 - {self.tunnel_url}")
                return
            else:
                if attempt < max_retries - 1:
                    self.signals.status_update.emit(
                        f"注册失败，正在重试 ({attempt + 1}/{max_retries})..."
                    )
                    time.sleep(2)  # 在重试之间等待2秒
                else:
                    self.signals.finished.emit(False, "启动失败")


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


class MetricsRefreshWorker(QRunnable):
    class Signals(QObject):
        result = Signal(dict)

    def __init__(self, port):
        super().__init__()
        self.port = port
        self.signals = self.Signals()

    def run(self):
        try:
            response = requests.get(f"http://localhost:{self.port}/metrics", timeout=5)
            if response.status_code == 200:
                metrics = self.parse_metrics(response.text)
                self.signals.result.emit(metrics)
            else:
                self.signals.result.emit(
                    {"error": f"HTTP status {response.status_code}"}
                )
        except requests.RequestException as e:
            self.signals.result.emit({"error": f"Request error: {str(e)}"})
        except Exception as e:
            self.signals.result.emit({"error": f"Unexpected error: {str(e)}"})

    def parse_metrics(self, metrics_text):
        metrics = {}
        for line in metrics_text.split("\n"):
            if line.startswith("#") or not line.strip():
                continue
            try:
                key, value = line.split(" ")
                metrics[key.split(":")[-1]] = float(value)
            except ValueError:
                continue
        return metrics


class CFShareWorker(QRunnable):
    class Signals(QObject):
        status_update = Signal(str)
        tunnel_url_found = Signal(str)
        error_occurred = Signal(str)
        health_check_failed = Signal()

    def __init__(self, port, worker_url):
        super().__init__()
        self.port = port
        self.worker_url = worker_url
        self.cloudflared_process = None
        self.tunnel_url = None
        self.is_running = False
        self.signals = self.Signals()

    def run(self):
        self.is_running = True
        self.signals.status_update.emit("正在启动 Cloudflare 隧道...")
        cloudflared_path = get_resource_path(CLOUDFLARED)

        try:
            self.cloudflared_process = subprocess.Popen(
                [
                    cloudflared_path,
                    "tunnel",
                    "--url",
                    f"http://localhost:{self.port}",
                    "--metrics",
                    "localhost:8081",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except Exception as e:
            self.signals.error_occurred.emit(f"启动 Cloudflare 隧道失败: {str(e)}")
            return

        self.signals.status_update.emit("正在等待隧道URL...")
        self.check_tunnel_url()

        # 启动健康检查
        while self.is_running:
            if not self.check_local_health_status():
                self.signals.health_check_failed.emit()
                break
            time.sleep(5)  # 每5秒检查一次

    def check_tunnel_url(self):
        max_attempts = 30  # 最多尝试30次，每次等待1秒
        for attempt in range(max_attempts):
            try:
                metrics_response = requests.get(
                    "http://localhost:8081/metrics", timeout=5
                )
                tunnel_url_match = re.search(
                    r"(https://.*?\.trycloudflare\.com)", metrics_response.text
                )
                if tunnel_url_match:
                    self.tunnel_url = tunnel_url_match.group(1)
                    self.signals.tunnel_url_found.emit(self.tunnel_url)
                    return
            except Exception as e:
                pass
            time.sleep(1)
            self.signals.status_update.emit(
                f"等待隧道URL... ({attempt + 1}/{max_attempts})"
            )

        self.signals.error_occurred.emit("获取隧道URL失败")

    def check_local_health_status(self):
        health_url = f"http://localhost:{self.port}/health"
        try:
            response = requests.get(health_url, timeout=5)
            data = response.json()
            return data["status"] in ["ok", "no slot available"]
        except Exception:
            return False

    def stop(self):
        self.is_running = False
        if self.cloudflared_process:
            self.cloudflared_process.terminate()
            try:
                self.cloudflared_process.wait(timeout=5)
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
        self.thread_pool = QThreadPool()

        self.metrics_timer = QTimer(self)
        self.metrics_timer.timeout.connect(self.refresh_metrics)
        self.metrics_timer.setInterval(5000)  # 5秒更新一次

        # 添加新的重新注册定时器
        self.reregister_timer = QTimer(self)
        self.reregister_timer.timeout.connect(self.reregister_node)
        self.reregister_timer.setInterval(60000)  # 60秒 (1分钟) 重新注册一次

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

        # 添加刷新按钮
        self.refresh_metrics_button = PushButton(FIF.SYNC, "刷新数据")
        self.refresh_metrics_button.clicked.connect(self.refresh_metrics)
        layout.addWidget(self.refresh_metrics_button)

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
    def refresh_metrics(self):
        port = self.main_window.run_server_section.port_input.text().strip()
        worker = MetricsRefreshWorker(port)
        worker.signals.result.connect(self.update_metrics_display)
        QThreadPool.globalInstance().start(worker)

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
            MessageBox("错误", "本地服务未运行", self).exec_()
            return

        self.worker = CFShareWorker(port, worker_url)
        self.worker.signals.status_update.connect(self.update_status)
        self.worker.signals.tunnel_url_found.connect(self.on_tunnel_url_found)
        self.worker.signals.error_occurred.connect(self.on_error)
        self.worker.signals.health_check_failed.connect(self.stop_cf_share)

        self.thread_pool.start(self.worker)

        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.status_label.setText("状态: 正在启动...")

        # 在主线程中启动定时器
        QMetaObject.invokeMethod(self.metrics_timer, "start", Qt.QueuedConnection)
        QMetaObject.invokeMethod(self.reregister_timer, "start", Qt.QueuedConnection)

    @Slot()
    def stop_cf_share(self):
        # 在主线程中停止定时器
        QMetaObject.invokeMethod(self.metrics_timer, "stop", Qt.QueuedConnection)
        QMetaObject.invokeMethod(self.reregister_timer, "stop", Qt.QueuedConnection)
        un_register_status = self.take_node_offline()
        if self.worker:
            self.worker.stop()
            self.worker = None
        if un_register_status:
            self.status_label.setText("状态: 已停止")
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)

    @Slot(str)
    def update_status(self, status):
        self.status_label.setText(f"状态: {status}")

    @Slot(str)
    def on_tunnel_url_found(self, tunnel_url):
        self.tunnel_url = tunnel_url
        logging.info(f"Tunnel URL: {self.tunnel_url}")

        worker = NodeRegistrationWorker(self, tunnel_url)
        worker.signals.status_update.connect(self.update_status)
        worker.signals.finished.connect(self.on_registration_finished)
        QThreadPool.globalInstance().start(worker)

    @Slot(bool, str)
    def on_registration_finished(self, success, status):
        if success:
            self.status_label.setText(f"状态: {status}")
            self.main_window.createSuccessInfoBar("成功", "已经成功启动分享。")
        else:
            self.status_label.setText(f"状态: {status}")
            self.main_window.createErrorInfoBar(
                "错误", "无法注册节点，请检查网络连接或稍后重试。"
            )
            self.stop_cf_share()

    @Slot(str)
    def on_error(self, error_message):
        logging.info(error_message)
        self.stop_cf_share()
        MessageBox("错误", error_message, self).exec_()

    @Slot(dict)
    def update_metrics_display(self, metrics):
        if "error" in metrics:
            MessageBox("错误", f"获取指标失败: {metrics['error']}", self).exec_()
            return

        for row in range(self.metrics_table.rowCount()):
            metric_item = self.metrics_table.item(row, 0)
            value_item = self.metrics_table.item(row, 1)
            if metric_item and value_item:
                metric_text = metric_item.text()
                key = self.get_metric_key(metric_text)
                if key in metrics:
                    value = metrics[key]
                    try:
                        if key in ["prompt_tokens_total", "tokens_predicted_total"]:
                            value_item.setText(f"{float(value):.0f} tokens")
                        elif key in [
                            "prompt_seconds_total",
                            "tokens_predicted_seconds_total",
                        ]:
                            value_item.setText(f"{float(value):.2f} 秒")
                        elif key == "n_decode_total":
                            value_item.setText(f"{float(value):.0f} 次")
                        elif key == "n_busy_slots_per_decode":
                            value_item.setText(f"{float(value):.2f}")
                        elif key in [
                            "prompt_tokens_seconds",
                            "predicted_tokens_seconds",
                        ]:
                            value_item.setText(f"{float(value):.2f} tokens/s")
                        elif key == "kv_cache_usage_ratio":
                            value_item.setText(f"{float(value)*100:.2f}%")
                        elif key == "kv_cache_tokens":
                            value_item.setText(f"{float(value):.0f} tokens")
                        elif key in ["requests_processing", "requests_deferred"]:
                            value_item.setText(f"{float(value):.0f}")
                        else:
                            value_item.setText(f"{float(value):.2f}")
                    except ValueError as e:
                        value_item.setText(str(value))
                else:
                    pass

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
                logging.info(f"本地服务状态: 不健康 - {data['status']}")
                return False
        except Exception as e:
            logging.info(f"检查本地服务状态失败: {str(e)}")
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
            logging.info(f"节点注册响应: {api_response.text}")
            if api_response.status_code == 200:
                return True
            else:
                return False
        except Exception as e:
            logging.info(f"节点注册失败: {str(e)}")
            return False

    def take_node_offline(self):
        try:
            offline_response = requests.post(
                f"{self.worker.worker_url}/delete-node",
                json={"url": self.tunnel_url},
                headers={"Content-Type": "application/json"},
            )
            logging.info(f"节点下线响应: {offline_response.text}")
            return True
        except Exception as e:
            if "object has no attribute 'worker_url'" in str(e):
                logging.info("节点已下线")
                return True
            else:
                logging.info(f"节点下线失败：{str(e)}")
                return False

    def __del__(self):
        if self.worker:
            self.worker.stop()
            self.worker.wait()

    @Slot()
    def reregister_node(self):
        if self.check_local_health_status():
            worker = NodeRegistrationWorker(self, self.tunnel_url)
            worker.signals.status_update.connect(self.update_status)
            worker.signals.finished.connect(self.on_reregistration_finished)
            QThreadPool.globalInstance().start(worker)
        else:
            logging.info("本地健康检查未通过,跳过重新注册")

    @Slot(bool, str)
    def on_reregistration_finished(self, success, status):
        if success:
            logging.info("节点重新注册成功")
        else:
            logging.warning(f"节点重新注册失败: {status}")