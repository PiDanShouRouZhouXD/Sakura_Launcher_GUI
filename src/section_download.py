from dataclasses import dataclass
from enum import Enum
import logging
import os
import json
import requests
from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QFrame,
    QHeaderView,
    QTableWidgetItem,
)
from qfluentwidgets import (
    FluentIcon as FIF,
    TableWidget,
    TransparentPushButton,
    ProgressBar,
    InfoBar,
)

from .common import CURRENT_DIR, get_resource_path, GHPROXY_URL
from .llamacpp import *
from .sakura import SAKURA_LIST, Sakura
from .ui import *


def UiDescription(html):
    description = QLabel()
    description.setText(html)
    description.setTextFormat(Qt.RichText)
    description.setWordWrap(True)
    description.setOpenExternalLinks(True)
    description.setMargin(4)
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


class LoadDataThread(QThread):
    def run(self):
        DATA_FILE = "data.json"
        with open(get_resource_path(DATA_FILE), "r", encoding="utf-8") as f:
            data_json = json.load(f)
        SAKURA_LIST.update_sakura_list(data_json)
        LLAMACPP_LIST.update_llamacpp_list(data_json)

        repo = "PiDanShouRouZhouXD/Sakura_Launcher_GUI"
        for link in [
            f"https://{GHPROXY_URL}/https://raw.githubusercontent.com/{repo}/refs/heads/main/{DATA_FILE}",
            f"https://cdn.jsdelivr.net/gh/{repo}@main/{DATA_FILE}",
            f"https://cdn.rawgit.com/{repo}/refs/heads/main/{DATA_FILE}",
            f"https://raw.githubusercontent.com/{repo}/refs/heads/main/{DATA_FILE}",
        ]:
            try:
                data_json = requests.get(link, timeout=1).json()
                SAKURA_LIST.update_sakura_list(data_json)
                LLAMACPP_LIST.update_llamacpp_list(data_json)
                break
            except Exception as e:
                logging.warning(f"获取远程数据失败: {link} {e}")


class DownloadTaskState(Enum):
    RUNNING = 1
    SUCCESS = 2
    ERROR = 3


@dataclass
class DownloadTask:
    name: str
    url: str
    filename: str
    state: DownloadTaskState = DownloadTaskState.RUNNING


class DownloadThread(QThread):
    sig_progress = Signal(int)
    sig_success = Signal()
    sig_error = Signal(str)

    def __init__(self, url, filename):
        super().__init__()
        self.url = url
        self.filename = filename
        self._is_finished = False

    def run(self):
        try:
            logging.info(f"开始下载: {self.url} => {self.filename}")
            response = requests.get(self.url, stream=True)
            response.raise_for_status()

            total_size = int(response.headers.get("content-length", 0))
            block_size = 1024  # 1 KB
            downloaded_size = 0

            file_path = os.path.join(CURRENT_DIR, self.filename)
            with open(file_path, "wb") as file:
                for data in response.iter_content(block_size):
                    size = file.write(data)
                    downloaded_size += size
                    if total_size > 0:
                        progress = int((downloaded_size / total_size) * 100)
                        self.sig_progress.emit(progress)

            logging.info(f"下载完成: {self.filename}")

            if not self._is_finished:
                self._is_finished = True
                self.sig_success.emit()
        except requests.RequestException as e:
            error_msg = f"下载出错: {str(e)}"
            logging.info(error_msg)
            self.sig_error.emit(error_msg)
        except IOError as e:
            error_msg = f"文件写入错误: {str(e)}"
            logging.info(error_msg)
            self.sig_error.emit(error_msg)
        except Exception as e:
            error_msg = f"未知错误: {str(e)}"
            logging.info(error_msg)
            self.sig_error.emit(error_msg)

    def safe_disconnect(self):
        logging.info("正在断开下载线程的所有信号连接")
        try:
            self.sig_progress.disconnect()
            logging.info("断开 progress 信号")
        except TypeError:
            pass
        try:
            self.sig_success.disconnect()
            logging.info("断开 finished 信号")
        except TypeError:
            pass
        try:
            self.sig_error.disconnect()
            logging.info("断开 error 信号")
        except TypeError:
            pass
        logging.info("下载线程的所有信号已断开")

    def stop(self):
        logging.info("正在停止下载线程")
        self.terminate()
        self.wait()
        self._is_finished = True
        logging.info("下载线程已停止")


class DownloadSection(QFrame):
    llamacpp_download_src = LLAMACPP_LIST.DOWNLOAD_SRC[0]
    sakura_download_src = SAKURA_LIST.DOWNLOAD_SRC[0]
    download_tasks: List[DownloadTask] = []
    download_threads: List[QThread] = []

    def __init__(self, title):
        super().__init__()
        self.setObjectName(title.replace(" ", "-"))
        self.init_ui()

    def init_ui(self):
        self.setLayout(
            UiStackedWidget(
                ("Sakura模型下载", self._create_sakura_download_section()),
                ("llama.cpp下载", self._create_llamacpp_download_section()),
                ("下载进度", self._create_download_progress_section()),
            ),
        )
        LoadDataThread(self).start()

    def refresh_sakura_table(self, sakura_list):
        table = self.sakura_table

        def create_button(sakura: Sakura):
            download_fn = lambda: self.start_download_sakura(sakura)
            button = UiDownloadButton(download_fn)
            return button

        table.clearContents()
        for row, sakura in enumerate(sakura_list):
            if table.rowCount() <= row:
                table.insertRow(row)
            table.setItem(row, 0, UiTableLabel(sakura.filename))
            table.setItem(row, 1, UiTableLabel(f"{sakura.size}GB"))
            table.setCellWidget(row, 2, create_button(sakura))

    def _create_sakura_download_section(self):
        def on_src_change(text):
            self.sakura_download_src = text

        comboBox = UiRow(
            QLabel("下载源"),
            None,
            UiComboBox(SAKURA_LIST.DOWNLOAD_SRC, on_src_change),
        )

        self.sakura_table = UiTable(["名称", "大小", "操作"])
        SAKURA_LIST.changed.connect(self.refresh_sakura_table)

        description = UiDescription(
            """
        <p>您可以在这里下载不同版本的模型，模型会保存到启动器所在的目录。如果启动器无法下载，您也可以手动从<a href="https://hf-mirror.com/SakuraLLM/Sakura-14B-Qwen2beta-v0.9.2-GGUF/">Hugging Face镜像站</a>下载模型，将下载的gguf文件放到启动器所在文件夹下即可。</p>
        <p>翻译Galgame推荐使用7B模型，12G以下显存可用。翻译小说推荐使用14B模型，需要12G及以上显存。</p>
        """
        )

        return UiCol(
            description,
            UiHLine(),
            comboBox,
            self.sakura_table,
        )

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
        self.llamacpp_table = UiTable(["版本", "适合显卡", "下载"])
        self.refresh_llamacpp_table()

        LLAMACPP_LIST.changed.connect(self.refresh_llamacpp_table)

        def on_src_change(text):
            self.llamacpp_download_src = text

        select_download_src = UiRow(
            QLabel("下载源"),
            None,
            UiComboBox(LLAMACPP_LIST.DOWNLOAD_SRC, on_src_change),
        )

        self.label_current_llamacpp_version = QLabel()
        self._update_current_llamacpp_version()
        current_version_hint = UiRow(
            QLabel("当前版本"),
            (self.label_current_llamacpp_version, 0),
        )

        description = UiDescription(
            """
        <p>
        下载的llama.cpp会解压到启动器所在的目录，如果存在旧版本，会自动覆盖。你也可以手动从<a href="https://github.com/ggerganov/llama.cpp/releases">GitHub发布页面</a>下载发行版。
        intel ARC用户请参考<a href="https://github.com/intel-analytics/ipex-llm/blob/main/docs/mddocs/Quickstart/llama_cpp_quickstart.md">这篇文档</a>来手动安装，在启动器指定软链接路径<b>可能</b>可以使用。
        Vulkan版本现在还不支持IQ系列的量化。
        </p>
        <p><b>ROCm支持的AMD独显型号(感谢Sora维护)</b></p>
        <ul>
            <li>RX 7900 / 7800 / 7700系列显卡</li>
            <li>RX 6900 / 6800 / 6700系列显卡</li>
        </ul>
        <p><b>ROCm-780m支持的AMD核显型号</b></p>
        <ul>
            <li>7840hs / 7940hs / 8840hs / 8845hs </li>
            <li>理论上支持任何2022年后的AMD GPU，但要求CPU支持AVX512，且不对任何非780m显卡的可用性负责</li>
        </ul>
        """
        )

        return UiCol(
            description,
            UiHLine(),
            select_download_src,
            current_version_hint,
            self.llamacpp_table,
        )

    def _create_download_progress_section(self):
        self.download_progress_layout = UiCol()
        self.download_progress_layout.addStretch()
        return self.download_progress_layout

    def _start_download_task(self, new_task: DownloadTask, on_finish):
        for task in self.download_tasks:
            if task.state == DownloadTaskState.RUNNING and task.name == new_task.name:
                InfoBar.warning(
                    title=f"{new_task.filename}已在下载中",
                    content="",
                    parent=self,
                )
                return

        self.download_tasks.append(new_task)

        progress_bar = ProgressBar()
        self.download_progress_layout.insertLayout(
            0,
            UiCol(
                QLabel(f"<b>{new_task.name}</b>"),
                QLabel(new_task.filename),
                progress_bar,
            ),
        )

        def on_error(error_message):
            new_task.state = DownloadTaskState.ERROR
            logging.error(f"下载失败 {error_message}")
            QApplication.processEvents()  # 确保UI更新
            UiInfoBarError(self, f"{new_task.name}下载失败", content=f"{error_message}")

        thread = DownloadThread(new_task.url, new_task.filename)
        thread.sig_progress.connect(progress_bar.setValue)
        thread.sig_success.connect(on_finish)
        thread.sig_error.connect(on_error)
        thread.start()

        self.download_threads.append(thread)

        logging.info(f"开始下载: URL={new_task.url}, 文件名={new_task.filename}")
        UiInfoBarSuccess(self, f"{new_task.name}开始下载，请在下载进度页面查看进度")

    def _update_current_llamacpp_version(self):
        version = get_llamacpp_version(os.path.join(CURRENT_DIR, "llama"))
        if version:
            self.label_current_llamacpp_version.setText(f"b{version}")
        else:
            self.label_current_llamacpp_version.setText("未检测到")

    def start_download_sakura(self, sakura: Sakura):
        src = self.sakura_download_src
        task = DownloadTask(
            name="Sakura模型",
            url=sakura.download_links[src],
            filename=sakura.filename,
        )

        def on_download_sakura_finish():
            file_path = os.path.join(CURRENT_DIR, task.filename)
            if sakura.check_sha256(file_path):
                task.state = DownloadTaskState.SUCCESS
                UiInfoBarSuccess(self, f"{task.name}下载成功")
            else:
                task.state = DownloadTaskState.ERROR
                UiInfoBarError(self, f"{task.name}校验失败")
                os.remove(file_path)  # 删除校验失败的文件

        self._start_download_task(task, on_finish=on_download_sakura_finish)

    def start_download_cudart(self):
        src = self.llamacpp_download_src
        cudart = LLAMACPP_LIST.CUDART
        task = DownloadTask(
            name="CUDA-RT",
            url=cudart["download_links"][src],
            filename=cudart["filename"],
        )

        def on_download_cudart_finish():
            file_path = os.path.join(CURRENT_DIR, task.filename)
            try:
                task.state = DownloadTaskState.SUCCESS
                unzip_llamacpp(CURRENT_DIR, task.filename)
                UiInfoBarSuccess(self, f"{task.name}下载成功")
            except Exception as e:
                task.state = DownloadTaskState.ERROR
                UiInfoBarError(self, f"{task.name}解压失败", content=str(e))
            finally:
                # 无论解压是否成功，都删除原始zip文件
                if os.path.exists(file_path):
                    os.remove(file_path)

        self._start_download_task(task, on_finish=on_download_cudart_finish)

    def start_download_llamacpp(self, llamacpp: Llamacpp):
        src = self.llamacpp_download_src
        task = DownloadTask(
            name="Llamacpp",
            url=llamacpp.download_links[src],
            filename=llamacpp.filename,
        )

        def on_download_llamacpp_finish():
            file_path = os.path.join(CURRENT_DIR, task.filename)
            try:
                task.state = DownloadTaskState.SUCCESS
                unzip_llamacpp(CURRENT_DIR, task.filename)
                UiInfoBarSuccess(self, f"{task.name}下载成功")
                self._update_current_llamacpp_version()
            except Exception as e:
                task.state = DownloadTaskState.ERROR
                UiInfoBarError(self, f"{task.name}解压失败", content=str(e))
            finally:
                # 无论解压是否成功，都删除原始zip文件
                if os.path.exists(file_path):
                    os.remove(file_path)

        self._start_download_task(task, on_finish=on_download_llamacpp_finish)

        if llamacpp.require_cuda and not is_cudart_exist(CURRENT_DIR):
            self.start_download_cudart()

    def start_download_launcher(self, version: str):
        filename = f"Sakura_Launcher_GUI_{version}.exe"
        url = f"https://github.com/PiDanShouRouZhouXD/Sakura_Launcher_GUI/releases/download/{version}/{filename}"
        if self.llamacpp_download_src == "GHProxy":
            url = f"https://{GHPROXY_URL}/" + url

        task = DownloadTask(
            name="Sakura启动器",
            url=url,
            filename=filename,
        )

        def on_finish():
            task.state = DownloadTaskState.SUCCESS
            UiInfoBarSuccess(self, f"{task.name}下载成功")

        self._start_download_task(task, on_finish=on_finish)
