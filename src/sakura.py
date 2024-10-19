from dataclasses import dataclass
from typing import Dict
from hashlib import sha256


@dataclass
class Sakura:
    repo: str
    filename: str
    sha256: str
    size: float
    download_links: Dict[str, str]

    def check_sha256(self, file: str):
        sha256_hash = sha256()
        with open(file, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest() == self.sha256


def _sakura(repo, filename, sha256, size):
    return Sakura(
        repo=repo,
        filename=filename,
        sha256=sha256,
        size=size,
        download_links={
            "HFMirror": f"https://hf-mirror.com/SakuraLLM/{repo}/resolve/main/{filename}",
            "HuggingFace": f"https://huggingface.co/SakuraLLM/{repo}/resolve/main/{filename}",
        },
    )


SAKURA_DOWNLOAD_SRC = [
    "HFMirror",
    "HuggingFace",
]

SAKURA_LIST = [
    _sakura(
        repo="GalTransl-7B-v2.6",
        filename="GalTransl-7B-v2.6-IQ4_XS.gguf",
        sha256="f1095c715bd37d6df1f674e86382723fe1fe45c3b4f9c80a4452bcf9128d3eca",
        size=4.29,
    ),
    _sakura(
        repo="SakuraLLM/Sakura-14B-Qwen2.5-v1.0-GGUF",
        filename="sakura-14b-qwen2.5-v1.0-iq4xs.gguf",
        sha256="34af88f99c113418d0665d3ceede767c9a12040c9e7c4bb5e87cdb1b1e06e94a",
        size=8.19,
    ),
    _sakura(
        repo="SakuraLLM/Sakura-14B-Qwen2.5-v1.0-GGUF",
        filename="sakura-14b-qwen2.5-v1.0-q4km.gguf",
        sha256="c87697cd9c7898464426cb7a1ec5e220755affaa08096766e8d20de1853c2063",
        size=8.99,
    ),
    _sakura(
        repo="Sakura-14B-Qwen2beta-v0.9.2-GGUF",
        filename="sakura-14b-qwen2beta-v0.9.2-iq4xs.gguf",
        sha256="254a7e97e5e2a5daa371145e55bb2b0a0a789615dab2d4316189ba089a3ced67",
        size=7.91,
    ),
    _sakura(
        repo="Sakura-14B-Qwen2beta-v0.9.2-GGUF",
        filename="sakura-14b-qwen2beta-v0.9.2-q4km.gguf",
        sha256="8bae1ae35b7327fa7c3a8f3ae495b81a071847d560837de2025e1554364001a5",
        size=9.19,
    ),
]
