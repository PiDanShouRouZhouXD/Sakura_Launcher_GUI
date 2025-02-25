import logging
import asyncio
import os
import aiohttp
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
from .section_settings import LogHandler


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
            self.signals.finished.emit(result)  # 直接发送结果，不做类型判断
        except Exception as e:
            self.signals.error.emit(e)
        finally:
            loop.close()


class CFShareSection(QFrame):
    request_download_cloudflared = Signal()
    show_message_signal = Signal(str, str)  # (title, message)
    status_update_signal = Signal(str)  # 添加状态更新信号
    start_timers_signal = Signal()  # 添加新的信号
    stop_timers_signal = Signal()  # 添加停止定时器信号

    def __init__(self, title, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.setObjectName(title.replace(" ", "-"))
        self.title = title

        # 初始化状态管理
        self.state = ShareState(self)
        self.api = None  # 保持向后兼容
        self.is_closing = False  # 保持向后兼容
        self._should_stop = False  # 添加停止标志

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
        self.status_update_signal.connect(self._update_status_label)  # 连接状态更新信号
        self.start_timers_signal.connect(self._start_timers)
        self.stop_timers_signal.connect(self._stop_timers)

    @Slot(str, str)
    def _show_message_box(self, title, message):
        """在主线程中显示消息框的槽函数"""
        MessageBox(title, message, self).exec_()

    @Slot(str)
    def _update_status_label(self, status):
        """更新状态标签"""
        self.status_label.setText(f"状态: {status}")

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

        self.tg_token_input = UiLineEdit("可选，从@sakura_share_one_bot获取，用于统计贡献（SGLang 启动必填）")
        # 从设置中加载保存的token
        if hasattr(SETTING, "token"):
            self.tg_token_input.setText(SETTING.token)
        layout.addLayout(UiOptionRow("令牌", self.tg_token_input))
        # 添加token自动保存
        self.tg_token_input.textChanged.connect(
            lambda text: SETTING.set_value("token", text.strip())
        )

        self.port_override_input = UiLineEdit("可选，用于覆盖运行面板的端口设置，SGLang启动请填30000")
        # 从设置中加载保存的端口
        if hasattr(SETTING, "port_override"):
            self.port_override_input.setText(SETTING.port_override)
        layout.addLayout(UiOptionRow("端口", self.port_override_input))
        # 添加端口自动保存
        self.port_override_input.textChanged.connect(
            lambda text: SETTING.set_value("port_override", text.strip())
        )

        # 添加隧道模式相关的UI组件
        self.tunnel_frame = QFrame()
        tunnel_layout = QVBoxLayout(self.tunnel_frame)
        tunnel_layout.setContentsMargins(0, 0, 0, 0)

        self.custom_tunnel_url_input = UiLineEdit("可选，自定义隧道URL")
        if hasattr(SETTING, "custom_tunnel_url"):
            self.custom_tunnel_url_input.setText(SETTING.custom_tunnel_url)
        tunnel_layout.addLayout(UiOptionRow("隧道URL", self.custom_tunnel_url_input))
        self.custom_tunnel_url_input.textChanged.connect(
            lambda text: SETTING.set_value("custom_tunnel_url", text.strip())
        )

        layout.addWidget(self.tunnel_frame)
        # 根据当前模式设置隧道组件的可见性
        self.tunnel_frame.setVisible(SETTING.share_mode == "tunnel")

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
            <h2>Sakura Share - 模型共享工具</h2>
            
            <p>这是一个让你快速将本地部署的Sakura模型分享给其他用户的工具（成为帕鲁）。</p>
            
            <h3>支持的模型</h3>
            <ul>
                <li>sakura-14b-qwen2.5-v1.0-iq4xs.gguf</li>
                <li>sakura-14b-qwen2.5-v1.0-q6k.gguf</li>
                <li>SakuraLLM.Sakura-14B-Qwen2.5-v1.0-W8A8-Int8
                    <small>（需要使用SGLang启动，并需要申请白名单权限）</small>
                </li>
            </ul>
            
            <h3>重要说明</h3>
            <ul>
                <li>建议使用默认链接 - 由共享脚本开发者维护，稳定可靠</li>
                <li>双向使用 - 你可以选择成为帕鲁分享模型，也可以作为用户访问其他帕鲁的模型
                    <small>（但不保证服务的可用性与稳定性）</small>
                </li>
                <li><b>匿名分享 - 分享时不填写「令牌」，就可以匿名分享算力</b></li>
                <li>如果无法正常链接到服务器，请尝试将「链接」更改为 <a href='https://cf.sakura-share.one'>https://cf.sakura-share.one</a></li>
            </ul>
            
            <h3>贡献统计说明</h3>
            <ul>
                <li>参与方式：
                    <ul>
                        <li>通过 <a href='https://t.me/sakura_share_one_bot'>@sakura_share_one_bot</a> 获取「令牌（Token）」</li>
                        <li>贡献统计为可选功能（W8A8模型必需）</li>
                        <li>在「在线排名」标签中可查看贡献排名（显示前10名）</li>
                        <li>查看全网算力情况：<a href='https://sakura-share.one/'>算力公示板</a></li>
                    </ul>
                </li>
                <li>详细文档请参考：<a href='https://www.youtube.com/watch?v=dQw4w9WgXcQ'>Sakura Share</a></li>
            </ul>
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

        layout.addItem(QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding))

        # 监听共享模式变化
        SETTING.value_changed.connect(self._on_setting_changed)

    def _on_setting_changed(self, key, value):
        """处理设置变化"""
        if key == "share_mode":
            # 更新隧道相关UI组件的可见性
            self.tunnel_frame.setVisible(value == "tunnel")
            # 如果正在运行，提示需要重启
            if self.api and self.api.is_running:
                UiInfoBarWarning(self, "修改共享模式后需要重新启动分享才能生效。")

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
        self.ranking_table.setColumnCount(3)
        self.ranking_table.setHorizontalHeaderLabels(["用户名", "生成Token数", "在线时长(小时)"])
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

        # 优先使用端口设置
        port_override = self.port_override_input.text().strip()
        if port_override:
            try:
                port = int(port_override)
            except ValueError:
                MessageBox("错误", "端口设置必须是有效的数字", self).exec_()
                return
        else:
            port = self.main_window.run_server_section.port_input.text().strip()
            if not port:
                MessageBox("错误", "请在运行面板中设置端口号或使用端口覆盖", self).exec_()
                return
            try:
                port = int(port)
            except ValueError:
                MessageBox("错误", "端口号必须是有效的数字", self).exec_()
                return

        self.refresh_metrics_button.setEnabled(False)
        api = self.api if self.api else SakuraShareAPI(port, worker_url)

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
    def _start_timers(self):
        """在主线程中启动定时器"""
        self.metrics_timer.start()
        self.reregister_timer.start()

    @Slot()
    def _stop_timers(self):
        """在主线程中停止定时器"""
        self.metrics_timer.stop()
        self.reregister_timer.stop()

    @Slot()
    def start_cf_share(self):
        """启动共享功能"""
        # 检查必要参数
        worker_url = self.worker_url_input.text().strip()
        if not worker_url:
            MessageBox("错误", "请输入WORKER_URL", self).exec_()
            return

        # 优先使用端口设置
        port_override = self.port_override_input.text().strip()
        if port_override:
            try:
                port = int(port_override)
            except ValueError:
                MessageBox("错误", "端口设置必须是有效的数字", self).exec_()
                return
        else:
            port = self.main_window.run_server_section.port_input.text().strip()
            if not port:
                MessageBox("错误", "请在运行面板中设置端口号或使用端口覆盖", self).exec_()
                return
            try:
                port = int(port)
            except ValueError:
                MessageBox("错误", "端口号必须是有效的数字", self).exec_()
                return

        # 保存参数
        self.port = port
        self.worker_url = worker_url
        self.share_mode = getattr(SETTING, "share_mode", "ws")
        self.tg_token = self.tg_token_input.text().strip()
        self.custom_tunnel_url = self.custom_tunnel_url_input.text().strip()

        # 重置停止标志
        self._should_stop = False
        
        # 创建并启动worker
        worker = AsyncWorker(self.start_sharing())
        worker.signals.finished.connect(self._handle_connection_status)
        
        # 保存worker引用
        self._current_worker = worker
        self.thread_pool.start(worker)
        
        # 更新UI状态
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.status_label.setText("状态: 正在启动...")

    async def start_sharing(self):
        try:
            # 初始化API
            self.api = SakuraShareAPI(self.port, self.worker_url, self.share_mode)
            self.state.update_api(self.api)
            
            # 检查本地服务状态
            if not await self.api.check_local_health_status():
                return "错误：本地服务未运行"

            # 检查是否为SGLang服务
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"http://localhost:{self.port}/get_model_info", timeout=5) as response:
                        if response.status == 200:
                            data = await response.json()
                            if "model_path" in data and "W8A8" in data["model_path"]:
                                if not self.tg_token:
                                    return "错误：检测到SGLang W8A8模型，必须填写令牌"
            except Exception:
                pass

            # 获取启动参数
            start_params = {
                "tg_token": self.tg_token
            }

            # 如果是隧道模式，添加隧道相关参数
            if self.share_mode == "tunnel":
                if self.custom_tunnel_url:
                    start_params["custom_tunnel_url"] = self.custom_tunnel_url
                elif os.path.exists(CLOUDFLARED):
                    start_params["cloudflared_path"] = CLOUDFLARED
                else:
                    return "错误：隧道模式下必须提供自定义隧道URL或安装cloudflared"

            # 启动服务
            if not await self.api.start(**start_params):
                return "错误：启动失败，请检查配置和网络连接"

            # 发送初始状态
            mode_str = "WebSocket已连接" if self.share_mode == "ws" else f"隧道已连接 - {self.api.tunnel_url}"
            self.status_update_signal.emit(f"运行中 - {mode_str}")
            
            # 使用信号在主线程中启动定时器
            self.start_timers_signal.emit()
            
            # 保持连接活跃
            while not self._should_stop:
                await asyncio.sleep(60)
                # if not self.api or not self.api.is_running:
                #     return "错误：连接已断开"
                # NOTE: 暂时关闭本地服务检查，新版Share会大幅增加llamacpp的负载，导致永远无法通过检查
                # # 定期检查连接状态
                # try:
                #     if not await self.api.check_local_health_status():
                #         return "错误：本地服务已断开"
                # except Exception as e:
                #     return f"错误：连接检查失败 - {str(e)}"

            return "正常停止"
            
        except Exception as e:
            print(f"[Share] 启动错误: {e}")
            return f"错误：{str(e)}"

    def _handle_connection_status(self, status):
        """处理连接状态更新"""
        if isinstance(status, str):
            if status.startswith("错误"):
                self.status_label.setText(f"状态: {status}")
                self.start_button.setEnabled(True)
                self.stop_button.setEnabled(False)
                UiInfoBarError(self, status)
            else:
                self.status_label.setText(f"状态: {status}")
                if status == "正常停止":
                    self.start_button.setEnabled(True)
                    self.stop_button.setEnabled(False)
                    self.metrics_timer.stop()
                    self.reregister_timer.stop()

    @Slot()
    def stop_cf_share(self):
        """停止共享服务"""
        self._should_stop = True
        
        if self.api:
            async def stop_api():
                api = self.api
                self.api = None  # 立即清除引用
                try:
                    await api.stop()
                    return None
                except Exception as e:
                    print(f"[Share] 停止错误: {e}")
                    return str(e)
            
            # 创建新的worker来处理停止操作
            worker = AsyncWorker(stop_api())
            worker.signals.finished.connect(self._handle_stop_finished)
            worker.signals.error.connect(self._handle_stop_error)
            self.thread_pool.start(worker)
        
        # 停止定时器
        self.stop_timers_signal.emit()
        
        # 更新UI状态
        self.status_label.setText("状态: 正在停止...")
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(False)

    @Slot()
    def _handle_stop_finished(self, error_msg=None):
        """处理停止完成的回调"""
        if error_msg:
            self.show_message_signal.emit("错误", f"停止时发生错误: {error_msg}")
        
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.status_label.setText("状态: 已停止")

    @Slot(Exception)
    def _handle_stop_error(self, error):
        """处理停止时的错误"""
        print(f"[Share] 停止过程中发生错误: {error}")
        self._handle_stop_finished()  # 仍然执行清理操作

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
        if isinstance(ranking_data, list) and len(ranking_data) > 0 and "error" not in ranking_data[0]:
            self.ranking_table.setRowCount(0)
            for item in ranking_data:
                row = self.ranking_table.rowCount()
                self.ranking_table.insertRow(row)
                self.ranking_table.setItem(row, 0, QTableWidgetItem(item["name"]))
                self.ranking_table.setItem(row, 1, QTableWidgetItem(f"{item['token_count']:,}"))
                # 将在线时间从秒转换为小时，并保留两位小数
                online_hours = item["online_time"] / 3600
                self.ranking_table.setItem(row, 2, QTableWidgetItem(f"{online_hours:.2f}"))
        else:
            error_msg = ranking_data[0]["error"] if isinstance(ranking_data, list) else "未知错误"
            MessageBox("错误", f"获取排名失败: {error_msg}", self).exec_()

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

    @Slot(Exception)
    def on_error(self, error):
        """处理通用错误"""
        self.status_label.setText(f"状态: 错误 - {str(error)}")
        MessageBox("错误", f"操作失败: {str(error)}", self).exec_()
