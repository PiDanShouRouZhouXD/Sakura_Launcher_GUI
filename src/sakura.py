import logging
from typing import List, Dict, Optional
from dataclasses import dataclass
from pydantic import BaseModel

from hashlib import sha256

import asyncio

from .utils.download import parallel_download
from .utils.model_size_cauculator import ModelCalculator, ModelConfig

logger = logging.getLogger(__name__)


class Sakura(BaseModel):
    """Sakura 模型基础信息"""

    repo: str
    filename: str
    sha256: str
    size: float
    minimal_gpu_memory_gib: int  # NOTE(kuriko): zero means no minimum requirement
    recommended_np: Dict[int, int] = {8: 1, 10: 1, 12: 1, 16: 1, 24: 1}
    download_links: Dict[str, str] = {}
    base_model_hf: str  # HuggingFace 模型ID
    bpw: float  # bytes per weight
    config_cache: Optional[Dict] = None  # 模型配置缓存

    def to_model_config(self, context: int = 8192) -> ModelConfig:
        """转换为 ModelCalculator 可用的配置"""
        return ModelConfig(
            hf_model=self.base_model_hf,
            context=context,
            batch_size=512,
            bytes_per_weight=self.bpw,
            # 如果有缓存配置，直接传入
            config_cache=self.config_cache,
        )

    def check_sha256(self, file: str) -> bool:
        """验证文件SHA256"""
        sha256_hash = sha256()
        with open(file, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest() == self.sha256


class SakuraCalculator:
    """Sakura 模型资源计算器"""

    def __init__(self, sakura: Sakura):
        self.sakura = sakura

    def calculate_memory_requirements(
        self, context_length: int
    ) -> Dict[str, float]:
        """计算指定配置下的内存需求"""
        config = self.sakura.to_model_config(context_length)
        calculator = ModelCalculator(config)
        return calculator.calculate_sizes()

    def recommend_config(self, available_memory_gib: float) -> Dict[str, int]:
        """根据可用显存推荐配置"""

        best_config = {"context_length": 2048, "n_parallel": 1}

        # 找到当前可用显存下最大的推荐np值，但不超过16
        max_np = 1  # 默认值为1
        for memory_threshold, np in self.sakura.recommended_np.items():
            if available_memory_gib >= float(memory_threshold):
                max_np = min(np, 16)  # 限制最大np为16

        try:
            # 确保每个线程至少有1536的上下文长度
            min_ctx_per_thread = 1536
            ctx = min_ctx_per_thread * max_np
            mem_req = self.calculate_memory_requirements(ctx)

            if mem_req["total_size_gib"] <= available_memory_gib:
                best_config["context_length"] = ctx
                best_config["n_parallel"] = max_np
        except Exception as e:
            logging.warning(f"计算配置时出错: {e}")

        return best_config


def _sakura(
    repo,
    filename,
    sha256,
    size,
    minimal_gpu_memory_gib,
    recommended_np,
    base_model_hf,
    bpw,
    config_cache,
):
    return Sakura(
        repo=repo,
        filename=filename,
        sha256=sha256,
        size=size,
        minimal_gpu_memory_gib=minimal_gpu_memory_gib,
        recommended_np=recommended_np,
        base_model_hf=base_model_hf,
        bpw=bpw,
        config_cache=config_cache,
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
            minimal_gpu_memory_gib=8,
            size=4.29,
            recommended_np={"8": 2, "10": 4, "12": 12, "16": 16, "24": 16},
            base_model_hf="Qwen/Qwen1.5-7B",
            bpw=4.25,
            config_cache={
                "hidden_size": 4096,
                "num_attention_heads": 32,
                "num_key_value_heads": 32,
                "num_hidden_layers": 32,
                "parameters": 7721324544.0,
            },
        ),
        _sakura(
            repo="Sakura-14B-Qwen2.5-v1.0-GGUF",
            filename="sakura-14b-qwen2.5-v1.0-iq4xs.gguf",
            sha256="34af88f99c113418d0665d3ceede767c9a12040c9e7c4bb5e87cdb1b1e06e94a",
            minimal_gpu_memory_gib=10,
            size=8.19,
            recommended_np={"10": 4, "12": 12, "16": 16, "24": 16},
            base_model_hf="Qwen/Qwen2.5-14B",
            bpw=4.25,
            config_cache={
                "hidden_size": 5120,
                "num_attention_heads": 40,
                "num_key_value_heads": 8,
                "num_hidden_layers": 48,
                "parameters": 14770033664.0,
            },
        ),
        _sakura(
            repo="Sakura-14B-Qwen2.5-v1.0-GGUF",
            filename="sakura-14b-qwen2.5-v1.0-q4km.gguf",
            sha256="c87697cd9c7898464426cb7a1ec5e220755affaa08096766e8d20de1853c2063",
            minimal_gpu_memory_gib=10,
            size=8.99,
            recommended_np={"10": 1, "12": 6, "16": 16, "24": 16},
            base_model_hf="Qwen/Qwen2.5-14B",
            bpw=4.85,
            config_cache={
                "hidden_size": 5120,
                "num_attention_heads": 40,
                "num_key_value_heads": 8,
                "num_hidden_layers": 48,
                "parameters": 14770033664.0,
            },
        ),
        _sakura(
            repo="Sakura-14B-Qwen2beta-v0.9.2-GGUF",
            filename="sakura-14b-qwen2beta-v0.9.2-iq4xs.gguf",
            sha256="254a7e97e5e2a5daa371145e55bb2b0a0a789615dab2d4316189ba089a3ced67",
            minimal_gpu_memory_gib=12,
            size=7.91,
            recommended_np={"12": 1, "16": 6, "24": 8},
            base_model_hf="Qwen/Qwen1.5-14B",
            bpw=4.25,
            config_cache={
                "hidden_size": 5120,
                "num_attention_heads": 40,
                "num_key_value_heads": 40,
                "num_hidden_layers": 40,
                "parameters": 14167290880.0,
            },
        ),
        _sakura(
            repo="Sakura-14B-Qwen2beta-v0.9.2-GGUF",
            filename="sakura-14b-qwen2beta-v0.9.2-q4km.gguf",
            sha256="8bae1ae35b7327fa7c3a8f3ae495b81a071847d560837de2025e1554364001a5",
            minimal_gpu_memory_gib=12,
            size=9.19,
            recommended_np={"12": 1, "16": 6, "24": 8},
            base_model_hf="Qwen/Qwen1.5-14B",
            bpw=4.85,
            config_cache={
                "hidden_size": 5120,
                "num_attention_heads": 40,
                "num_key_value_heads": 40,
                "num_hidden_layers": 40,
                "parameters": 14167290880.0,
            },
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
        self.SAKURA_LIST: Dict[str, Sakura] = asyncio.run(
            self.fetch_latest_model_list()
        )

    async def fetch_latest_model_list(self) -> List[Sakura]:
        ret_model_list: List[Sakura] = []
        try:
            model_list: ModelList = await parallel_download(
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

    def __getitem__(self, name) -> Sakura:
        for model in self.SAKURA_LIST:
            if model.filename == name:
                return model
        return None

    def __iter__(self):
        for item in self.SAKURA_LIST:
            yield item


SAKURA_LIST = sakura_list_init()
