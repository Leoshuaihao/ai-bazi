"""修正子模块

包含各级修正的细化实现：
- level1_yongshen: Level 1 用神修正（透干会支/真假判别/救应检测）
- level5_dayun: Level 5 行运修正（成格/变格/破格/并存）
"""

# 延迟导入，避免循环依赖
# 使用 try/except ImportError 保证可选模块不破坏现有流程

# 从被 package 目录遮蔽的 correction.py 单文件模块中重新导出所有公开 API
# （correction/ 目录优先于 correction.py，因此需要通过文件路径显式加载）
import importlib.util
import os

_correction_py_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'correction.py')
_spec = importlib.util.spec_from_file_location("_services_correction_module", _correction_py_path)
_correction = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_correction)

# 重新导出所有公开符号
for _name in dir(_correction):
    if not _name.startswith('_'):
        globals()[_name] = getattr(_correction, _name)

# 清理命名空间
del _correction_py_path, _spec, _correction, _name, importlib, os
