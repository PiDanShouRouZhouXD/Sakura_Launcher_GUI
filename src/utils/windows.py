import logging
from typing import List
from dataclasses import dataclass
import winreg
from src.common import DEBUG_BUILD

logger = logging.getLogger(__name__)

@dataclass
class AdapterInfoFromReg:
    AdapterString: str
    MemorySize: int
    pci_bus_id: str|None = None

def get_gpu_mem_info() -> List[AdapterInfoFromReg]:
    # This key is set by miniport driver
    # Ref: https://learn.microsoft.com/en-us/windows-hardware/drivers/display/registering-hardware-information
    base_key = r"SYSTEM\ControlSet001\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    adapter_values: List[AdapterInfoFromReg] = []

    if DEBUG_BUILD:
        logging.debug(f"开始从Windows注册表读取GPU信息: {base_key}")

    try:
        # Open the base registry key
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base_key) as base:
            i = 0
            while True:
                try:
                    subkey_name = winreg.EnumKey(base, i)
                    if DEBUG_BUILD:
                        logging.debug(f"发现注册表子键: {subkey_name}")
                        
                    if subkey_name.startswith("0"):  # Filter subkeys starting with '0'
                        subkey_path = f"{base_key}\\{subkey_name}"
                        if DEBUG_BUILD:
                            logging.debug(f"处理GPU适配器子键: {subkey_path}")
                            
                        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, subkey_path) as subkey:
                            adapter_string = winreg.QueryValueEx(subkey, "HardwareInformation.AdapterString")[0]
                            # FIXME(kuriko): this is a workaround from b"A\x00M\x00D\x00...."
                            if type(adapter_string) == bytes:
                                adapter_string = "".join(filter(lambda x: x != '\x00', adapter_string.decode("utf-8")))
                                if DEBUG_BUILD:
                                    logging.debug(f"转换二进制适配器名称: {adapter_string}")
                                    
                            memory_size = winreg.QueryValueEx(subkey, "HardwareInformation.qwMemorySize")[0]
                            
                            # 尝试读取 PCI 总线 ID
                            try:
                                location_info = winreg.QueryValueEx(subkey, "LocationInformation")[0]
                                # LocationInformation 通常包含 "PCI bus %d, device %d, function %d"
                                if "PCI bus" in location_info:
                                    pci_bus_id = location_info
                                    if DEBUG_BUILD:
                                        logging.debug(f"读取到PCI总线ID: {pci_bus_id}")
                                else:
                                    pci_bus_id = None
                                    if DEBUG_BUILD:
                                        logging.debug(f"未找到有效的PCI总线ID，位置信息: {location_info}")
                            except (WindowsError, FileNotFoundError) as e:
                                pci_bus_id = None
                                if DEBUG_BUILD:
                                    logging.debug(f"读取PCI总线ID失败: {e}")
                                
                            adapter_info = AdapterInfoFromReg(
                                AdapterString=adapter_string,
                                MemorySize=memory_size,
                                pci_bus_id=pci_bus_id
                            )
                            
                            if DEBUG_BUILD:
                                from src.utils import BytesToGiB
                                mem_gib = BytesToGiB(memory_size)
                                logging.debug(f"添加GPU适配器: 名称={adapter_string}, 显存={mem_gib:.2f}GiB, PCI={pci_bus_id}")
                                
                            adapter_values.append(adapter_info)
                except FileNotFoundError:
                    # Continue if the value doesn't exist
                    if DEBUG_BUILD:
                        logging.debug(f"子键 {i} 未找到所需值，继续检查下一个")
                    pass
                except OSError:
                    # No more subkeys
                    if DEBUG_BUILD:
                        logging.debug(f"没有更多子键，共处理 {i} 个子键")
                    break
                i += 1

    except OSError as e:
        logger.error(f"Error accessing registry: {e}")
        if DEBUG_BUILD:
            import traceback
            logging.debug(f"访问注册表异常详情: {traceback.format_exc()}")
        raise e

    if DEBUG_BUILD:
        logging.debug(f"从Windows注册表读取GPU信息完成，共找到 {len(adapter_values)} 个适配器")
        
    return adapter_values
