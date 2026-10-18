# 依据与合规模块

## 文件

| 文件 | 作用 |
|---|---|
| `block07_compliance.py` | 汇总事实和图片来源，检查绝对化用语、价格促销、无依据比较、虚构体验、贬低竞品和虚假承诺 |
| `__init__.py` | 声明 Python 包 |

## 主要入口

```python
from modules.compliance.block07_compliance import build_evidence_section
```

输出包含已引用来源、检测到的风险和待人工确认项。检查通过不等于法律合规或可以直接发布。
