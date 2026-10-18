# 营销内容模块

## 文件

| 文件 | 作用 |
|---|---|
| `marketing_content_module.py` | 根据产品事实、平台模板、受众沟通卡和图片索引生成营销草稿 |
| `__init__.py` | 声明 Python 包 |

## 主要入口

```python
from modules.marketing.marketing_content_module import generate_marketing_content
```

生成结果包含标题、正文、行动引导、事实来源、推荐图片和警告。模块不编造客户案例、价格、库存、性能承诺或图片权利；发布前仍需人工审核。
