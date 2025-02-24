import logging
import os
import re
import subprocess
import sys
from typing import Dict, List
import zipfile

from PySide6.QtCore import QObject, Signal

from .common import GHPROXY_URL



class Llamacpp:
    repo: str
    filename: str
    version: str
    gpu: str
    require_cuda: bool
    download_links: Dict[str, str]

    def __init__(
        self,
        repo: str,
        filename: str,
        version: str,
        gpu: str,
        require_cuda: bool,
    ):
        self.repo = repo
        self.version = version
        self.gpu = gpu
        self.filename = filename
        self.require_cuda = require_cuda
        github_repo = f"https://github.com/{repo}/{filename}"
        self.download_links = {
            "GHProxy": f"https://{GHPROXY_URL}/" + github_repo,
            "GitHub": github_repo,
        }


class LlamacppList(QObject):
    DOWNLOAD_SRC = [
        "GHProxy",
        "GitHub",
    ]
    CUDART = {
        "filename": "cudart-llama-bin-win-cu12.2.0-x64.zip",
        "download_links": {
            "GitHub": "https://github.com/ggerganov/llama.cpp/releases/download/b3926/cudart-llama-bin-win-cu12.2.0-x64.zip",
            "GHProxy": f"https://{GHPROXY_URL}/https://github.com/ggerganov/llama.cpp/releases/download/b3926/cudart-llama-bin-win-cu12.2.0-x64.zip",
        },
    }
    _list: List[Llamacpp] = []
    changed = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)

    def update_llamacpp_list(self, data_json):
        llamacpp_list = []
        for obj in data_json["llamacpp"]:
            llamacpp = Llamacpp(
                repo=obj["repo"],
                filename=obj["filename"],
                version=obj["version"],
                gpu=obj["gpu"],
                require_cuda=obj["require_cuda"],
            )
            llamacpp_list.append(llamacpp)
        self._list = llamacpp_list
        self.changed.emit(llamacpp_list)

    def __iter__(self):
        for item in self._list:
            yield item


LLAMACPP_LIST = LlamacppList()


def unzip_llamacpp(folder: str, filename: str):
    llama_folder = os.path.join(folder, "llama")
    file_path = os.path.join(folder, filename)
    print(f"将解压 {filename} 到 {llama_folder}")

    if not os.path.exists(llama_folder):
        os.mkdir(llama_folder)

    # 解压，如果文件已存在则覆盖
    if filename.endswith(".zip"):
        with zipfile.ZipFile(file_path, "r") as zip_ref:
            zip_ref.extractall(llama_folder)
        # macOS build 中解压后产生的是'llama/build/bin'文件夹，需要将其中的所有内容移动到llama文件夹下
        if sys.platform == "darwin":
            bin_folder = os.path.join(llama_folder, "build", "bin")
            for item in os.listdir(bin_folder):
                src_path = os.path.join(bin_folder, item)
                dst_path = os.path.join(llama_folder, item)
                os.rename(src_path, dst_path)
                # 添加执行权限 (755 = rwxr-xr-x)
                os.chmod(dst_path, 0o755)
            # 删除空文件夹
            import shutil
            shutil.rmtree(os.path.join(llama_folder, "build"))
    else:
        print(f"不支持的文件格式: {filename}")
        return

    print(f"{filename} 已成功解压到 {llama_folder}")


def is_cudart_exist(folder: str):
    llama_folder = os.path.join(folder, "llama")
    for filename in [
        "cublas64_12.dll",
        "cublasLt64_12.dll",
        "cudart64_12.dll",
    ]:
        if not os.path.exists(os.path.join(llama_folder, filename)):
            return False
    return True


def get_llamacpp_version(llamacpp_path: str):
    exe_extension = ".exe" if sys.platform == "win32" else ""
    executable_path = os.path.join(llamacpp_path, f"llama-server{exe_extension}")
    try:
        logging.info(f"尝试执行命令: {executable_path} --version")
        result = subprocess.run(
            [executable_path, "--version"],
            capture_output=True,
            text=True,
            timeout=2,
            shell=os.name == "nt",
        )
        version_output = result.stderr.strip()  # 使用 stderr 而不是 stdout
        logging.info(f"版本输出: {version_output}")
        version_match = re.search(r"version: (\d+)", version_output)
        if version_match:
            return int(version_match.group(1))
        else:
            logging.info("无法匹配版本号")
    except subprocess.TimeoutExpired as e:
        logging.info(f"获取llama.cpp版本超时: {e.stdout}, {e.stderr}")
    except Exception as e:
        logging.info(f"获取llama.cpp版本时出错: {str(e)}")
    return None
