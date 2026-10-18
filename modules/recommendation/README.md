# 推荐与检索模块

## 文件

| 文件 | 作用 |
|---|---|
| `recommendation_engine.py` | 根据检索结果识别产品、评估硬条件并输出推荐候选 |
| `retrieval_adapter.py` | 统一 Mock 检索和未来真实检索的响应契约 |
| `mock_retriever.py` | 从公开知识库精选片段中做确定性关键词检索 |
| `__init__.py` | 声明 Python 包 |

## 主要入口

```python
from modules.recommendation.recommendation_engine import generate_recommendation_plan
from modules.recommendation.retrieval_adapter import retrieve_with_adapter
```

默认 `RETRIEVER_MODE=mock`，不访问网络。真实检索模式只通过适配层接入，不改变上层接口。当前实现不宣称为生产级全库检索。
