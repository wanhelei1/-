# 业务模块总览

`modules/` 是后端业务实现区。模块按职责拆分，入口程序只负责 HTTP 路由和参数校验，跨模块业务流由 `workflow` 统一编排。

## 调用关系

```text
app.py
  ├─ workflow.store_growth_workflow
  │    ├─ customer_insight
  │    ├─ recommendation
  │    ├─ pricing
  │    ├─ marketing
  │    ├─ demo_script
  │    └─ compliance
  └─ follow_up
```

## 目录说明

| 目录 | 文件 | 责任 |
|---|---|---|
| `workflow/` | `store_growth_workflow.py` | 串联客户洞察、推荐、价格、营销、3 分钟演示脚本和合规 |
| `customer_insight/` | `kb_agent.py` | 将顾客显式输入整理为洞察卡 |
| `recommendation/` | `recommendation_engine.py`、`retrieval_adapter.py`、`mock_retriever.py` | 检索适配、候选推荐、硬条件评估 |
| `pricing/` | `pricing_module.py` | 官方公开价格快照和人工核验状态 |
| `marketing/` | `marketing_content_module.py` | 基于事实锚点生成营销草稿 |
| `demo_script/` | `demo_script_module.py` | 生成五段式、证据可追溯的顾客演示脚本草稿 |
| `follow_up/` | `follow_up_module.py` | 匿名四节点跟进计划和状态更新 |
| `compliance/` | `block07_compliance.py` | 内容风险和来源完整性检查 |

每个子目录都有自己的 README，打开对应目录即可查看文件级入口、输入输出和测试方式。模块只使用 Python 标准库，不依赖 API Key 或外部服务。
