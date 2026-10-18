# 门店增长工作台 · 华为 PC 门店销售智能助手

> **先看这里：** 这是一个纯 Python 标准库实现的、证据优先的门店顾客接待工作台。打开本 README 可以先看完整流程图，再从根目录的 `app.py` 启动程序，最后按 `modules/` 中的业务模块阅读实现。

## 30 秒了解项目

- **解决什么问题：** 把门店顾客接待中的需求确认、产品推荐、公开价格核验、营销草稿、成交跟进和依据合规检查组织成一条可追溯流程。
- **怎么运行：** 不需要 API Key，不需要第三方 Python 包，不需要联网；使用随包分发的公开知识库和确定性规则即可运行。
- **当前边界：** 六个业务环节已有对应功能；“按客户洞察自动生成个性化 3 分钟演示脚本”仍是 P1 规划项。
- **提交入口：** GitHub 当前地址为 `https://github.com/wanhelei1/-`；ModelScope 尚未配置已验证的公开地址。

## 先看程序流程

下面的拓扑图展示从浏览器进入 `app.py` 后，如何经过统一流程编排层调用各业务模块，最后回到可审阅的结果。所有需要引用的产品事实、价格和图片来源都来自公开知识库子集；未知项会转为待追问或人工核验。

```mermaid
flowchart TD
    UI["index.html\n顾客接待工作台"] --> APP["app.py\nHTTP 入口与接口路由"]
    APP --> QUICK["轻量接口\n咨询 / 报价 / 营销 / 问答 / 跟进"]
    APP --> FLOW["modules/workflow\n七步流程编排"]

    FLOW --> INSIGHT["01 customer_insight\n客户洞察卡"]
    FLOW --> RECOMMEND["02 recommendation\n推荐与本地检索适配"]
    FLOW --> PRICE["03 pricing\n公开价格快照核验"]
    FLOW --> MARKETING["04 marketing\n证据优先营销草稿"]
    FLOW --> COMPLIANCE["07 compliance\n依据与风险检查"]
    APP --> FOLLOWUP["06 follow_up\n匿名四节点成交跟进"]

    INSIGHT --> KB[("knowledge-base\n公开知识库子集")]
    RECOMMEND --> KB
    PRICE --> KB
    MARKETING --> KB
    FLOW --> RESULT["结构化结果\n来源 / 风险 / 待人工确认"]
    COMPLIANCE --> RESULT
    FOLLOWUP --> RESULT
    QUICK --> RESULT
    RESULT --> UI

    DEMO["05 演示脚本\n当前为规划项"] -. "P1" .-> FLOW
```

### 七步业务流程

| 步骤 | 输出 | 当前状态 | 主要实现目录 |
|---|---|---|---|
| 01 客户洞察卡 | 客户身份、场景、需求、顾虑、触发点、沟通策略、依据 | 已实现 | `modules/customer_insight/` |
| 02 推荐方案 | 产品、推荐理由、关键事实、适配程度、来源 | 已实现 | `modules/recommendation/` |
| 03 价格与报价状态 | 配置、公开价格、价格口径、基准日期、来源、待核验项 | 已实现 | `modules/pricing/` |
| 04 营销内容 | 平台、策略、标题、正文、行动引导、图片来源 | 已实现 | `modules/marketing/` |
| 05 3 分钟演示脚本 | 开场、需求确认、产品演示、异议处理、收口 | 规划中 | 知识库方法论可检索，自动个性化生成尚未实现 |
| 06 成交跟进 | 今天、第 1 天、第 3 天、第 7 天 | 已实现 | `modules/follow_up/` |
| 07 依据与合规 | 引用来源、风险、待人工确认项 | 已实现 | `modules/compliance/` |

## 快速运行

### 环境要求

- Python **3.10+**
- 只使用 Python 标准库
- 无需 `pip install`，无需 API Key

### 本地启动

```bash
# Windows
py -3 app.py

# macOS / Linux
python3 app.py
```

浏览器打开 <http://127.0.0.1:7860>。托管环境使用：

```bash
python3 app.py --host 0.0.0.0 --port 7860
```

### Docker 启动

```bash
docker build -t store-growth-workbench .
docker run --rm -p 7860:7860 store-growth-workbench
```

### 自动化测试

```bash
py -3 -m unittest discover -s tests -v
```

## 评委演示路径

1. 启动程序，进入「顾客接待」。
2. 选择「门店零售」，点击示例输入。
3. 点击「生成接待方案与价格核验」。
4. 重点查看客户洞察、推荐依据、价格核验日期、营销草稿和合规待确认项。
5. 再进入「知识问答」和「成交跟进」，查看本地检索来源与匿名四节点计划。

## 接口入口

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/health` | 服务健康检查 |
| GET | `/api/bootstrap` | 前端初始化数据 |
| POST | `/api/insight` | 生成客户洞察卡 |
| POST | `/api/workflow` | 串联洞察、推荐、价格、营销和合规 |
| POST | `/api/consult` | 轻量顾客接待结果 |
| POST | `/api/knowledge-query` | 本地知识片段检索 |
| POST | `/api/quote` | 公开价格快照与核验状态 |
| POST | `/api/marketing` | 生成营销内容草稿 |
| POST | `/api/followups/plan` | 创建四节点跟进计划 |
| POST | `/api/followups/task` | 更新单个跟进节点 |
| POST | `/api/followups/status` | 更新计划状态 |

## 仓库阅读顺序

根目录按“先运行、再理解、后深入”的顺序组织：

```text
.
├── README.md                  # 第一入口：流程图、运行、结构和边界
├── app.py                    # 主程序：HTTP 服务、接口路由、静态页面服务
├── index.html                # 前端工作台
├── Dockerfile                # ModelScope / Docker 启动配置
├── prepare_public_deploy.py  # 生成排除受限资料的公开部署包
├── modules/                  # 按业务职责拆分的 Python 模块
│   ├── README.md             # 模块总览和调用关系
│   ├── workflow/             # 流程编排层
│   ├── customer_insight/     # 01 客户洞察
│   ├── recommendation/       # 02 推荐与检索适配
│   ├── pricing/              # 03 价格快照核验
│   ├── marketing/            # 04 营销草稿
│   ├── follow_up/            # 06 成交跟进
│   └── compliance/           # 07 依据与合规
├── tests/                    # 自动化测试和测试说明
├── docs/                     # 需求、系统设计、演示与测试文档
└── knowledge-base/           # 公开知识库子集及其说明
```

每个模块目录都包含自己的 `README.md`，说明职责、文件、入口函数、输入输出和验证方式。建议按以下顺序阅读：

1. [modules/workflow/](modules/workflow/)：先看跨模块如何串联。
2. [modules/customer_insight/](modules/customer_insight/) 和 [modules/recommendation/](modules/recommendation/)：理解客户需求与推荐依据如何形成。
3. [modules/pricing/](modules/pricing/)、[modules/marketing/](modules/marketing/) 和 [modules/compliance/](modules/compliance/)：理解价格、内容和合规边界。
4. [modules/follow_up/](modules/follow_up/)：查看匿名跟进计划的数据结构和状态流转。
5. [tests/](tests/)：用测试确认接口和跨模块契约。

## 模块职责

| 目录 | 核心文件 | 作用 |
|---|---|---|
| `modules/workflow/` | `store_growth_workflow.py` | 统一装配洞察、推荐、价格、营销和合规结果 |
| `modules/customer_insight/` | `kb_agent.py` | 从显式顾客输入生成洞察卡和待追问项 |
| `modules/recommendation/` | `recommendation_engine.py`、`retrieval_adapter.py`、`mock_retriever.py` | 本地 Mock 检索、推荐候选和硬条件评估 |
| `modules/pricing/` | `pricing_module.py` | 读取官方公开价格快照，区分金额、日期和人工核验项 |
| `modules/marketing/` | `marketing_content_module.py` | 依据 P2/P6 素材生成可审阅营销草稿 |
| `modules/follow_up/` | `follow_up_module.py` | 生成今天、第 1 天、第 3 天、第 7 天匿名跟进计划 |
| `modules/compliance/` | `block07_compliance.py` | 检查绝对化、价格促销、无依据比较、虚构体验等风险 |

## 证据与数据边界

- 推荐结论必须能回到知识库事实；未知或冲突不会自动判定为满足。
- 价格只展示带核验日期的官方公开快照，不代表当前库存、促销、地区价或成交价。
- 软件和外设兼容性不从硬件参数推断，必须按目标版本和现场环境核验。
- 营销内容是草稿；合规检查通过不等于可以直接发布，仍需人工审核。
- 本地知识问答是明确标注的 Mock 精选检索，不是生产级全库搜索，也未接入外部 LLM。
- 公开包不包含 P4 价格政策、待审核资料、历史归档和来源研究底稿。

## ModelScope Docker 部署

本仓库可以直接作为 Docker 创空间代码来源。创建空间后：

1. 选择 Docker 运行方式并使用 `master` 分支。
2. 确认容器监听 `0.0.0.0:7860`。
3. 将空间设为公开。
4. 使用无痕窗口访问真实空间地址，并完整走一遍上面的演示路径。
5. 在最终提交表和 README 中填写真实 ModelScope 地址。

当前仓库**没有配置已验证的公开 ModelScope 地址**，不要把 `https://modelscope.cn/studios/<用户名>/<空间名>` 当成可访问链接。

从完整开发目录重新生成公开部署包时：

```powershell
py -3 prepare_public_deploy.py --output dist/public-deploy
```

脚本会自动排除受限知识库目录，并生成 `bundle-manifest.json`。

## 已知局限与下一步

1. 本地检索使用确定性关键词排序和精选片段，下一步可扩展全库索引与相关性调优。
2. 价格模块不接入动态促销、库存、补贴或授权折扣。
3. 3 分钟演示脚本的个性化自动生成列为 P1，当前仅保留知识库方法论和话术片段。
4. 未使用真实门店成交或转化样本，不声明销售提升、ROI 或客户案例效果。

## 团队

浙客松·AI+X 破界黑客松 · 华为产业落地赛道

| 角色 | 成员 | 职责 |
|---|---|---|
| 1号 · 组长 | 雷秉谕 | 需求拆解 / 规格文档 / 验收 / 答辩 |
| 2号 · 开发 | 姜宇翔 | 核心程序 / 接口 |
| 3号 · 界面与部署 | 程塨 | 工作台界面 / 魔搭部署 |
| 4号 · 测试与仓库 | 巩志栋 | 测试用例 / 文档 / 提交 |

## 许可证

见 [LICENSE](LICENSE)。
