from dataclasses import dataclass
import os
import re
from typing import Dict, List
import zipfile
import py7zr
import requests


@dataclass
class Llamacpp:
    version: str
    gpu: str
    require_cuda: bool
    filename: str
    download_links: Dict[str, str]


def _llamacpp(filename: str):
    b_number = re.findall(r"b\d+", filename)[0]
    version = b_number
    gpu = "未知"
    if "vulkan" in filename:
        version = b_number + "-Vulkan"
        gpu = "通用，不推荐"
    elif "rocm-avx512" in filename:
        version = b_number + "-ROCm-780m"
        gpu = "部分AMD核显"
    elif "rocm-avx2" in filename:
        version = b_number + "-ROCm"
        gpu = "部分AMD独显"
    elif "cuda" in filename:
        version = b_number + "-CUDA"
        gpu = "Nvidia独显"

    if "rocm" in filename:
        github_repo = "https://github.com/PiDanShouRouZhouXD/Sakura_Launcher_GUI/releases/download/v0.0.3-alpha/"
    else:
        github_repo = (
            f"https://github.com/ggerganov/llama.cpp/releases/download/{b_number}/"
        )

    return Llamacpp(
        version=version,
        gpu=gpu,
        filename=filename,
        require_cuda=gpu == "Nvidia独显",
        download_links={
            "GHProxy": "https://ghp.ci/" + github_repo + filename,
            "GitHub": github_repo + filename,
        },
    )


LLAMACPP_DOWNLOAD_SRC = [
    "GitHub",
    "GHProxy",
]

LLAMACPP_LIST: List[Llamacpp] = [
    _llamacpp("llama-b3923-bin-win-cuda-cu12.2.0-x64.zip"),
    _llamacpp("llama-b3384-bin-win-rocm-avx2-x64.zip"),
    _llamacpp("llama-b3534-bin-win-rocm-avx512-x64.zip"),
    _llamacpp("llama-b3923-bin-win-vulkan-x64.zip"),
]

LLAMACPP_CUDART = {
    "filename": "cudart-llama-bin-win-cu12.2.0-x64.zip",
    "download_links": {
        "GitHub": "https://github.com/ggerganov/llama.cpp/releases/download/b3926/cudart-llama-bin-win-cu12.2.0-x64.zip",
        "GHProxy": "https://ghp.ci/https://github.com/ggerganov/llama.cpp/releases/download/b3926/cudart-llama-bin-win-cu12.2.0-x64.zip",
    },
}


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
    elif filename.endswith(".7z"):
        with py7zr.SevenZipFile(file_path, mode="r") as z:
            z.extractall(llama_folder)
    else:
        print(f"不支持的文件格式: {filename}")
        return

    with open(os.path.join(llama_folder, "VERSION"), "w") as f:
        f.write(filename)

    print(f"{filename} 已成功解压到 {llama_folder}")


def get_latest_cuda_release():
    response = requests.get(
        "https://github.com/ggerganov/llama.cpp/releases/latest",
        allow_redirects=False,
    )

    if response.status_code == 302:
        redirect_url = response.headers.get("Location")
        b_number = redirect_url.split("/")[-1]
        download_url = f"https://github.com/ggerganov/llama.cpp/releases/download/{b_number}/llama-{b_number}-bin-win-cuda-cu12.2.0-x64.zip"
        llamacpp = _llamacpp(f"llama-{b_number}-bin-win-cuda-cu12.2.0-x64.zip")
        llamacpp.download_links = {
            "GitHub": download_url,
            "GHProxy": "https://ghp.ci/" + download_url,
        }
        llamacpp.version += "-最新"
        LLAMACPP_LIST.insert(0, llamacpp)
    else:
        raise RuntimeError("无法获取最新版本信息")


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
