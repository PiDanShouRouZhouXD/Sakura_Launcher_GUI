

# Sakura Launcher GUI

<!-- PROJECT LOGO -->
<br />

<p align="center">
  <a href="https://github.com/PiDanShouRouZhouXD/Sakura_Launcher_GUI/">
    <img src="icon.ico" alt="Logo" width="80" height="80">
  </a>

  <h3 align="center">Sakura Launcher GUI</h3>
  <p align="center">
    一个简单的Sakura启动器
    <br />
    <a href="https://github.com/PiDanShouRouZhouXD/Sakura_Launcher_GUI/issues">报告Bug</a>
    ·
    <a href="https://github.com/PiDanShouRouZhouXD/Sakura_Launcher_GUI/issues">提出新特性</a>
    ·
    <a href="https://github.com/PiDanShouRouZhouXD/Sakura_Launcher_GUI/pulls">贡献代码</a>
  </p>

</p>

 本篇README.md主要面向开发者，如需使用指南，请查看[用户手册](https://github.com/PiDanShouRouZhouXD/Sakura_Launcher_GUI/blob/main/Sakura%20Launcher%20GUI%20%E7%94%A8%E6%88%B7%E6%89%8B%E5%86%8C.md)。

## 目录

- [Sakura Launcher GUI](#sakura-launcher-gui)
  - [目录](#目录)
    - [**界面预览**](#界面预览)
    - [**安装步骤**](#安装步骤)
    - [**代码结构**](#代码结构)
    - [**打包**](#打包)
    - [**注意事项**](#注意事项)
    - [**基于项目**](#基于项目)


### **界面预览**

<div align=center><img src="assets\PixPin_2024-11-13_02-15-00.png" width="540px"></div>

### **安装步骤**

1. Clone 仓库并进入仓库目录

```sh
git clone https://github.com/PiDanShouRouZhouXD/Sakura_Launcher_GUI.git
cd Sakura_Launcher_GUI
```

2. 安装依赖

```sh
pip install -r requirements.txt
```

3. 运行

```sh
python main.py
```

### **代码结构**

```python
main.py                     # 主程序入口,初始化窗口和导航界面

src/:
├── common.py              # 通用工具函数,包含路径处理和版本信息
├── gpu.py                 # GPU管理器实现,负责检测和管理显卡资源
├── llamacpp.py           # llama.cpp管理,包含版本检测和下载功能
├── sakura.py             # Sakura模型类定义,处理模型信息和配置
├── sakura_share_api.py   # Sakura共享功能的API实现
├── sakura_share_cli.py   # Sakura共享功能的命令行工具
├── setting.py            # 程序设置管理,处理配置的保存和加载
├── ui.py                 # 通用UI组件和界面工具函数

页面实现:
├── section_about.py      # "关于"页面,显示版本信息和项目链接
├── section_download.py   # "下载"页面,管理模型和llama.cpp下载
├── section_run_server.py # "启动"页面,处理服务启动和性能测试
├── section_settings.py   # "设置"页面,提供程序配置界面
├── section_share.py      # "共享"页面,实现模型共享功能

工具类(src/utils/):
├── gpu/
│   ├── __init__.py       # GPU相关数据结构定义
│   └── nvidia.py         # NVIDIA GPU 已占用显存获取
├── model_size_cauculator.py  # 模型大小计算器
├── windows.py            # Windows下初始化GPU的工具
└── __init__.py
```

### **打包**

```sh
pyinstaller --clean --noconfirm main.spec
```

### **注意事项**

- 请确保已安装 Python 3.x 环境（推荐3.12）
- 建议使用包管理器安装依赖，如 [miniforge](https://github.com/conda-forge/miniforge)

### **基于项目**

- [llama.cpp](https://github.com/ggerganov/llama.cpp)
- [SakuraLLM](https://github.com/SakuraLLM/SakuraLLM)
- [PyQt-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets)
