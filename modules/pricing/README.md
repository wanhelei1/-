# 价格核验模块

## 文件

| 文件 | 作用 |
|---|---|
| `pricing_module.py` | 读取 `P1-产品参数库/08-官方公开价格快照/官方价格快照.csv`，输出价格、口径、日期、来源和人工核验项 |
| `__init__.py` | 声明 Python 包 |

## 主要入口

```python
from modules.pricing.pricing_module import build_quote_status
```

模块只展示带核验日期的官方公开快照，不计算门店折扣、补贴、库存、地区价或当前成交价。测试位于 `tests/test_mvp.py` 和 `tests/test_workflow.py`。
