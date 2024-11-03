import logging
import asyncio
import os
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

from .common import CLOUDFLARED, CURRENT_DIR, get_resource_path
from .sakura_share_api import SakuraShareAPI
from .setting import SETTING
from .ui import *


class ShareState(QObject):
    """状态管理类"""

    status_changed = Signal(str)

    def __init__(self, parent):
        super().__init__(parent)
        self.api = None
        self.is_closing = False

        # 初始化定时器
        self.metrics_timer = QTimer(parent)
        self.metrics_timer.setInterval(60000)  # 1分钟刷新一次

        self.reregister_timer = QTimer(parent)
        self.reregister_timer.setInterval(300000)  # 5分钟重新注册一次

    def update_api(self, api):
        """更新API实例"""
        self.api = api

    def cleanup(self):
        """清理状态"""
        self.is_closing = True
        self.api = None


class AsyncWorker(QRunnable):
    """异步任务处理类"""

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
    request_download_cloudflared = Signal()
    show_message_signal = Signal(str, str)  # (title, message)

    def __init__(self, title, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.setObjectName(title.replace(" ", "-"))
        self.title = title

        # 初始化状态管理
        self.state = ShareState(self)
        self.api = None  # 保持向后兼容
        self.is_closing = False  # 保持向后兼容

        # 初始化线程池
        self.thread_pool = QThreadPool()

        # 初始化UI
        self._init_ui()

        # 设置定时器连接
        self.metrics_timer = self.state.metrics_timer  # 保持向后兼容
        self.metrics_timer.timeout.connect(self.refresh_metrics)

        self.reregister_timer = self.state.reregister_timer  # 保持向后兼容
        self.reregister_timer.timeout.connect(self.reregister_node)

        # 连接信号
        self.show_message_signal.connect(self._show_message_box)

    @Slot(str, str)
    def _show_message_box(self, title, message):
        """在主线程中显示消息框的槽函数"""
        MessageBox(title, message, self).exec_()

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

        self.refresh_slots_button = PushButton(FIF.SYNC, "刷新")
        self.refresh_slots_button.clicked.connect(self.refresh_slots)

        self.stop_button = PushButton(FIF.CLOSE, "下线")
        self.stop_button.clicked.connect(self.stop_cf_share)
        self.stop_button.setEnabled(False)

        self.start_button = PrimaryPushButton(FIF.PLAY, "上线")
        self.start_button.clicked.connect(self.start_cf_share)

        layout.addWidget(
            UiButtonGroup(
                self.refresh_slots_button,
                self.stop_button,
                self.start_button,
            )
        )

        self.worker_url_input = UiLineEdit("输入WORKER_URL", SETTING.worker_url)
        layout.addLayout(UiOptionRow("链接", self.worker_url_input))
        self.worker_url_input.textChanged.connect(
            lambda text: SETTING.set_value("worker_url", text.strip())
        )

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
        """初始化指标统计页面"""
        layout = QVBoxLayout(self.metrics_page)
        layout.setContentsMargins(0, 0, 0, 0)

        # 创建表格
        self.metrics_table = TableWidget(self)
        self.metrics_table.setColumnCount(2)
        self.metrics_table.setHorizontalHeaderLabels(["指标", "值"])
        self.metrics_table.verticalHeader().setVisible(False)
        self.metrics_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        # 初始化指标数据
        self._init_metrics_data()

        layout.addWidget(self.metrics_table)

        # 添加刷新按钮
        self.refresh_metrics_button = PushButton(FIF.SYNC, "刷新数据")
        self.refresh_metrics_button.clicked.connect(self.refresh_metrics)
        layout.addWidget(self.refresh_metrics_button)

    def _init_metrics_data(self):
        """初始化指标数据和提示信息"""
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

        self.metrics_table.setRowCount(len(metrics_data))
        for row, (metric, value) in enumerate(metrics_data):
            self.metrics_table.setItem(row, 0, QTableWidgetItem(metric))
            self.metrics_table.setItem(row, 1, QTableWidgetItem(value))
            if metric in tooltips:
                self.metrics_table.item(row, 0).setToolTip(tooltips[metric])

    def init_ranking_page(self):
        """初始化排名页面"""
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
        """刷新指标数据"""
        worker_url = self.worker_url_input.text().strip()
        if not worker_url:
            MessageBox("错误", "请先设置链接", self).exec_()
            return

        self.refresh_metrics_button.setEnabled(False)
        api = self.api if self.api else SakuraShareAPI(0, worker_url)

        worker = AsyncWorker(api.get_metrics())
        worker.signals.finished.connect(self.on_metrics_refreshed)
        worker.signals.error.connect(self.on_error)
        self.thread_pool.start(worker)

    @Slot(object)
    def on_metrics_refreshed(self, metrics):
        """处理指标刷新结果"""
        self.refresh_metrics_button.setEnabled(True)
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
                    self._format_metric_value(value_item, key, value)

    def _format_metric_value(self, item, key, value):
        """格式化指标值"""
        try:
            if key in ["prompt_tokens_total", "tokens_predicted_total"]:
                item.setText(f"{float(value):.0f} tokens")
            elif key in ["prompt_seconds_total", "tokens_predicted_seconds_total"]:
                item.setText(f"{float(value):.2f} 秒")
            elif key == "n_decode_total":
                item.setText(f"{float(value):.0f} 次")
            elif key == "n_busy_slots_per_decode":
                item.setText(f"{float(value):.2f}")
            elif key in ["prompt_tokens_seconds", "predicted_tokens_seconds"]:
                item.setText(f"{float(value):.2f} tokens/s")
            elif key == "kv_cache_usage_ratio":
                item.setText(f"{float(value)*100:.2f}%")
            elif key == "kv_cache_tokens":
                item.setText(f"{float(value):.0f} tokens")
            elif key in ["requests_processing", "requests_deferred"]:
                item.setText(f"{float(value):.0f}")
            else:
                item.setText(f"{float(value):.2f}")
        except ValueError:
            item.setText(str(value))

    @Slot()
    def start_cf_share(self):
        """启动共享功能"""
        # 检查cloudflared是否存在
        cloudflared_path = os.path.join(CURRENT_DIR, CLOUDFLARED)
        if not os.path.exists(cloudflared_path):
            UiInfoBarWarning(self, "未检测到Cloudflared，请等待下载完成后再上线。")
            self.request_download_cloudflared.emit()
            return

        # 检查必要参数
        worker_url = self.worker_url_input.text().strip()
        if not worker_url:
            MessageBox("错误", "请输入WORKER_URL", self).exec_()
            return

        port = self.main_window.run_server_section.port_input.text().strip()
        if not port:
            MessageBox("错误", "请在运行面板中设置端口号", self).exec_()
            return

        # 初始化API
        self.api = SakuraShareAPI(int(port), worker_url)
        self.state.update_api(self.api)

        async def start_sharing():
            # 检查本地服务状态
            if not await self.api.check_local_health_status():
                self.show_message_signal.emit("错误", "本地服务未运行")
                return None

            # 启动cloudflare隧道
            await self.api.start_cloudflare_tunnel(cloudflared_path)
            if self.api.tunnel_url is None:
                self.show_message_signal.emit("错误", "无法获取隧道URL")
                return None

            self.update_status(f"正在注册节点 - {self.api.tunnel_url}")
            await asyncio.sleep(5)  # 延迟5秒钟

            # 注册节点
            success = await self.api.register_node(self.tg_token_input.text().strip())
            if not success:
                self.show_message_signal.emit(
                    "错误", "无法注册节点，请检查网络连接或稍后重试"
                )
                return None

            return f"运行中 - {self.api.tunnel_url}"

        # 启动异步任务
        worker = AsyncWorker(start_sharing())
        worker.signals.finished.connect(self.on_start_finished)
        worker.signals.error.connect(self.on_error)
        self.thread_pool.start(worker)

        # 更新UI状态
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.status_label.setText("状态: 正在启动...")

        # 启动定时器
        QMetaObject.invokeMethod(self.metrics_timer, "start", Qt.QueuedConnection)
        QMetaObject.invokeMethod(self.reregister_timer, "start", Qt.QueuedConnection)

    @Slot(object)
    def on_start_finished(self, status):
        """处理启动操作完成"""
        if status is None:
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.status_label.setText("状态: 启动失败")
            return

        self.update_status(status)
        UiInfoBarSuccess(self, "已经成功启动分享。")

    @Slot()
    def stop_cf_share(self):
        """停止共享功能"""
        if self.api and not self.is_closing:

            async def stop_sharing():
                try:
                    # 标记正在下线
                    self.is_closing = True
                    self.state.is_closing = True

                    success = await self.api.take_node_offline()
                    if not success:
                        self.show_message_signal.emit("警告", "节点下线可能未完全成功")
                except Exception as e:
                    print(f"Error taking node offline: {str(e)}")  # 使用print打印错误信息，因为这时候主线程已经退出
                finally:
                    self.api.stop()
                return "已停止"

            # 启动异步任务
            worker = AsyncWorker(stop_sharing())
            worker.signals.finished.connect(self.on_stop_finished)
            worker.signals.error.connect(self.on_error_stop)  # 使用专门的错误处理器
            self.thread_pool.start(worker)

            # 更新UI状态
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.status_label.setText("状态: 正在下线...")

            # 停止定时器
            QMetaObject.invokeMethod(self.metrics_timer, "stop", Qt.QueuedConnection)
            QMetaObject.invokeMethod(self.reregister_timer, "stop", Qt.QueuedConnection)
        else:
            print("API未初始化或正在关闭")  # 使用print打印信息，因为这时候主线程已经退出

    @Slot(Exception)
    def on_error_stop(self, error):
        """处理停止操作时的错误"""
        logging.error(f"停止操作发生错误: {str(error)}")
        self.show_message_signal.emit("错误", f"停止操作失败: {str(error)}")

        # 确保清理完成
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.status_label.setText("状态: 停止失败")

        if self.api:
            self.api.stop()
            self.api = None

    @Slot(object)
    def on_stop_finished(self, status):
        """处理停止操作完成"""
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.status_label.setText(f"状态: {status}")
        self.api = None  # 清除API实例
        UiInfoBarSuccess(self, "已成功停止分享。")

    @Slot(str)
    def update_status(self, status):
        """更新状态显示"""
        self.status_label.setText(f"状态: {status}")

    @Slot(Exception)
    def on_error(self, error):
        """处理一般错误"""
        logging.error(str(error))

        async def check_and_retry():
            if not self.api:
                self.show_message_signal.emit("错误", str(error))
                return None

            try:
                if await self.api.check_local_health_status():
                    # 本地服务正常,尝试重新注册
                    self.status_label.setText(
                        "状态: 检测到本地服务正常,尝试重新连接..."
                    )
                    success = await self.api.register_node(
                        self.tg_token_input.text().strip()
                    )
                    if success:
                        status = f"状态: 运行中 - {self.api.tunnel_url}"
                        self.status_label.setText(status)
                        UiInfoBarSuccess(self, "重新连接成功。")
                        return status
            except Exception as e:
                logging.error(f"重试过程发生错误: {str(e)}")

            # 如果重试失败或发生异常，执行下线流程
            self.stop_cf_share()
            self.show_message_signal.emit("错误", str(error))
            return None

        worker = AsyncWorker(check_and_retry())
        worker.signals.finished.connect(self.on_retry_finished)
        self.thread_pool.start(worker)

    @Slot(object)
    def on_retry_finished(self, status):
        """处理重试操作完成"""
        if status is None:
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.status_label.setText("状态: 重试失败")

    @Slot()
    def refresh_slots(self):
        """刷新slots状态"""
        worker_url = self.worker_url_input.text().strip()
        if not worker_url:
            self.slots_status_label.setText("在线slot数量: 未设置链接")
            UiInfoBarWarning(self, "请先设置链接后再刷新在线数量。")
            return

        self.refresh_slots_button.setEnabled(False)
        api = self.api if self.api else SakuraShareAPI(0, worker_url)

        worker = AsyncWorker(api.get_slots_status())
        worker.signals.finished.connect(self.update_slots_status)
        worker.signals.error.connect(self.on_error_refresh_slots)
        self.thread_pool.start(worker)

    @Slot(str)
    def update_slots_status(self, status):
        """更新slots状态显示"""
        self.slots_status_label.setText(status)
        self.refresh_slots_button.setEnabled(True)

    @Slot(Exception)
    def on_error_refresh_slots(self, error):
        """处理刷新slots时的错误"""
        self.slots_status_label.setText(f"在线slot数量: 获取失败 - {str(error)}")
        self.refresh_slots_button.setEnabled(True)

    @Slot()
    def refresh_ranking(self):
        """刷新排名数据"""
        worker_url = self.worker_url_input.text().strip()
        if not worker_url:
            MessageBox("错误", "请先设置链接", self).exec_()
            return

        self.refresh_ranking_button.setEnabled(False)
        api = self.api if self.api else SakuraShareAPI(0, worker_url)

        worker = AsyncWorker(api.get_ranking())
        worker.signals.finished.connect(self.update_ranking)
        worker.signals.error.connect(self.on_error_refresh_ranking)
        self.thread_pool.start(worker)

    @Slot(object)
    def update_ranking(self, ranking_data):
        """更新排名数据"""
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

    @Slot(Exception)
    def on_error_refresh_ranking(self, error):
        """处理刷新排名时的错误"""
        MessageBox("错误", f"获取排名失败: {str(error)}", self).exec_()
        self.refresh_ranking_button.setEnabled(True)

    def get_metric_key(self, metric_text):
        """获取指标键值映射"""
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

    @Slot()
    def reregister_node(self):
        """定时重新注册节点"""
        if self.api and self.api.tunnel_url:
            self.status_label.setText("状态: 正在重新注册节点...")

            async def do_reregister():
                success = await self.api.register_node()
                if success:
                    return f"运行中 - {self.api.tunnel_url}"
                self.show_message_signal.emit(
                    "错误", "无法重新注册节点，请检查网络连接或稍后重试"
                )
                return None

            worker = AsyncWorker(do_reregister())
            worker.signals.finished.connect(self.on_reregistration_finished)
            worker.signals.error.connect(self.on_error)
            self.thread_pool.start(worker)
        else:
            logging.info("API未初始化或隧道URL为空，跳过重新注册")
            self.status_label.setText("状态: API未初始化或隧道URL为空，跳过重新注册")

    @Slot(object)
    def on_reregistration_finished(self, status):
        """处理重新注册完成"""
        if status:
            self.status_label.setText(status)
            UiInfoBarSuccess(self, "节点重新注册成功。")
        else:
            self.status_label.setText("状态: 重新注册失败")
            UiInfoBarError(self, "无法重新注册节点，请检查网络连接或稍后重试。")

    def closeEvent(self, event):
        """处理关闭事件"""
        QTimer.singleShot(0, self.cleanup)
        QTimer.singleShot(100, lambda: super().closeEvent(event))

    def cleanup(self):
        """清理资源"""
        self.is_closing = True
        self.state.is_closing = True

        # 停止定时器
        if hasattr(self, "metrics_timer"):
            self.metrics_timer.stop()
            self.metrics_timer.deleteLater()

        if hasattr(self, "reregister_timer"):
            self.reregister_timer.stop()
            self.reregister_timer.deleteLater()

        # API清理
        if self.api:
            try:

                def cleanup_api():
                    try:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        loop.run_until_complete(self.api.take_node_offline())
                    except Exception as e:
                        logging.error(f"Error during API cleanup: {str(e)}")
                    finally:
                        if self.api:
                            self.api.stop()
                            self.api = None

                QTimer.singleShot(0, cleanup_api)
            except Exception as e:
                logging.error(f"Error initiating cleanup: {str(e)}")
