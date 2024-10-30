import os
import json
import logging
from typing import Dict, Optional
from hashlib import sha256
import requests

from .utils.model_size_cauculator import ModelCalculator, ModelConfig

SAKURA_DATA_FILE = "data/sakura_list.json"


class Sakura:
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

    def __init__(
        self,
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
        self.repo = repo
        self.filename = filename
        self.sha256 = sha256
        self.size = size
        self.minimal_gpu_memory_gib = minimal_gpu_memory_gib
        self.recommended_np = recommended_np
        self.base_model_hf = base_model_hf
        self.bpw = bpw
        self.config_cache = config_cache
        self.download_links = {
            "HFMirror": f"https://hf-mirror.com/SakuraLLM/{repo}/resolve/main/{filename}",
            "HuggingFace": f"https://huggingface.co/SakuraLLM/{repo}/resolve/main/{filename}",
        }

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

    def calculate_memory_requirements(self, context_length: int) -> Dict[str, float]:
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


class SakuraList:
    DOWNLOAD_SRC = [
        "HFMirror",
        "HuggingFace",
    ]

    def __init__(self):
        self._load_from_local()
        try:
            self._load_from_remote()
        except Exception as e:
            logging.warning(f"获取远程Sakura列表失败:{e}")

    def _load_from_local(self):
        with open(os.path.join(SAKURA_DATA_FILE), "r", encoding="utf-8") as f:
            raw_json = json.load(f)
        self._update_sakura_list(raw_json)

    def _load_from_remote(self):
        raw_json = requests.get(
            f"https://ghp.ci/https://raw.githubusercontent.com/PiDanShouRouZhouXD/Sakura_Launcher_GUI/refs/heads/main/data/model_list.json"
        ).json()
        self._update_sakura_list(raw_json)

    def _update_sakura_list(self, raw_json):
        sakura_list = []
        for obj in raw_json:
            sakura = Sakura(
                repo=obj["repo"],
                filename=obj["filename"],
                sha256=obj["sha256"],
                minimal_gpu_memory_gib=obj["minimal_gpu_memory_gib"],
                size=obj["size"],
                recommended_np=obj["recommended_np"],
                base_model_hf=obj["base_model_hf"],
                bpw=obj["bpw"],
                config_cache=obj["config_cache"],
            )
            sakura_list.append(sakura)
        self._sakura_list = sakura_list

    def __getitem__(self, name) -> Sakura:
        for model in self._sakura_list:
            if model.filename == name:
                return model
        return None

    def __iter__(self):
        for item in self._sakura_list:
            yield item


SAKURA_LIST = SakuraList()
