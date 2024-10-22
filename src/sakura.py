import logging
from typing import List, Dict
from dataclasses import dataclass
from pydantic import BaseModel

from hashlib import sha256

import asyncio

from .utils.download import parallel_download

logger = logging.getLogger(__name__)


class Sakura(BaseModel):
    repo: str
    filename: str
    sha256: str
    size: float
    minimal_gpu_memory_gb: int
    recommended_np: Dict[int, int] = {8: 1, 10: 1, 12: 1, 16: 1, 24: 1}
    download_links: Dict[str, str] = {}

    def check_sha256(self, file: str):
        sha256_hash = sha256()
        with open(file, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest() == self.sha256


def _sakura(repo, filename, sha256, size, minimal_gpu_memory_gb, recommended_np):
    return Sakura(
        repo=repo,
        filename=filename,
        sha256=sha256,
        size=size,
        minimal_gpu_memory_gb=minimal_gpu_memory_gb,
        recommended_np=recommended_np,
        download_links={
            "HFMirror": f"https://hf-mirror.com/SakuraLLM/{repo}/resolve/main/{filename}",
            "HuggingFace": f"https://huggingface.co/SakuraLLM/{repo}/resolve/main/{filename}",
        },
    )


SAKURA_DOWNLOAD_SRC = [
    "HFMirror",
    "HuggingFace",
]


class ModelList(BaseModel):
    created_at: int
    models: List[Sakura]


class sakura_list_init:
    SAKURA_DEFAULT_LIST = [
        _sakura(
            repo="GalTransl-7B-v2.6",
            filename="GalTransl-7B-v2.6-IQ4_XS.gguf",
            sha256="f1095c715bd37d6df1f674e86382723fe1fe45c3b4f9c80a4452bcf9128d3eca",
            minimal_gpu_memory_gb=8,
            size=4.29,
            recommended_np={8: 2, 10: 2, 12: 8, 16: 12, 24: 16},
        ),
        _sakura(
            repo="SakuraLLM/Sakura-14B-Qwen2.5-v1.0-GGUF",
            filename="sakura-14b-qwen2.5-v1.0-iq4xs.gguf",
            sha256="34af88f99c113418d0665d3ceede767c9a12040c9e7c4bb5e87cdb1b1e06e94a",
            minimal_gpu_memory_gb=10,
            size=8.19,
            recommended_np={10: 2, 12: 8, 16: 12, 24: 16},
        ),
        _sakura(
            repo="SakuraLLM/Sakura-14B-Qwen2.5-v1.0-GGUF",
            filename="sakura-14b-qwen2.5-v1.0-q4km.gguf",
            sha256="c87697cd9c7898464426cb7a1ec5e220755affaa08096766e8d20de1853c2063",
            minimal_gpu_memory_gb=10,
            size=8.99,
            recommended_np={10: 1, 12: 6, 16: 12, 24: 16},
        ),
        _sakura(
            repo="Sakura-14B-Qwen2beta-v0.9.2-GGUF",
            filename="sakura-14b-qwen2beta-v0.9.2-iq4xs.gguf",
            sha256="254a7e97e5e2a5daa371145e55bb2b0a0a789615dab2d4316189ba089a3ced67",
            minimal_gpu_memory_gb=12,
            size=7.91,
            recommended_np={12: 1, 16: 6, 24: 8},
        ),
        _sakura(
            repo="Sakura-14B-Qwen2beta-v0.9.2-GGUF",
            filename="sakura-14b-qwen2beta-v0.9.2-q4km.gguf",
            sha256="8bae1ae35b7327fa7c3a8f3ae495b81a071847d560837de2025e1554364001a5",
            minimal_gpu_memory_gb=12,
            size=9.19,
            recommended_np={12: 1, 16: 6, 24: 8},
        ),
    ]

    def __init__(self):
        username = "PiDanShouRouZhouXD"

        self.update_file_mirror_list = [
            # Mirror
            f"https://gh-proxy.com/https://raw.githubusercontent.com/{username}/Sakura_Launcher_GUI/refs/heads/main/data/model_list.json",
            f"https://ghp.ci/https://raw.githubusercontent.com/{username}/Sakura_Launcher_GUI/refs/heads/main/data/model_list.json",
            # JsDelivr CDN
            f"https://cdn.jsdelivr.net/gh/{username}/Sakura_Launcher_GUI@main/data/model_list.json",
            # rawgit CDN, but not recommended
            f"https://cdn.rawgit.com/{username}/Sakura_Launcher_GUI/refs/heads/main/data/model_list.json",
            # Direct access
            f"https://raw.githubusercontent.com/{username}/Sakura_Launcher_GUI/refs/heads/main/data/model_list.json",
        ]

        # FIXME(kuriko): This will add delay (max to 3s) in startup,
        #   we should split the model_list load schema in section_download.py
        self.SAKURA_LIST = asyncio.run(self.fetch_latest_model_list())

    async def fetch_latest_model_list(self):
        ret_model_list = []
        try:
            model_list = await parallel_download(
                self.update_file_mirror_list,
                json=True,
                parser=lambda data: ModelList(**data),
                timeout=3,
            )

            print(f"当前模型列表：{model_list}")

            for model in model_list.models:
                # FIXME(kuriko): move download links to model_list.json rather than hard coded.
                ret_model_list.append(
                    _sakura(**model.model_dump(exclude={"download_links"}))
                )

        except Exception as e:
            logger.error("无法获取模型列表, 回退到内置默认模型列表")
            ret_model_list = self.SAKURA_DEFAULT_LIST

        return ret_model_list

    def __getitem__(self, name):
        for model in self.SAKURA_LIST:
            if model.filename == name:
                return model
        return None

    def __iter__(self):
        for item in self.SAKURA_LIST:
            yield item


SAKURA_LIST = sakura_list_init()
