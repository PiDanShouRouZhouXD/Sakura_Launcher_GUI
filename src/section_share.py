import logging
import asyncio
import os
import json
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
from .sakura_share_api import SakuraShareAPI
from .ui import *
from .common import CLOUDFLARED, CONFIG_FILE, get_resource_path


class AsyncWorker(QRunnable):
    class Signals(QObject):
        finished = Signal(object)
        error = Signal(Exception)

    def __init__(self, coro):
        super().__init__()
        self.coro = coro
        self.signals = self.Signals()

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(self.coro)
            self.signals.finished.emit(result)
        except Exception as e:
            self.signals.error.emit(e)
        finally:
            loop.close()


class CFShareSection(QFrame):
    def __init__(self, title, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.setObjectName(title.replace(" ", "-"))
        self.title = title

        self._init_ui()
        self.load_settings()
        self.api = None
        self.thread_pool = QThreadPool()

        self.metrics_timer = QTimer(self)
        self.metrics_timer.timeout.connect(self.refresh_metrics)
        self.metrics_timer.setInterval(60000)  # 1分钟刷新一次

        self.reregister_timer = QTimer(self)
        self.reregister_timer.timeout.connect(self.reregister_node)
        self.reregister_timer.setInterval(300000)  # 5分钟重新注册一次

        self.is_closing = False

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
        if self.api:
            self.refresh_metrics_button.setEnabled(False)  # 禁用刷新按钮
            worker = AsyncWorker(self.api.get_metrics())
            worker.signals.finished.connect(self.on_metrics_refreshed)
            worker.signals.error.connect(self.on_error)
            self.thread_pool.start(worker)
        else:
            MessageBox("错误", "API未初始化", self).exec_()

    @Slot(object)
    def on_metrics_refreshed(self, metrics):
        self.refresh_metrics_button.setEnabled(True)  # 重新启用刷新按钮
        if "error" in metrics:
            logging.error(f"获取指标失败: {metrics['error']}")
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
                    except ValueError:
                        value_item.setText(str(value))

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

        self.api = SakuraShareAPI(int(port), worker_url)

        async def start_sharing():
            if not await self.api.check_local_health_status():
                raise Exception("本地服务未运行")

            cloudflared_path = get_resource_path(CLOUDFLARED)
            await self.api.start_cloudflare_tunnel(cloudflared_path)
            if self.api.tunnel_url is None:
                raise Exception("无法获取隧道URL")

            self.update_status(f"正在注册节点 - {self.api.tunnel_url}")

            success = await self.api.register_node(self.tg_token_input.text().strip())
            if not success:
                raise Exception("无法注册节点，请检查网络连接或稍后重试")

            return f"运行中 - {self.api.tunnel_url}"

        worker = AsyncWorker(start_sharing())
        worker.signals.finished.connect(self.on_start_finished)
        worker.signals.error.connect(self.on_error)
        self.thread_pool.start(worker)

        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.status_label.setText("状态: 正在启动...")

        QMetaObject.invokeMethod(self.metrics_timer, "start", Qt.QueuedConnection)
        QMetaObject.invokeMethod(self.reregister_timer, "start", Qt.QueuedConnection)

    @Slot()
    def stop_cf_share(self):
        if self.api and not self.is_closing:

            async def stop_sharing():
                try:
                    await self.api.take_node_offline()
                except Exception as e:
                    print(f"Error taking node offline: {str(e)}")
                finally:
                    self.api.stop()
                return "已停止"

            worker = AsyncWorker(stop_sharing())
            worker.signals.finished.connect(self.on_stop_finished)
            worker.signals.error.connect(self.on_error)
            self.thread_pool.start(worker)

            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.status_label.setText("状态: 正在下线...")

            QMetaObject.invokeMethod(self.metrics_timer, "stop", Qt.QueuedConnection)
            QMetaObject.invokeMethod(self.reregister_timer, "stop", Qt.QueuedConnection)
        else:
            print("API未初始化或正在关闭")

    @Slot(str)
    def update_status(self, status):
        self.status_label.setText(f"状态: {status}")

    @Slot(object)
    def on_start_finished(self, status):
        self.update_status(status)
        UiInfoBarSuccess(self, "已经成功启动分享。")

    @Slot(str)
    def on_stop_finished(self, status):
        self.update_status(status)
        UiInfoBarSuccess(self, "已经成功下线。")

    @Slot(Exception)
    def on_error(self, error):
        logging.error(str(error))
        self.stop_cf_share()
        MessageBox("错误", str(error), self).exec_()

    @Slot()
    def refresh_slots(self):
        worker_url = self.worker_url_input.text().strip()
        if not worker_url:
            self.slots_status_label.setText("在线slot数量: 未设置链接")
            UiInfoBarWarning(self, "请先设置链接后再刷新在线数量。")
            return

        self.refresh_slots_button.setEnabled(False)  # 禁用刷新按钮

        # 使用现有的API对象或创建一个临时的
        api = self.api if self.api else SakuraShareAPI(0, worker_url)

        worker = AsyncWorker(api.get_slots_status())
        worker.signals.finished.connect(self.update_slots_status)
        worker.signals.error.connect(self.on_error_refresh_slots)
        self.thread_pool.start(worker)

    @Slot(str)
    def update_slots_status(self, status):
        self.slots_status_label.setText(status)
        self.refresh_slots_button.setEnabled(True)  # 重新启用刷新按钮

    @Slot(Exception)
    def on_error_refresh_slots(self, error):
        self.slots_status_label.setText(f"在线slot数量: 获取失败 - {str(error)}")
        self.refresh_slots_button.setEnabled(True)  # 重新启用刷新按钮

    @Slot()
    def refresh_ranking(self):
        if self.api:
            self.refresh_ranking_button.setEnabled(False)  # 禁用刷新按钮
            worker = AsyncWorker(self.api.get_ranking())
            worker.signals.finished.connect(self.update_ranking)
            worker.signals.error.connect(self.on_error_refresh_ranking)
            self.thread_pool.start(worker)
        else:
            MessageBox("错误", "API未初始化", self).exec_()

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

        self.refresh_ranking_button.setEnabled(True)  # 重新启用刷新按钮

    @Slot(Exception)
    def on_error_refresh_ranking(self, error):
        MessageBox("错误", f"获取排名失败: {str(error)}", self).exec_()
        self.refresh_ranking_button.setEnabled(True)  # 重新启用刷新按钮

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
            settings = {}
        except json.JSONDecodeError:
            settings = {}

        self.worker_url_input.setText(
            settings.get("worker_url", "https://sakura-share.one")
        )

    @Slot()
    def reregister_node(self):
        if self.api and self.api.tunnel_url:
            self.status_label.setText("状态: 正在重新注册节点...")
            worker = AsyncWorker(self.api.register_node())
            worker.signals.finished.connect(self.on_reregistration_finished)
            worker.signals.error.connect(self.on_error)
            self.thread_pool.start(worker)
        else:
            logging.info("API未初始化或隧道URL为空，跳过重新注册")
            self.status_label.setText("状态: API未初始化或隧道URL为空，跳过重新注册")

    @Slot(object)
    def on_reregistration_finished(self, success):
        if success:
            self.status_label.setText(f"状态: 运行中 - {self.api.tunnel_url}")
            UiInfoBarSuccess(self, "节点重新注册成功。")
        else:
            self.status_label.setText("状态: 重新注册失败")
            UiInfoBarError(self, "无法重新注册节点，请检查网络连接或稍后重试。")

    def closeEvent(self, event):
        self.cleanup()
        super().closeEvent(event)

    def cleanup(self):
        self.is_closing = True
        if self.api:
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self.api.take_node_offline())
            except Exception as e:
                print(f"Error during cleanup: {str(e)}")
            finally:
                self.api.stop()
                self.api = None

        self.metrics_timer.stop()
        self.reregister_timer.stop()
