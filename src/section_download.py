import os
import requests
from hashlib import sha256
from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtWidgets import (
    QApplication,
    QVBoxLayout,
    QLabel,
    QFrame,
    QHeaderView,
    QTableWidgetItem,
    QWidget,
    QStackedWidget,
    QHBoxLayout,
)
from qfluentwidgets import (
    MessageBox,
    FluentIcon as FIF,
    TableWidget,
    TransparentPushButton,
    SegmentedWidget,
    ProgressBar,
)

from .common import CURRENT_DIR, get_self_path
from .llamacpp import (
    LLAMACPP_CUDART,
    LLAMACPP_DOWNLOAD_SRC,
    LLAMACPP_LIST,
    Llamacpp,
    get_latest_cuda_release,
    unzip_llamacpp,
)
from .sakura import SAKURA_DOWNLOAD_SRC, SAKURA_LIST, Sakura
from .ui import *


def UiDescription(html):
    description = QLabel()
    description.setText(html)
    description.setTextFormat(Qt.RichText)
    description.setWordWrap(True)
    description.setOpenExternalLinks(True)
    description.setMargin(16)
    description.setTextInteractionFlags(
        Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse
    )
    return description


def UiTable(columns):
    table = TableWidget()
    table.setColumnCount(len(columns))
    table.setHorizontalHeaderLabels(columns)
    vh = table.verticalHeader()
    hh = table.horizontalHeader()
    vh.hide()
    vh.setSectionResizeMode(QHeaderView.ResizeToContents)
    hh.setSectionResizeMode(QHeaderView.ResizeToContents)
    hh.setStretchLastSection(True)
    return table


def UiTableLabel(text):
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemIsEnabled)
    return item


def UiDownloadButton(on_click):
    download_button = TransparentPushButton(FIF.DOWNLOAD, "下载")
    download_button.clicked.connect(on_click)
    return download_button


class DownloadThread(QThread):
    progress = Signal(int)
    finished = Signal()
    error = Signal(str)

    def __init__(self, url, filename, main_window):
        super().__init__()
        self.url = url
        self.filename = filename
        self.main_window = main_window
        self._is_finished = False

    def run(self):
        try:
            self.main_window.log_info(f"开始下载: {self.filename}")
            response = requests.get(self.url, stream=True)
            response.raise_for_status()

            total_size = int(response.headers.get("content-length", 0))
            block_size = 1024  # 1 KB
            downloaded_size = 0

            file_path = os.path.join(get_self_path(), self.filename)
            with open(file_path, "wb") as file:
                for data in response.iter_content(block_size):
                    size = file.write(data)
                    downloaded_size += size
                    if total_size > 0:
                        progress = int((downloaded_size / total_size) * 100)
                        self.progress.emit(progress)

            self.main_window.log_info(f"下载完成: {self.filename}")

            if not self._is_finished:
                self._is_finished = True
                self.finished.emit()
        except requests.RequestException as e:
            error_msg = f"下载出错: {str(e)}"
            self.main_window.log_info(error_msg)
            self.error.emit(error_msg)
        except IOError as e:
            error_msg = f"文件写入错误: {str(e)}"
            self.main_window.log_info(error_msg)
            self.error.emit(error_msg)
        except Exception as e:
            error_msg = f"未知错误: {str(e)}"
            self.main_window.log_info(error_msg)
            self.error.emit(error_msg)

    def safe_disconnect(self):
        self.main_window.log_info("正在断开下载线程的所有信号连接")
        try:
            self.progress.disconnect()
            self.main_window.log_info("断开 progress 信号")
        except TypeError:
            pass
        try:
            self.finished.disconnect()
            self.main_window.log_info("断开 finished 信号")
        except TypeError:
            pass
        try:
            self.error.disconnect()
            self.main_window.log_info("断开 error 信号")
        except TypeError:
            pass
        self.main_window.log_info("下载线程的所有信号已断开")

    def stop(self):
        self.main_window.log_info("正在停止下载线程")
        self.terminate()
        self.wait()
        self._is_finished = True
        self.main_window.log_info("下载线程已停止")


class DownloadSection(QFrame):
    llamacpp_download_src = "GHProxy"
    sakura_download_src = "HFMirror"

    def __init__(self, title, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.setObjectName(title.replace(" ", "-"))
        self.init_ui()

    def init_ui(self):
        self.pivot = SegmentedWidget()
        self.stacked_widget = QStackedWidget()
        self.layout = QVBoxLayout()

        self.add_sub_interface(
            self._create_sakura_download_section(),
            "model_download_section",
            "模型下载",
        )
        self.add_sub_interface(
            self._create_llamacpp_download_section(),
            "llamacpp_download_section",
            "llama.cpp下载",
        )

        self.layout.addWidget(self.pivot)
        self.layout.addWidget(self.stacked_widget)

        # 添加全局进度条
        self.global_progress_bar = ProgressBar(self)
        self.layout.addWidget(self.global_progress_bar)

        self.stacked_widget.currentChanged.connect(self.on_current_index_changed)
        self.stacked_widget.setCurrentIndex(0)
        self.pivot.setCurrentItem(self.stacked_widget.currentWidget().objectName())

        self.setLayout(self.layout)

    def add_sub_interface(self, widget: QWidget, object_name, text):
        widget.setObjectName(object_name)
        self.stacked_widget.addWidget(widget)
        self.pivot.addItem(
            routeKey=object_name,
            text=text,
            onClick=lambda: self.stacked_widget.setCurrentWidget(widget),
        )

    def on_current_index_changed(self, index):
        widget = self.stacked_widget.widget(index)
        self.pivot.setCurrentItem(widget.objectName())

    def _create_sakura_download_section(self):
        def on_src_change(text):
            self.sakura_download_src = text

        comboBox = UiRow(
            QLabel("下载源"),
            None,
            UiComboBox(SAKURA_DOWNLOAD_SRC, on_src_change),
        )
        on_src_change(SAKURA_DOWNLOAD_SRC[0])

        def create_button(sakura: Sakura):
            download_fn = lambda: self.start_download_sakura(sakura)
            button = UiDownloadButton(download_fn)
            return button

        table = UiTable(["名称", "大小", "操作"])
        for sakura in SAKURA_LIST:
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, UiTableLabel(sakura.filename))
            table.setItem(row, 1, UiTableLabel(f"{sakura.size}GB"))
            table.setCellWidget(row, 2, create_button(sakura))

        description = UiDescription(
            """
        <p>您可以在这里下载不同版本的模型，模型会保存到启动器所在的目录。您也可以手动从<a href="https://hf-mirror.com/SakuraLLM/Sakura-14B-Qwen2beta-v0.9.2-GGUF/">Hugging Face镜像站</a>下载模型。</p>
        <p>12G以下显存推荐使用GalTransl-7B-v2-IQ4_XS.gguf</p>
        <p>12G及以上显存推荐使用Sakura-14B-Qwen2beta-v0.9.2_IQ4_XS.gguf</p>
        <p>如果您的网络状况不佳，可能会出现没有反应或卡住的情况。遇到这种情况时，请直接从上述链接下载后，将模型文件（.gguf）放到启动器所在目录下。</p>
        """
        )

        section = QWidget()
        section.setLayout(
            UiCol(
                description,
                UiHLine(),
                comboBox,
                table,
            )
        )
        return section

    def refresh_llamacpp_table(self):
        table = self.llamacpp_table

        def create_button(llamacpp: Llamacpp):
            download_fn = lambda: self.start_download_llamacpp(llamacpp)
            button = UiDownloadButton(download_fn)
            button.setEnabled(self.llamacpp_download_src in llamacpp.download_links)
            return button

        table.clearContents()
        for row, llamacpp in enumerate(LLAMACPP_LIST):
            if table.rowCount() <= row:
                table.insertRow(row)
            table.setItem(row, 0, UiTableLabel(llamacpp.version))
            table.setItem(row, 1, UiTableLabel(llamacpp.gpu))
            table.setCellWidget(row, 2, create_button(llamacpp=llamacpp))

    def _create_llamacpp_download_section(self):
        try:
            get_latest_cuda_release()
        except Exception as e:
            self.main_window.log_info(f"获取最新CUDA版本时出错: {str(e)}")

        self.llamacpp_table = UiTable(["版本", "适合显卡", "下载"])
        self.refresh_llamacpp_table()

        def on_src_change(text):
            self.llamacpp_download_src = text

        comboBox = UiRow(
            QLabel("下载源"),
            None,
            UiComboBox(LLAMACPP_DOWNLOAD_SRC, on_src_change),
        )
        on_src_change(LLAMACPP_DOWNLOAD_SRC[0])

        def create_cudart_button():
            download_fn = lambda: self.start_download_cudart()
            button = UiDownloadButton(download_fn)
            layout = QHBoxLayout()
            layout.addWidget(QLabel("下载CUDA"))
            layout.addWidget(button)
            return layout

        cudart_button = create_cudart_button()

        description = UiDescription(
            """
        <p>下载的llama.cpp会解压到启动器所在的目录，如果存在旧版本，会自动覆盖。你也可以手动从<a href="https://github.com/ggerganov/llama.cpp/releases">GitHub发布页面</a>下载发行版。</p>
        <p><b>ROCm支持的AMD独显型号(感谢Sora维护)</b>
        <ul>
            <li>RX 7900 / 7800 / 7700系列显卡</li>
            <li>RX 6900 / 6800 / 6700系列显卡</li>
        </ul>
        </p>
        <p><b>ROCm-780m支持的AMD核显型号</b>
        <ul>
            <li>7840hs / 7940hs / 8840hs / 8845hs </li>
            <li>理论上支持任何2022年后的AMD GPU，但要求CPU支持AVX512，且不对任何非780m显卡的可用性负责</li>
        </ul>
        </p>
        <p><b>注意：</b></p>
        <ul>
            <li>Vulkan版本现在还不支持IQ系列的量化。</li>
            <li>intel ARC用户可以参考<a href="https://github.com/intel-analytics/ipex-llm/blob/main/docs/mddocs/Quickstart/llama_cpp_quickstart.md">这篇文档</a>来手动安装llamacpp，在启动器指定软链接路径<b>可能</b>可以正常使用。
        </ur>
        """
        )

        section = QWidget()
        section.setLayout(
            UiCol(
                description,
                UiHLine(),
                comboBox,
                cudart_button,
                self.llamacpp_table,
            )
        )
        return section

    def start_download_sakura(self, sakura: Sakura):
        src = self.sakura_download_src
        url = sakura.download_links[src]
        self.start_download(url, sakura.filename)

    def start_download_cudart(self):
        cudart = LLAMACPP_CUDART
        src = self.llamacpp_download_src
        url = cudart["download_links"][src]
        self.start_download(url, cudart["filename"])

    def start_download_llamacpp(self, llamacpp: Llamacpp):
        src = self.llamacpp_download_src
        url = llamacpp.download_links[src]
        if url:
            self.start_download(url, llamacpp.filename)
        else:
            self.main_window.log_info(f"当前下载源不支持该llamacpp版本，请换其他源")

    # 直接使用requests下载
    def start_download(self, url, filename):
        self.main_window.log_info(f"开始下载: URL={url}, 文件名={filename}")

        # 重置下载状态
        if hasattr(self, "_download_processed"):
            delattr(self, "_download_processed")

        # 确保旧的下载线程已经停止并且信号已经断开
        if hasattr(self, "download_thread"):
            self.download_thread.safe_disconnect()
            self.download_thread.wait()  # 等待线程完全停止

        self.download_thread = DownloadThread(url, filename, self.main_window)

        # 连接信号，使用 Qt.UniqueConnection 确保只连接一次
        self.download_thread.progress.connect(
            self.global_progress_bar.setValue, Qt.UniqueConnection
        )
        self.download_thread.finished.connect(
            self.on_download_finished, Qt.UniqueConnection
        )
        self.download_thread.error.connect(self.on_download_error, Qt.UniqueConnection)

        self.download_thread.start()
        self.main_window.createSuccessInfoBar(
            "下载中", "文件正在下载，请耐心等待，下载进度请关注最下方的进度条。"
        )

    def on_download_finished(self):
        if hasattr(self, "_download_processed") and self._download_processed:
            self.main_window.log_info("下载已经处理过，跳过重复处理")
            return

        self._download_processed = True
        self.main_window.log_info("开始处理下载完成的文件")
        self.main_window.createSuccessInfoBar("下载完成", "文件已成功下载")
        # 获取下载的文件名
        downloaded_file = self.download_thread.filename
        file_path = os.path.join(CURRENT_DIR, downloaded_file)

        # 检查文件是否存在
        if not os.path.exists(file_path):
            self.main_window.log_info(f"错误：文件 {file_path} 不存在")
            return

        # 检查是否为llama.cpp文件
        if downloaded_file.startswith("llama"):
            try:
                unzip_llamacpp(CURRENT_DIR, downloaded_file)
                self.main_window.createSuccessInfoBar(
                    "解压完成", "已经将llama.cpp解压到程序所在目录的llama文件夹内。"
                )
            except Exception as e:
                self.main_window.log_info(f"解压文件时出错: {str(e)}")
            finally:
                # 无论解压是否成功，都删除原始zip文件
                if os.path.exists(file_path):
                    os.remove(file_path)
        else:
            # 对模型文件进行SHA256校验
            sakura = next(s for s in SAKURA_LIST if s.filename == downloaded_file)
            if sakura:
                if sakura.check_sha256(file_path):
                    self.main_window.createSuccessInfoBar(
                        "校验成功", "文件SHA256校验通过。"
                    )
                else:
                    self.main_window.createWarningInfoBar(
                        "校验失败", "文件SHA256校验未通过，请重新下载。"
                    )
                    os.remove(file_path)  # 删除校验失败的文件
            else:
                self.main_window.createWarningInfoBar(
                    "未校验", "无法为此文件执行SHA256校验。"
                )

        # 不要删除标志，以防止重复处理
        # delattr(self, '_download_processed')

    def on_download_error(self, error_message):
        self.main_window.log_info(f"Download error: {error_message}")
        QApplication.processEvents()  # 确保UI更新
        MessageBox("错误", f"下载失败: {error_message}", self).exec()
