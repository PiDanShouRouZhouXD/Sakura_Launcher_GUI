from dataclasses import dataclass
from typing import Optional, Dict
import logging
import json
import requests
from bs4 import BeautifulSoup

# 设置日志配置
logging.basicConfig(
    level=logging.DEBUG, 
    format="%(asctime)s - %(levelname)s - %(message)s"
)

@dataclass
class ModelConfig:
    """模型配置和计算参数"""
    hf_model: str
    hf_token: str = ""
    context: int = 8192
    batch_size: int = 512
    cache_bit: int = 16
    bytes_per_weight: float = 4.5
    config_cache: Optional[Dict] = None
    filename: Optional[str] = None

class ModelCalculator:
    def __init__(self, config: ModelConfig):
        self.config = config
        logging.debug(
            f"Initializing ModelCalculator with model: {config.hf_model}, "
            f"context: {config.context}, batch_size: {config.batch_size}, "
            f"cache_bit: {config.cache_bit}, bytes_per_weight: {config.bytes_per_weight}, "
            f"filename: {config.filename}"
        )
        self.model_config = self._get_model_config()
    
    def _get_model_config(self) -> Dict:
        """获取模型配置,优先使用config_cache"""
        if self.config.config_cache:
            logging.debug(f"Using config cache for model: {self.config.hf_model}")
            return {
                "hidden_size": self.config.config_cache["hidden_size"],
                "num_attention_heads": self.config.config_cache["num_attention_heads"],
                "num_key_value_heads": self.config.config_cache["num_key_value_heads"],
                "num_hidden_layers": self.config.config_cache["num_hidden_layers"],
                "parameters": self.config.config_cache["parameters"],
            }
                
        return self._fetch_model_config()
    
    def _get_cached_config(self) -> Optional[Dict]:
        """从缓存文件获取配置"""
        try:
            with open(self.config.cache_path, "r") as f:
                model_list = json.load(f)
                for model in model_list["models"]:
                    if self._is_model_match(model) and "config_cache" in model:
                        logging.debug(f"Using cached config for model: {self.config.hf_model}")
                        return {
                            "hidden_size": model["config_cache"]["hidden_size"],
                            "num_attention_heads": model["config_cache"]["num_attention_heads"],
                            "num_key_value_heads": model["config_cache"]["num_key_value_heads"],
                            "num_hidden_layers": model["config_cache"]["num_hidden_layers"],
                            "parameters": model["config_cache"]["parameters"],
                        }
        except Exception as e:
            logging.debug(f"Cache read error: {e}")
        return None

    def _is_model_match(self, model: Dict) -> bool:
        """检查模型是否匹配"""
        return (self.config.filename and model.get("filename") == self.config.filename) or \
               (not self.config.filename and model["base_model_hf"] == self.config.hf_model)

    def _fetch_model_config(self) -> Dict:
        """从HuggingFace获取模型配置"""
        headers = {"Authorization": f"Bearer {self.config.hf_token}"} if self.config.hf_token else {}
        
        # 获取基础配置
        config_url = f"https://huggingface.co/{self.config.hf_model}/raw/main/config.json"
        logging.debug(f"Fetching model config from: {config_url}")
        config = requests.get(config_url, headers=headers).json()
        
        # 获取模型大小
        config["parameters"] = self._get_model_size(headers)
        logging.debug(f"Model parameters size: {config['parameters']}")
        return config

    def _get_model_size(self, headers: Dict) -> float:
        """尝试不同方式获取模型大小"""
        try:
            # 尝试从safetensors获取
            url = f"https://huggingface.co/{self.config.hf_model}/resolve/main/model.safetensors.index.json"
            logging.debug(f"Fetching model size from: {url}")
            return requests.get(url, headers=headers).json()["metadata"]["total_size"] / 2
        except Exception as e:
            logging.error(f"Failed to fetch safetensors model size: {e}")
            try:
                # 尝试从pytorch获取
                url = f"https://huggingface.co/{self.config.hf_model}/resolve/main/pytorch_model.bin.index.json"
                logging.debug(f"Fetching model size from: {url}")
                return requests.get(url, headers=headers).json()["metadata"]["total_size"] / 2
            except Exception as e:
                logging.error(f"Failed to fetch pytorch model size: {e}")
                # 从页面解析
                return self._parse_size_from_page(headers)

    def _parse_size_from_page(self, headers: Dict) -> float:
        """从HuggingFace页面解析模型大小"""
        model_page = requests.get(
            f"https://huggingface.co/{self.config.hf_model}", 
            headers=headers
        ).text
        target = "ModelSafetensorsParams" if "ModelSafetensorsParams" in model_page else "ModelHeader"
        return self._extract_model_size(model_page, target)

    def _extract_model_size(self, page_content: str, target: str) -> float:
        """从页面内容提取模型大小"""
        logging.debug(f"Extracting model size from page content with target: {target}")
        soup = BeautifulSoup(page_content, "html.parser")
        params_el = soup.find("div", {"data-target": target})
        data_props = params_el["data-props"]
        size = float(data_props.split('"total":')[1].split(",")[0])
        logging.debug(f"Extracted model size: {size}")
        return size

    def calculate_sizes(self) -> Dict[str, float]:
        """计算所有相关的大小"""
        logging.debug("Calculating total size")
        model_size = self._calculate_model_size()
        context_size = self._calculate_context_size()
        
        # 转换为GiB
        model_size_gib = model_size / (2**30)
        context_size_gib = context_size / (2**30)
        total_size_gib = model_size_gib + context_size_gib
        
        logging.debug(
            f"Total size - Model: {model_size_gib} GiB, "
            f"Context: {context_size_gib} GiB, "
            f"Total: {total_size_gib} GiB"
        )
        
        return {
            "model_size_gib": model_size_gib,
            "context_size_gib": context_size_gib,
            "total_size_gib": total_size_gib
        }

    def _calculate_model_size(self) -> float:
        """计算模型大小"""
        if self.config.config_cache:
            try:
                cached_size = self.config.config_cache["parameters"] * self.config.bytes_per_weight / 8
                logging.debug(f"Using cached size: {cached_size} bytes")
                return cached_size
            except Exception as e:
                logging.debug(f"Error using cached size: {e}")
        
        size = round(self.model_config["parameters"] * self.config.bytes_per_weight / 8, 2)
        logging.debug(f"Model size: {size}")
        return size

    def _calculate_context_size(self) -> float:
        """计算上下文大小"""
        return round(
            self._calculate_input_buffer() + 
            self._calculate_kv_cache() + 
            self._calculate_compute_buffer(), 
            2
        )

    def _calculate_input_buffer(self) -> float:
        """计算输入缓冲区大小"""
        logging.debug("Calculating input buffer size")
        total_input_buffer = sum([
            self.config.batch_size,  # inp_tokens
            self.model_config["hidden_size"] * self.config.batch_size,  # inp_embd
            self.config.batch_size,  # inp_pos
            self.config.context * self.config.batch_size,  # inp_KQ_mask
            self.config.context,  # inp_K_shift
            self.config.batch_size  # inp_sum
        ])
        logging.debug(f"Input buffer size: {total_input_buffer}")
        return total_input_buffer

    def _calculate_compute_buffer(self) -> float:
        """计算计算缓冲区大小"""
        if self.config.batch_size != 512:
            logging.warning(
                "Batch size other than 512 is currently not supported for the compute buffer, "
                "using batch size 512 for compute buffer calculation, "
                "end result will be an overestimation"
            )
        compute_buffer_size = (
            (self.config.context / 1024 * 2 + 0.75) *
            self.model_config["num_attention_heads"] *
            1024 * 1024
        )
        logging.debug(f"Compute buffer size: {compute_buffer_size}")
        return compute_buffer_size

    def _calculate_kv_cache(self) -> float:
        """计算KV缓存大小"""
        logging.debug("Calculating KV cache size")
        n_gqa = (
            self.model_config["num_attention_heads"] /
            self.model_config["num_key_value_heads"]
        )
        n_embd_gqa = self.model_config["hidden_size"] / n_gqa
        n_elements = n_embd_gqa * (
            self.model_config["num_hidden_layers"] * self.config.context
        )
        size = 2 * n_elements
        kv_cache_size = size * (self.config.cache_bit / 8)
        logging.debug(f"KV cache size: {kv_cache_size}")
        return kv_cache_size


def update_model_list(json_file_path: str) -> None:
    """更新模型列表的配置缓存"""
    logging.debug(f"Updating model list from file: {json_file_path}")
    with open(json_file_path, "r") as f:
        model_list = json.load(f)

    for model in model_list["models"]:
        logging.debug(f"Fetching config for model: {model['base_model_hf']}")
        config = ModelConfig(
            hf_model=model["base_model_hf"],
            bytes_per_weight=model["bpw"]
        )
        calculator = ModelCalculator(config)
        
        model["config_cache"] = {
            "hidden_size": calculator.model_config["hidden_size"],
            "num_attention_heads": calculator.model_config["num_attention_heads"],
            "num_key_value_heads": calculator.model_config["num_key_value_heads"],
            "num_hidden_layers": calculator.model_config["num_hidden_layers"],
            "parameters": calculator.model_config["parameters"],
        }

    with open(json_file_path, "w") as f:
        json.dump(model_list, f, indent=4)
    logging.debug("Model configs cached successfully")


def calculate_model_size_from_cache(model_list_path: str) -> None:
    """从缓存计算模型大小"""
    with open(model_list_path, "r") as f:
        model_list = json.load(f)
    
    for model in model_list["models"]:
        config = ModelConfig(
            hf_model=model["base_model_hf"],
            bytes_per_weight=model["bpw"],
            context=24576,
            config_cache=model["config_cache"],
            filename=model["filename"]
        )
        calculator = ModelCalculator(config)
        calculator.calculate_sizes()


if __name__ == "__main__":
    update_model_list("data/model_list.json")
    # calculate_model_size_from_cache("data/model_list.json")