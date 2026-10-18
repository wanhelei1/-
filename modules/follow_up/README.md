# 成交跟进模块

## 文件

| 文件 | 作用 |
|---|---|
| `follow_up_module.py` | 创建今天、第 1 天、第 3 天、第 7 天四节点匿名跟进计划，并校验状态更新 |
| `__init__.py` | 声明 Python 包 |

## 主要入口

```python
from modules.follow_up.follow_up_module import (
    create_plan,
    update_task,
    update_plan_status,
)
```

计划只使用线索代号，不保存姓名和电话。浏览器端数据由前端存放在当前设备 `localStorage`；模块本身提供离线规则和 JSON 持久化辅助函数。
