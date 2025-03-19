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

from .common import CURRENT_DIR, get_resource_path
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

        self.status_label = QLabel("状态: 未运行")
        layout.addWidget(self.status_label)

        self.slots_status_label = QLabel("在线slot数量: 未知")
        layout.addWidget(self.slots_status_label)

        # 添加节点列表显示
        self.nodes_label = QLabel("节点列表: 未获取")
        self.nodes_label.setWordWrap(True)
        self.nodes_label.setTextFormat(Qt.RichText)
        self.nodes_label.setStyleSheet("""
            QLabel {
                background-color: rgba(0, 0, 0, 0.03);
                border-radius: 5px;
                padding: 8px;
                margin-top: 5px;
                margin-bottom: 5px;
            }
        """)
        layout.addWidget(self.nodes_label)

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

    def init_metrics_page(self):
        """初始化指标统计页面"""
        layout = QVBoxLayout(self.metrics_page)
        layout.setContentsMargins(0, 0, 0, 0)

        # 创建子页面切换控件
        self.metrics_pivot = SegmentedWidget()
        self.metrics_stacked_widget = QStackedWidget()

        # 创建LlamaCpp和SGLang两个子页面
        self.llamacpp_page = QWidget()
        self.sglang_page = QWidget()

        # 初始化LlamaCpp页面
        self.init_llamacpp_page()
        
        # 初始化SGLang页面
        self.init_sglang_page()

        def add_metrics_sub_interface(widget: QWidget, object_name, text):
            widget.setObjectName(object_name)
            self.metrics_stacked_widget.addWidget(widget)
            self.metrics_pivot.addItem(
                routeKey=object_name,
                text=text,
                onClick=lambda: self.metrics_stacked_widget.setCurrentWidget(widget),
            )

        add_metrics_sub_interface(self.llamacpp_page, "llamacpp_page", "LlamaCpp")
        add_metrics_sub_interface(self.sglang_page, "sglang_page", "SGLang")

        self.metrics_pivot.setCurrentItem(self.metrics_stacked_widget.currentWidget().objectName())

        layout.addWidget(self.metrics_pivot)
        layout.addWidget(self.metrics_stacked_widget)

        # 添加刷新按钮
        self.refresh_metrics_button = PushButton(FIF.SYNC, "刷新数据")
        self.refresh_metrics_button.clicked.connect(self.refresh_metrics)
        layout.addWidget(self.refresh_metrics_button)

    def init_llamacpp_page(self):
        """初始化LlamaCpp指标页面"""
        layout = QVBoxLayout(self.llamacpp_page)
        layout.setContentsMargins(0, 0, 0, 0)

        # 创建表格
        self.llamacpp_table = TableWidget(self)
        self.llamacpp_table.setColumnCount(2)
        self.llamacpp_table.setHorizontalHeaderLabels(["指标", "值"])
        self.llamacpp_table.verticalHeader().setVisible(False)
        self.llamacpp_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        # 初始化指标数据
        self._init_llamacpp_metrics_data()

        layout.addWidget(self.llamacpp_table)

    def init_sglang_page(self):
        """初始化SGLang指标页面"""
        layout = QVBoxLayout(self.sglang_page)
        layout.setContentsMargins(0, 0, 0, 0)

        # 创建表格
        self.sglang_table = TableWidget(self)
        self.sglang_table.setColumnCount(2)
        self.sglang_table.setHorizontalHeaderLabels(["指标", "值"])
        self.sglang_table.verticalHeader().setVisible(False)
        self.sglang_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        # 初始化指标数据
        self._init_sglang_metrics_data()

        layout.addWidget(self.sglang_table)
        
        # 添加模型信息标签
        self.model_info_label = QLabel("模型: 未知")
        self.model_info_label.setWordWrap(True)
        layout.addWidget(self.model_info_label)

    def _init_llamacpp_metrics_data(self):
        """初始化LlamaCpp指标数据和提示信息"""
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

        self.llamacpp_table.setRowCount(len(metrics_data))
        for row, (metric, value) in enumerate(metrics_data):
            self.llamacpp_table.setItem(row, 0, QTableWidgetItem(metric))
            self.llamacpp_table.setItem(row, 1, QTableWidgetItem(value))
            if metric in tooltips:
                self.llamacpp_table.item(row, 0).setToolTip(tooltips[metric])

    def _init_sglang_metrics_data(self):
        """初始化SGLang指标数据和提示信息"""
        metrics_data = [
            ("Token使用率", "暂无数据"),
            ("缓存命中率", "暂无数据"),
            ("推测解码接受长度", "暂无数据"),
            ("提示词tokens总数", "暂无数据"),
            ("生成tokens总数", "暂无数据"),
            ("请求总数", "暂无数据"),
            ("首token平均时间", "暂无数据"),
            ("请求平均延迟", "暂无数据"),
            ("每token平均时间", "暂无数据"),
            ("当前运行请求数", "暂无数据"),
            ("当前使用tokens数", "暂无数据"),
            ("生成吞吐量", "暂无数据"),
            ("队列中请求数", "暂无数据"),
        ]

        tooltips = {
            "Token使用率": "当前token使用率",
            "缓存命中率": "前缀缓存命中率",
            "推测解码接受长度": "推测解码的平均接受长度",
            "提示词tokens总数": "已处理的提示词tokens总数",
            "生成tokens总数": "已生成的tokens总数",
            "请求总数": "已处理的请求总数",
            "首token平均时间": "生成第一个token的平均时间",
            "请求平均延迟": "端到端请求的平均延迟",
            "每token平均时间": "每个输出token的平均时间",
            "当前运行请求数": "当前正在运行的请求数",
            "当前使用tokens数": "当前使用的tokens数量",
            "生成吞吐量": "生成吞吐量(tokens/秒)",
            "队列中请求数": "等待队列中的请求数",
        }

        self.sglang_table.setRowCount(len(metrics_data))
        for row, (metric, value) in enumerate(metrics_data):
            self.sglang_table.setItem(row, 0, QTableWidgetItem(metric))
            self.sglang_table.setItem(row, 1, QTableWidgetItem(value))
            if metric in tooltips:
                self.sglang_table.item(row, 0).setToolTip(tooltips[metric])

    def _init_metrics_data(self):
        """初始化指标数据和提示信息 - 保留向后兼容"""
        self._init_llamacpp_metrics_data()

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
        # 添加检查，如果正在停止过程中，则不继续刷新
        if self._should_stop:
            self.refresh_metrics_button.setEnabled(True)
            return
            
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
        
        # 无论是否已启动API，都创建一个新的临时API进行刷新操作
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

        # 保存当前指标数据，用于键值查找
        self.current_metrics = metrics

        # 检查是否为SGLang指标
        is_sglang = metrics.get("_is_sglang", 0) > 0
        
        # 获取当前选中的标签页
        current_page = self.metrics_stacked_widget.currentWidget().objectName()
        
        # 根据指标类型更新相应的表格
        if is_sglang:
            # 更新SGLang指标
            self._update_sglang_metrics(metrics)
            # 如果当前不是SGLang页面，提示用户并询问是否切换
            if current_page != "sglang_page":
                self._switch_metrics_tab("sglang_page", "检测到SGLang指标数据")
        else:
            # 更新LlamaCpp指标
            self._update_llamacpp_metrics(metrics)
            # 如果当前不是LlamaCpp页面，提示用户并询问是否切换
            if current_page != "llamacpp_page":
                self._switch_metrics_tab("llamacpp_page", "检测到LlamaCpp指标数据")

    def _update_llamacpp_metrics(self, metrics):
        """更新LlamaCpp指标表格"""
        for row in range(self.llamacpp_table.rowCount()):
            metric_item = self.llamacpp_table.item(row, 0)
            value_item = self.llamacpp_table.item(row, 1)
            if metric_item and value_item:
                metric_text = metric_item.text()
                key = self.get_llamacpp_metric_key(metric_text)
                if key in metrics:
                    value = metrics[key]
                    self._format_llamacpp_metric_value(value_item, key, value)

    def _update_sglang_metrics(self, metrics):
        """更新SGLang指标表格"""
        # 更新模型信息
        model_name = metrics.get("_model_name", "未知")
        self.model_info_label.setText(f"模型: {model_name}")
        
        for row in range(self.sglang_table.rowCount()):
            metric_item = self.sglang_table.item(row, 0)
            value_item = self.sglang_table.item(row, 1)
            if metric_item and value_item:
                metric_text = metric_item.text()
                key = self.get_sglang_metric_key(metric_text)
                if key in metrics:
                    value = metrics[key]
                    self._format_sglang_metric_value(value_item, key, value, metrics)
                else:
                    # 尝试查找匹配的前缀
                    base_key = key.split("{")[0] if "{" in key else key
                    matching_keys = [k for k in metrics.keys() if k.startswith(base_key + "{") or k == base_key]
                    if matching_keys:
                        value = metrics[matching_keys[0]]
                        self._format_sglang_metric_value(value_item, matching_keys[0], value, metrics)

    def _format_llamacpp_metric_value(self, item, key, value):
        """格式化LlamaCpp指标值"""
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

    def _format_sglang_metric_value(self, item, key, value, metrics):
        """格式化SGLang指标值"""
        try:
            # 提取基础键名（不包含模型名称部分）
            base_key = key.split("{")[0] if "{" in key else key
            
            if base_key == "sglang:token_usage":
                item.setText(f"{float(value)*100:.2f}%")
            elif base_key == "sglang:cache_hit_rate":
                item.setText(f"{float(value)*100:.2f}%")
            elif base_key == "sglang:spec_accept_length":
                item.setText(f"{float(value):.2f}")
            elif base_key in ["sglang:prompt_tokens_total", "sglang:generation_tokens_total"]:
                item.setText(f"{float(value):,.0f} tokens")
            elif base_key == "sglang:num_requests_total":
                item.setText(f"{float(value):,.0f}")
            elif base_key in ["sglang:time_to_first_token_seconds_sum", "sglang:e2e_request_latency_seconds_sum"]:
                # 查找对应的count指标
                count_key = base_key.replace("_sum", "_count")
                # 在所有键中查找匹配的count键
                count_full_key = None
                for k in metrics.keys():
                    if k.startswith(count_key + "{") or k == count_key:
                        count_full_key = k
                        break
                
                count = metrics.get(count_full_key, 1) if count_full_key else 1
                total = float(value)
                avg = total / count if count > 0 else 0
                item.setText(f"{avg:.2f} 秒")
            elif base_key == "sglang:time_per_output_token_seconds_sum":
                # 查找对应的count指标
                count_key = base_key.replace("_sum", "_count")
                # 在所有键中查找匹配的count键
                count_full_key = None
                for k in metrics.keys():
                    if k.startswith(count_key + "{") or k == count_key:
                        count_full_key = k
                        break
                    
                count = metrics.get(count_full_key, 1) if count_full_key else 1
                total = float(value)
                avg = total / count if count > 0 else 0
                item.setText(f"{avg*1000:.2f} 毫秒")
            elif base_key in ["sglang:num_running_reqs", "sglang:num_used_tokens", "sglang:num_queue_reqs"]:
                item.setText(f"{float(value):.0f}")
            elif base_key == "sglang:gen_throughput":
                item.setText(f"{float(value):.2f} tokens/s")
            else:
                item.setText(f"{float(value):.2f}")
        except ValueError:
            item.setText(str(value))

    def get_llamacpp_metric_key(self, metric_text):
        """获取LlamaCpp指标键值映射"""
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

    def get_sglang_metric_key(self, metric_text):
        """获取SGLang指标键值映射"""
        base_key_map = {
            "Token使用率": "sglang:token_usage",
            "缓存命中率": "sglang:cache_hit_rate",
            "推测解码接受长度": "sglang:spec_accept_length",
            "提示词tokens总数": "sglang:prompt_tokens_total",
            "生成tokens总数": "sglang:generation_tokens_total",
            "请求总数": "sglang:num_requests_total",
            "首token平均时间": "sglang:time_to_first_token_seconds_sum",
            "请求平均延迟": "sglang:e2e_request_latency_seconds_sum",
            "每token平均时间": "sglang:time_per_output_token_seconds_sum",
            "当前运行请求数": "sglang:num_running_reqs",
            "当前使用tokens数": "sglang:num_used_tokens",
            "生成吞吐量": "sglang:gen_throughput",
            "队列中请求数": "sglang:num_queue_reqs",
        }
        
        base_key = base_key_map.get(metric_text, "")
        
        # 如果找不到基础键，直接返回空字符串
        if not base_key:
            return ""
        
        # 在metrics字典中查找匹配的完整键（包含模型名称）
        for full_key in self.current_metrics.keys() if hasattr(self, 'current_metrics') else []:
            if full_key.startswith(base_key + "{"):
                return full_key
        
        # 如果没有找到匹配的完整键，返回基础键
        return base_key

    def get_metric_key(self, metric_text):
        """获取指标键值映射 - 保留向后兼容"""
        return self.get_llamacpp_metric_key(metric_text)

    @Slot()
    def _start_timers(self):
        """在主线程中启动定时器"""
        self.metrics_timer.start()

    @Slot()
    def _stop_timers(self):
        """在主线程中停止定时器"""
        self.metrics_timer.stop()

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
        self.tg_token = self.tg_token_input.text().strip()

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
            self.api = SakuraShareAPI(self.port, self.worker_url)
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

            # 启动服务
            if not await self.api.start(self.tg_token):
                return "错误：启动失败，请检查配置和网络连接"

            # 发送初始状态
            self.status_update_signal.emit("运行中 - WebSocket已连接")
            
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

    @Slot()
    def stop_cf_share(self):
        """停止共享服务"""
        self._should_stop = True
        
        # 立即停止定时器，防止在停止期间继续触发刷新
        self.metrics_timer.stop()
        self.stop_timers_signal.emit()
        
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
        
        # 更新UI状态
        self.status_label.setText("状态: 正在停止...")
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(False)

    @Slot()
    def _handle_stop_finished(self, error_msg=None):
        """处理停止完成的回调"""
        # 确保定时器已经停止
        self.metrics_timer.stop()
        
        # 重置停止标志，使刷新功能恢复可用
        self._should_stop = False
        
        if error_msg:
            self.show_message_signal.emit("错误", f"停止时发生错误: {error_msg}")
        
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.status_label.setText("状态: 已停止")

    @Slot(Exception)
    def _handle_stop_error(self, error):
        """处理停止时的错误"""
        print(f"[Share] 停止过程中发生错误: {error}")
        # 重置停止标志，即使出错也能恢复刷新功能
        self._should_stop = False
        
        # 更新UI状态
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.status_label.setText(f"状态: 停止失败 - {str(error)}")
        self.show_message_signal.emit("错误", f"停止过程中发生错误: {str(error)}")

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

        # 获取slots状态
        worker = AsyncWorker(api.get_slots_status())
        worker.signals.finished.connect(self.update_slots_status)
        worker.signals.error.connect(self.on_error_refresh_slots)
        self.thread_pool.start(worker)

        # 同时获取节点列表
        tg_token = self.tg_token_input.text().strip()
        nodes_worker = AsyncWorker(api.get_nodes(tg_token))
        nodes_worker.signals.finished.connect(self.update_nodes_list)
        nodes_worker.signals.error.connect(self.on_error_refresh_nodes)
        self.thread_pool.start(nodes_worker)

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

    @Slot(object)
    def update_nodes_list(self, nodes):
        """更新节点列表显示"""
        if isinstance(nodes, list) and len(nodes) > 0 and not isinstance(nodes[0], dict):
            # 处理正常的节点ID列表
            if len(nodes) == 0:
                self.nodes_label.setText("节点列表: 当前没有在线节点")
                return
                
            nodes_text = "<b>节点列表 (Metrics IDs):</b><br>"
            for i, node_id in enumerate(nodes):
                nodes_text += f"{i+1}. <b>ID:</b> {node_id}<br>"
                
            self.nodes_label.setText(nodes_text)
            self.nodes_label.setTextFormat(Qt.RichText)
        elif isinstance(nodes, list) and len(nodes) > 0 and "error" in nodes[0]:
            # 处理错误情况
            error_msg = nodes[0]["error"]
            self.nodes_label.setText(f"节点列表: 获取失败 - {error_msg}")
            self.nodes_label.setTextFormat(Qt.PlainText)
        else:
            # 处理其他未知情况
            self.nodes_label.setText("节点列表: 获取失败 - 未知格式")
            self.nodes_label.setTextFormat(Qt.PlainText)

    @Slot(Exception)
    def on_error_refresh_nodes(self, error):
        """处理刷新节点列表时的错误"""
        self.nodes_label.setText(f"节点列表: 获取失败 - {str(error)}")

    @Slot()
    def refresh_ranking(self):
        """刷新排名数据"""
        # 添加检查，如果正在停止过程中，则不继续刷新
        if self._should_stop:
            self.refresh_ranking_button.setEnabled(True)
            return
            
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

        # API清理
        if self.api:
            try:
                def cleanup_api():
                    try:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        loop.run_until_complete(self.api.stop())
                    except Exception as e:
                        logging.error(f"Error during API cleanup: {str(e)}")
                    finally:
                        self.api = None

                QTimer.singleShot(0, cleanup_api)
            except Exception as e:
                logging.error(f"Error initiating cleanup: {str(e)}")

    @Slot(Exception)
    def on_error(self, error):
        """处理通用错误"""
        self.status_label.setText(f"状态: 错误 - {str(error)}")
        # 确保按钮恢复可用状态
        self.refresh_metrics_button.setEnabled(True)
        self.refresh_ranking_button.setEnabled(True)
        MessageBox("错误", f"操作失败: {str(error)}", self).exec_()

    def _switch_metrics_tab(self, target_page, reason):
        """智能切换指标标签页
        
        Args:
            target_page: 目标页面的objectName
            reason: 切换原因
        """
        # 直接切换标签页，不再弹出提示
        # 设置当前项
        self.metrics_pivot.setCurrentItem(target_page)
        # 同时切换堆叠小部件的当前页面
        for i in range(self.metrics_stacked_widget.count()):
            if self.metrics_stacked_widget.widget(i).objectName() == target_page:
                self.metrics_stacked_widget.setCurrentIndex(i)
                break
