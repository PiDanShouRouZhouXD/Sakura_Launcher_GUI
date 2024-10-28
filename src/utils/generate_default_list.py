import json
from pathlib import Path
import black
from typing import List, Dict, Any

def load_model_list() -> Dict[str, Any]:
    """加载model_list.json文件"""
    json_path = Path(__file__).parent.parent.parent / "data" / "model_list.json"
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)

def generate_sakura_list_code(models: List[Dict[str, Any]]) -> str:
    """生成SAKURA_DEFAULT_LIST的代码"""
    items = []
    for model in models:
        # 构建_sakura函数的参数
        params = [
            f'repo="{model["repo"]}"',
            f'filename="{model["filename"]}"',
            f'sha256="{model["sha256"]}"',
            f'minimal_gpu_memory_gib={model["minimal_gpu_memory_gib"]}',
            f'size={model["size"]}',
            f'recommended_np={model["recommended_np"]}',
            f'base_model_hf="{model["base_model_hf"]}"',
            f'bpw={model["bpw"]}',
            f'config_cache={model["config_cache"]}'
        ]
        
        # 使用join而不是f-string来处理多行字符串
        param_str = ',\n            '.join(params)
        item = '        _sakura(\n            ' + param_str + '\n        )'
        items.append(item)
    
    # 同样使用join来处理多行字符串
    items_str = ',\n'.join(items)
    code = '    SAKURA_DEFAULT_LIST = [\n' + items_str + '\n    ]'
    
    return code

def update_sakura_file():
    """更新src/sakura.py文件中的SAKURA_DEFAULT_LIST"""
    # 加载model_list.json
    model_list = load_model_list()
    
    # 生成新的代码
    new_code = generate_sakura_list_code(model_list["models"])
    
    # 读取现有的sakura.py文件
    sakura_path = Path(__file__).parent.parent / "sakura.py"
    with open(sakura_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # 查找并替换SAKURA_DEFAULT_LIST部分
    start_marker = "class sakura_list_init:"
    list_start = content.find("    SAKURA_DEFAULT_LIST = [", content.find(start_marker))
    list_end = content.find("\n\n", list_start)
    
    # 替换内容
    new_content = content[:list_start] + new_code + content[list_end:]
    
    # 使用black格式化代码
    new_content = black.format_file_contents(
        new_content, 
        fast=False,
        mode=black.FileMode()
    )
    
    # 写回文件
    with open(sakura_path, "w", encoding="utf-8") as f:
        f.write(new_content)

if __name__ == "__main__":
    update_sakura_file()
