import os
import requests
import zipfile
import py7zr
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
)
from qfluentwidgets import (
    MessageBox,
    FluentIcon as FIF,
    TableWidget,
    TransparentPushButton,
    SegmentedWidget,
    ProgressBar,
)

from common import CURRENT_DIR, get_self_path, logger


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
    model_links = [
        (
            "GalTransl-7B-v2-IQ4_XS.gguf",
            "https://hf-mirror.com/SakuraLLM/GalTransl-7B-v2/resolve/main/GalTransl-7B-v2-IQ4_XS.gguf",
        ),
        (
            "sakura-14b-qwen2beta-v0.9.2-iq4xs.gguf",
            "https://hf-mirror.com/SakuraLLM/Sakura-14B-Qwen2beta-v0.9.2-GGUF/resolve/main/sakura-14b-qwen2beta-v0.9.2-iq4xs.gguf",
        ),
        (
            "sakura-14b-qwen2beta-v0.9.2-q4km.gguf",
            "https://hf-mirror.com/SakuraLLM/Sakura-14B-Qwen2beta-v0.9.2-GGUF/resolve/main/sakura-14b-qwen2beta-v0.9.2-q4km.gguf",
        ),
    ]
    llamacpp_links = [
        (
            "b3855-CUDA",
            "Nvidia独显",
            "https://mirror.ghproxy.com/https://github.com/PiDanShouRouZhouXD/Sakura_Launcher_GUI/releases/download/v0.0.3-alpha/llama-b3855-bin-win-cuda-cu12.2.0-x64.7z",
        ),
        (
            "b3384-ROCm",
            "部分AMD独显",
            "https://mirror.ghproxy.com/https://github.com/PiDanShouRouZhouXD/Sakura_Launcher_GUI/releases/download/v0.0.3-alpha/llama-b3384-bin-win-rocm-avx2-x64.zip",
        ),
        (
            "b3534-ROCm-780m",
            "部分AMD核显",
            "https://mirror.ghproxy.com/https://github.com/PiDanShouRouZhouXD/Sakura_Launcher_GUI/releases/download/v0.0.3-alpha/llama-b3534-bin-win-rocm-avx512-x64.zip",
        ),
        (
            "b3855-Vulkan",
            "通用，不推荐",
            "https://mirror.ghproxy.com/https://github.com/PiDanShouRouZhouXD/Sakura_Launcher_GUI/releases/download/v0.0.3-alpha/llama-b3855-bin-win-vulkan-x64.zip",
        ),
    ]

    def __init__(self, title, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.setObjectName(title.replace(" ", "-"))
        self.resize(400, 400)
        self.init_ui()

    def init_ui(self):
        self.pivot = SegmentedWidget(self)
        self.stacked_widget = QStackedWidget(self)
        self.layout = QVBoxLayout(self)

        self.model_download_section = QWidget(self)
        self.llamacpp_download_section = QWidget(self)

        self.init_model_download_section()
        self.init_llamacpp_download_section()

        self.add_sub_interface(
            self.model_download_section, "model_download_section", "模型下载"
        )
        self.add_sub_interface(
            self.llamacpp_download_section, "llamacpp_download_section", "llama.cpp下载"
        )

        self.layout.addWidget(self.pivot)
        self.layout.addWidget(self.stacked_widget)

        # 添加全局进度条
        self.global_progress_bar = ProgressBar(self)
        self.layout.addWidget(self.global_progress_bar)

        self.stacked_widget.currentChanged.connect(self.on_current_index_changed)
        self.stacked_widget.setCurrentWidget(self.model_download_section)
        self.pivot.setCurrentItem(self.model_download_section.objectName())

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

    def init_model_download_section(self):
        table = self.create_download_table(["名称", "操作"])
        for name, url in self.model_links:
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, self.create_table_label(name))
            # 使用默认参数来捕获当前的 url 和 name
            download_fn = lambda url=url, name=name: self.start_download(url, name)
            table.setCellWidget(row, 1, self.create_table_button(download_fn))

        description = self.create_description_label(
            """
        <p>您可以在这里下载不同版本的模型，模型会保存到启动器所在的目录。您也可以手动从<a href="https://hf-mirror.com/SakuraLLM/Sakura-14B-Qwen2beta-v0.9.2-GGUF/">Hugging Face镜像站</a>下载模型。</p>
        <p>12G以下显存推荐使用GalTransl-7B-v2-IQ4_XS.gguf</p>
        <p>12G及以上显存推荐使用Sakura-14B-Qwen2beta-v0.9.2_IQ4_XS.gguf</p>
        <p>如果您的网络状况不佳，可能会出现没有反应或卡住的情况。遇到这种情况时，请直接从上述链接下载后，将模型文件（.gguf）放到启动器所在目录下。</p>
        """
        )

        layout = QVBoxLayout(self.model_download_section)
        layout.addWidget(description)
        layout.addWidget(table)
        self.model_download_section.setLayout(layout)

    def init_llamacpp_download_section(self):
        table = self.create_download_table(["版本", "适合显卡", "下载"])
        # 添加GitHub最新CUDA版本选项
        latest_cuda = self.get_latest_cuda_release()
        if latest_cuda:
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(
                row, 0, self.create_table_label(f"最新CUDA版本 ({latest_cuda['name']})")
            )
            table.setItem(row, 1, self.create_table_label("Nvidia独显"))
            download_fn = lambda url=latest_cuda["url"], name=latest_cuda[
                "name"
            ]: self.start_download(url, name)
            table.setCellWidget(row, 2, self.create_table_button(download_fn))

        # 添加现有的下载选项
        for version, gpu, url in self.llamacpp_links:
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, self.create_table_label(version))
            table.setItem(row, 1, self.create_table_label(gpu))
            # 从 URL 中提取文件名
            filename = url.split("/")[-1]
            download_fn = lambda url=url, filename=filename: self.start_download(
                url, filename
            )
            table.setCellWidget(row, 2, self.create_table_button(download_fn))

        description = self.create_description_label(
            """
        <p>您可以在这里下载不同版本的llama.cpp，文件会保存到启动器所在的目录。您也可以手动从<a href="https://github.com/ggerganov/llama.cpp/releases">GitHub发布页面</a>下载发行版。</p>
        <p><b>ROCm支持的独显型号(感谢Sora维护)</b>
            <ul>
                <li>RX 7900 / 7800 / 7700系列显卡</li>
                <li>RX 6900 / 6800 / 6700系列显卡</li>
            </ul>
        </p>
        <p><b>ROCm-780m支持的核显型号</b>
            <ul>
                <li>7840hs/7940hs/8840hs/8845hs </li>
                <li>理论上支持任何2022年后的AMD GPU，但要求CPU支持AVX512，且不对任何非780m显卡的可用性负责</li>
            </ul>
        </p>
        <p><b>注意：</b></p>
        <p>最新CUDA版本不包含cudart，如果你不知道这是什么，请不要下载最新CUDA版本</p>
        <p>Vulkan版本现在还不支持IQ系列的量化。</p>
        """
        )

        layout = QVBoxLayout(self.llamacpp_download_section)
        layout.addWidget(description)
        layout.addWidget(table)
        self.llamacpp_download_section.setLayout(layout)

    def create_description_label(self, content):
        description = QLabel()
        description.setText(content)
        description.setTextFormat(Qt.RichText)
        description.setWordWrap(True)
        description.setOpenExternalLinks(True)  # 允许打开外部链接
        description.setMargin(16)
        description.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse
        )
        return description

    def create_download_table(self, columns):
        table = TableWidget()
        table.setColumnCount(len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.verticalHeader().hide()
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    def create_table_label(self, text):
        item = QTableWidgetItem(text)
        item.setFlags(Qt.ItemIsEnabled)
        return item

    def create_table_button(self, download_function):
        download_button = TransparentPushButton(FIF.DOWNLOAD, "下载")
        download_button.clicked.connect(download_function)
        return download_button

    def unzip_llamacpp(self, filename):
        llama_folder = os.path.join(CURRENT_DIR, "llama")
        file_path = os.path.join(CURRENT_DIR, filename)
        print(f"解压 {filename} 到 {llama_folder}")

        if not os.path.exists(llama_folder):
            os.mkdir(llama_folder)

        # 解压，如果文件已存在则覆盖
        if filename.endswith(".zip"):
            with zipfile.ZipFile(file_path, "r") as zip_ref:
                zip_ref.extractall(llama_folder)
        elif filename.endswith(".7z"):
            with py7zr.SevenZipFile(file_path, mode="r") as z:
                z.extractall(llama_folder)
        else:
            print(f"不支持的文件格式: {filename}")
            return

        print(f"{filename} 已成功解压到 {llama_folder}")

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
                self.unzip_llamacpp(downloaded_file)
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
            expected_sha256 = ""
            if downloaded_file == "GalTransl-7B-v2-IQ4_XS.gguf":
                expected_sha256 = (
                    "8749e704993a2c327f319278818ba0a7f9633eae8ed187d54eb63456a11812aa"
                )
            elif downloaded_file == "sakura-14b-qwen2beta-v0.9.2-iq4xs.gguf":
                expected_sha256 = (
                    "254a7e97e5e2a5daa371145e55bb2b0a0a789615dab2d4316189ba089a3ced67"
                )
            elif downloaded_file == "sakura-14b-qwen2beta-v0.9.2-q4km.gguf":
                expected_sha256 = (
                    "8bae1ae35b7327fa7c3a8f3ae495b81a071847d560837de2025e1554364001a5"
                )

            if expected_sha256:
                if self.check_sha256(file_path, expected_sha256):
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

    def check_sha256(self, filename, expected_sha256):
        sha256_hash = sha256()
        with open(filename, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest() == expected_sha256

    def on_download_error(self, error_message):
        logger.error(f"Download error: {error_message}")
        QApplication.processEvents()  # 确保UI更新
        MessageBox("错误", f"下载失败: {error_message}", self).exec()

    def get_latest_cuda_release(self):
        try:
            # 发送请求到最新release页面
            response = requests.get(
                "https://github.com/ggerganov/llama.cpp/releases/latest",
                allow_redirects=False,
            )

            # 从重定向URL中提取版本号
            if response.status_code == 302:
                redirect_url = response.headers.get("Location")
                version = redirect_url.split("/")[-1]

                # 构造下载URL
                download_url = f"https://github.com/ggerganov/llama.cpp/releases/download/{version}/llama-{version}-bin-win-cuda-cu12.2.0-x64.zip"

                return {
                    "name": f"llama-{version}-bin-win-cuda-cu12.2.0-x64.zip",
                    "url": download_url,
                }
            else:
                self.main_window.log_info("无法获取最新版本信息")
                return None
        except Exception as e:
            self.main_window.log_info(f"获取最新CUDA版本时出错: {str(e)}")
            return None
