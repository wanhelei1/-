# 测试目录

## 文件

| 文件 | 覆盖范围 |
|---|---|
| `test_mvp.py` | HTTP 路由、初始化数据、咨询、营销、报价、知识问答和跟进接口 |
| `test_workflow.py` | 客户洞察、推荐、价格、营销和合规的跨模块串联 |
| `test_follow_up.py` | 四节点计划、状态校验和 JSON 持久化 |

运行全部测试：

```bash
py -3 -m unittest discover -s tests -v
```

测试从仓库根目录导入 `app` 和 `modules.*`，与实际启动方式保持一致。
