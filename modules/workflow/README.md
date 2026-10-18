# 流程编排模块

## 文件

| 文件 | 作用 |
|---|---|
| `store_growth_workflow.py` | 将客户洞察、推荐、公开价格、营销草稿、3 分钟演示脚本和依据合规检查串成一个结构化结果 |
| `__init__.py` | 声明 Python 包 |

## 主要入口

```python
from modules.workflow.store_growth_workflow import (
    run_customer_insight,
    run_store_growth_workflow,
)
```

- `run_customer_insight(payload)`：只生成客户洞察卡。
- `run_store_growth_workflow(payload)`：运行完整证据优先流程。

流程不会把未知条件当成满足，也不会把价格快照当成当前成交价。对应集成测试位于 `tests/test_workflow.py`。
