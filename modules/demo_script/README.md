# 3 分钟演示脚本

## 职责

把顾客已提供的任务、场景和顾虑整理成五段式顾客演示话术：开场、需求确认、产品演示、异议处理、收口。总时长为 180 秒，生成内容是可编辑草稿，不是营销文案，也不是评委操作说明。

## 文件与入口

- `demo_script_module.py`
  - `generate_demo_script(payload, knowledge_base_dir=None)`：生成结构化脚本。
  - `format_demo_script(script)`：渲染为便于复制的纯文本。

## 输入与输出

输入包括产品型号、顾客角色、场景、顾客任务、顾虑、必需软件和外设。产品演示部分只引用公开知识库 `P1-产品参数库` 中匹配到的产品事实，附知识库相对路径和行号。未匹配到产品或事实时，结果会标记 `needs_product` 或 `limited_evidence`，并提示停止参数宣讲、先核验资料。

脚本不会推断软件/外设兼容性、实时价格、库存、促销或顾客体验。异议处理只提供待核验的安全回应，不构成购买建议或成交效果承诺。

## 验证

对应单元、工作流和 HTTP 接口测试位于 `tests/test_demo_script.py`、`tests/test_workflow.py` 和 `tests/test_mvp.py`。运行全部测试：

```bash
py -3 -m unittest discover -s tests -v
```
