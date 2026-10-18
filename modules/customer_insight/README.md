# 客户洞察模块

## 文件

| 文件 | 作用 |
|---|---|
| `kb_agent.py` | 读取公开知识库，依据顾客显式输入生成客户身份、场景、需求、顾虑、触发点和待追问项 |
| `__init__.py` | 声明 Python 包 |

## 主要入口

```python
from modules.customer_insight.kb_agent import KnowledgeBase, build_insight
```

模块只记录顾客明确表达的信息；缺失字段保持为“待追问”，不把推测写成客户事实。知识库路径默认为仓库根目录下的 `knowledge-base/`。
