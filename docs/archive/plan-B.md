# 需求+架构驱动的 SE Agent 系统设计

---

## 一、 设计哲学

> **核心命题：** Coding Agent 最大的失败模式不是"写不出代码"，而是 **"在错误的抽象层级、用错误的本体类型、忽略治理约束"地写代码。**

本系统的本质是：**将 XYZ 元认知框架编译为 Agent 可执行的约束协议**，使 Coding Agent 从"自由生成"转变为"约束求解"。

---

## 二、 整体架构：四阶流水线

```
┌─────────────────────────────────────────────────────────────────────┐
│                        SE Agent 总控（Orchestrator）                  │
├─────────┬──────────────┬──────────────────┬─────────────────────────┤
│ Phase 1 │   Phase 2    │     Phase 3      │       Phase 4           │
│ 需求解析 │  架构决策     │   编码执行        │     验证收敛            │
│ (Analyst)│ (Architect)  │  (Coder Agent)   │    (Verifier)           │
├─────────┼──────────────┼──────────────────┼─────────────────────────┤
│ 输入：   │ 输入：       │ 输入：           │ 输入：                  │
│ 自然语言 │ 需求结构化   │ 架构契约包       │ 代码 + 架构契约包       │
│ 需求     │ 产物        │                  │                         │
│         │              │                  │                         │
│ 输出：   │ 输出：       │ 输出：           │ 输出：                  │
│ 结构化   │ 架构契约包   │ 代码 + 映射表    │ 合规报告 / 修复指令     │
│ 需求卡   │ (Contract)  │                  │                         │
└─────────┴──────────────┴──────────────────┴─────────────────────────┘
```

---

## 三、 Phase 1：需求解析 Agent（Analyst）

### 3.1 职责
将自然语言需求转化为 **XYZ 坐标系下的结构化需求卡**。

### 3.2 输出格式：需求卡（Requirement Card）

```yaml
requirement_card:
  id: "REQ-2026-0829-001"
  title: "订单取消后自动退款"
  
  # X轴定位：涉及哪些本体类型
  x_axis_mapping:
    entities: ["Order", "Refund", "PaymentRecord"]
    interactions: ["OrderService → PaymentGateway.cancel()"]
    events: ["OrderCancelledEvent"]
    rules: ["取消窗口≤30min", "已发货订单禁止取消"]
    processes: ["取消审批流 → 退款执行流"]
    decisions: ["是否全额退款（基于已使用优惠券）"]
  
  # Y轴定位：影响哪些视图层
  y_axis_mapping:
    business_view: "用户取消订单的业务流程变更"
    application_view: "OrderService新增cancel方法，PaymentService新增refund接口"
    infrastructure_view: "需新增MQ Topic: order.cancelled"
  
  # Z轴定位：触发哪些治理约束
  z_axis_mapping:
    observability: "取消操作需记录审计日志，退款耗时需P99<2s"
    resilience: "支付网关超时3s，重试2次，失败进入人工队列"
    config: "取消窗口时长可配置（当前30min）"
    security: "仅订单所有者可触发取消，退款金额需二次校验"
  
  # 档位判定
  tier: "mid"  # 触发中配版规则
  
  # 验收标准
  acceptance_criteria:
    - "Given 未发货订单, When 用户在30min内取消, Then 全额退款且状态→CANCELLED"
    - "Given 已发货订单, When 用户取消, Then 返回403+提示"
```

### 3.3 关键规则
- **强制完整性检查：** 若 X 轴 6 类中有未覆盖项，必须显式标注 `N/A` 并给出理由。
- **档位自动判定：** 依据升档检查单（团队规模、部署形态、异步依赖等）自动推荐低/中/高配。

---

## 四、 Phase 2：架构决策 Agent（Architect）

### 4.1 职责
将需求卡转化为 **架构契约包（Architecture Contract Package）**——这是 Coding Agent 的"施工图纸"。

### 4.2 架构契约包结构

```
📦 architecture-contract/
├── 📄 contract.yaml              # 总控契约（版本号、档位、全局约束）
├── 📁 x-axis/                    # 本体定义
│   ├── entities/
│   │   ├── Order.yaml            # 实体定义（字段、状态机、不变量）
│   │   └── Refund.yaml
│   ├── interactions/
│   │   └── OrderService_PaymentGateway.yaml  # 接口契约（入参、出参、异常）
│   ├── events/
│   │   └── OrderCancelledEvent.yaml          # Topic、Schema、幂等策略
│   ├── rules/
│   │   └── CancelWindowRule.yaml             # 规则表达式 + 测试用例
│   ├── processes/
│   │   └── CancelRefundFlow.yaml             # 流程编排（BPMN/伪代码）
│   └── decisions/
│       └── RefundAmountDecision.yaml         # 决策表/决策树
├── 📁 y-axis/                    # 分层视图
│   ├── business/
│   │   └── context-diagram.md    # 业务上下文图
│   ├── application/
│   │   ├── component-diagram.md  # 组件图（服务/模块边界）
│   │   └── sequence-diagram.md   # 关键交互时序
│   └── infrastructure/
│       ├── deployment-diagram.md # 部署拓扑
│       └── middleware.yaml       # 中间件选型与版本
├── 📁 z-axis/                    # 治理策略
│   ├── observability.yaml        # 埋点规范、日志格式、Metrics定义
│   ├── resilience.yaml           # 超时/重试/熔断/降级策略
│   ├── config.yaml               # 配置项清单、默认值、刷新策略
│   └── security.yaml             # 鉴权模型、数据分级、脱敏规则
└── 📁 coding-directives/         # 🔑 给Coding Agent的编码指令
    ├── file-structure.md         # 目标文件/包结构
    ├── naming-convention.md      # 命名规范
    ├── pattern-selection.md      # 设计模式选型（策略/状态机/观察者等）
    ├── anti-patterns.md          # 禁止事项清单
    └── test-strategy.md          # 测试分层与覆盖率要求
```

### 4.3 契约包中的编码指令示例（coding-directives/file-structure.md）

```markdown
## 目标文件结构（中配版·应用视图）

```
order-service/
├── src/main/java/com/xxx/order/
│   ├── domain/                          # X轴·实体+规则（纯业务，无框架依赖）
│   │   ├── model/
│   │   │   ├── Order.java               # 实体（含状态枚举+状态流转方法）
│   │   │   └── OrderStatus.java         # 状态机定义
│   │   ├── event/
│   │   │   └── OrderCancelledEvent.java # X轴·事件
│   │   ├── rule/
│   │   │   └── CancelWindowRule.java    # X轴·规则
│   │   └── decision/
│   │       └── RefundAmountDecision.java# X轴·决策
│   ├── application/                     # X轴·过程（编排层）
│   │   ├── CancelOrderUseCase.java
│   │   └── dto/
│   ├── infrastructure/                  # Y轴·基础设施适配
│   │   ├── gateway/
│   │   │   └── PaymentGatewayImpl.java  # X轴·交互（防腐层）
│   │   ├── mq/
│   │   │   └── OrderCancelledPublisher.java
│   │   └── repository/
│   │       └── OrderRepositoryImpl.java
│   └── interfaces/                      # Y轴·应用视图入口
│       ├── rest/
│       │   └── OrderController.java
│       └── mq/
│           └── OrderCancelledListener.java
```

## 映射关系（X轴 → 包路径）
| X轴类型 | 包路径 | 命名后缀 |
|---------|--------|----------|
| 实体 | `domain/model/` | `Entity` / 无 |
| 交互 | `infrastructure/gateway/` | `Gateway` / `Client` |
| 事件 | `domain/event/` | `Event` |
| 规则 | `domain/rule/` | `Rule` |
| 过程 | `application/` | `UseCase` / `Service` |
| 决策 | `domain/decision/` | `Decision` |
```

### 4.4 档位对契约包的影响

| 契约包内容 | 低配 | 中配 | 高配 |
|:---|:---|:---|:---|
| X轴·事件定义 | ❌ 不生成 | ✅ Topic+Schema | ✅ Schema Registry注册+兼容性校验 |
| Y轴·基础设施图 | 合并入技术视图 | 独立部署图 | 多机房+单元化拓扑 |
| Z轴·可观测 | 注释级备注 | 独立YAML+埋点代码 | OpenTelemetry SDK集成+告警规则 |
| Z轴·韧性 | try-catch模板 | 框架注解(@Retryable) | 混沌实验用例+自动降级脚本 |
| coding-directives | 简化（1页） | 完整（5-8页） | 完整+自动生成脚手架 |

---

## 五、 Phase 3：编码执行 Agent（Coder）

### 5.1 核心机制：契约注入式编码

Coding Agent **不是**自由生成代码，而是在契约包约束下**求解**。

```
┌──────────────────────────────────────────────┐
│            Coding Agent 工作循环              │
│                                              │
│  1. 读取 contract.yaml → 确定档位与全局约束   │
│  2. 读取 coding-directives/ → 确定文件骨架   │
│  3. 逐文件生成：                             │
│     ├── 读取对应 X轴定义（实体字段/接口签名） │
│     ├── 读取对应 Z轴约束（超时/日志/权限）    │
│     ├── 生成代码                            │
│     └── 自检：是否违反 anti-patterns.md      │
│  4. 生成测试代码（按 test-strategy.md）      │
│  5. 输出 映射表（代码文件 ↔ 契约条目）       │
│                                              │
└──────────────────────────────────────────────┘
```

### 5.2 Prompt 协议（System Prompt 骨架）

```markdown
# Role
你是一个受架构契约约束的编码Agent。你的任务不是"创造性编程"，
而是将架构契约包精确翻译为可运行代码。

# 约束协议
1. 【本体约束】每个类/方法必须对应X轴中的一个明确类型。
   若无法归类，停下来向Architect Agent提问，不得自行发明。
2. 【分层约束】严格遵守Y轴包结构。
   - domain/ 禁止引入Spring/MyBatis等框架注解
   - infrastructure/ 禁止包含业务规则判断
   - application/ 禁止直接操作数据库
3. 【治理约束】每个方法必须满足Z轴要求：
   - 可观测：按observability.yaml添加日志/指标
   - 韧性：按resilience.yaml添加超时/重试
   - 配置：可变参数必须读取配置，禁止硬编码
   - 安全：按security.yaml添加权限校验
4. 【档位约束】当前档位为 {tier}，
   禁止引入超出该档位的复杂度（如低配禁止引入MQ）。

# 输入
- 架构契约包：{contract_package_content}
- 当前任务：实现 {target_file}

# 输出格式
- 代码文件（含完整import）
- 映射声明：`// CONTRACT: x-axis/entities/Order.yaml#L12-L30`
- 自检报告：逐条对照anti-patterns.md
```

### 5.3 多 Agent 并行编码策略（中/高配）

```
Architect Agent 输出契约包
        │
        ├──→ Coder Agent A：domain/ 层（实体+规则+决策）
        ├──→ Coder Agent B：application/ 层（过程编排）
        ├──→ Coder Agent C：infrastructure/ 层（交互+事件）
        └──→ Coder Agent D：interfaces/ 层 + 测试
              │
              ▼
        Integrator Agent：合并 + 冲突检测 + 契约一致性校验
```

---

## 六、 Phase 4：验证收敛 Agent（Verifier）

### 6.1 三层验证

| 验证层 | 检查内容 | 工具 |
|:---|:---|:---|
| **契约合规性** | 代码是否覆盖契约包所有条目；是否有契约外的"野代码" | AST解析 + 契约映射表比对 |
| **架构一致性** | 分层依赖是否违规；X轴类型是否放错包 | ArchUnit / 自定义Lint规则 |
| **Z轴达标性** | 超时是否配置；日志是否打印；权限是否校验 | 静态扫描 + 运行时断言 |

### 6.2 不合规处理

```
Verifier 发现问题
    │
    ├── 轻微（命名不规范、缺少注释）→ 自动修复 → 重新提交
    ├── 中等（分层违规、缺少重试）→ 生成修复指令 → Coder Agent 重做
    └── 严重（契约缺失、架构冲突）→ 回退至 Architect Agent 重新决策
```

---

## 七、 认知对齐机制：共享词汇表

### 7.1 为什么需要
Coding Agent（如Cursor/Copilot）的默认"认知"是通用编程知识。必须通过**共享词汇表**将其锚定到本框架。

### 7.2 词汇表注入（.cursorrules / AGENTS.md）

```markdown
# 项目认知协议（本项目所有AI Agent必须遵守）

## 术语映射
- 当我说"实体"，指X轴·实体，对应 `domain/model/` 包
- 当我说"交互"，指X轴·交互（跨边界调用），对应 `infrastructure/gateway/`
- 当我说"规则"，指X轴·规则（纯业务判断），对应 `domain/rule/`
- 当我说"过程"，指X轴·过程（用例编排），对应 `application/`
- 禁止将"规则"写在Controller中
- 禁止在domain层引入HTTP/RPC概念

## 当前档位
- 档位：中配
- Z轴工具栈：Prometheus + Resilience4j + Nacos + Spring Security

## 编码铁律
1. 每个public方法第一行必须是日志（可观测性）
2. 外部调用必须包裹超时+重试（韧性）
3. 魔法数字必须提取为配置项（可变配置）
4. 入参必须校验权限（安全）
```

---

## 八、 工具链集成方案

```
┌─────────────────────────────────────────────────────────────┐
│                      用户界面层                               │
│  需求输入（自然语言/PRD） → 可视化契约包查看 → 代码Review     │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                    SE Agent 编排层                            │
│  Orchestrator（LangGraph / CrewAI / AutoGen）               │
│  ├── Analyst Agent（LLM + RAG on 需求库）                   │
│  ├── Architect Agent（LLM + 架构模式库 + 契约模板）         │
│  ├── Coder Agent × N（对接 ↓）                              │
│  └── Verifier Agent（静态分析 + LLM Review）                │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                   Coding Agent 执行层                         │
│  选项A：Cursor / Windsurf（IDE内，契约作为@file注入）       │
│  选项B：Devin / OpenHands（自主执行，契约作为System Prompt）│
│  选项C：Claude Code / Aider（CLI，契约作为AGENTS.md）       │
│  选项D：自研（基于AST+LSP，精确到函数级生成）               │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                    工程基础设施层                              │
│  Git（契约包+代码同仓） → CI（契约合规检查） → CD（部署）   │
└─────────────────────────────────────────────────────────────┘
```

---

## 九、 端到端示例（中配版）

> **用户输入：** "实现订单取消后自动退款功能，取消窗口30分钟，已发货不可取消"

| 阶段 | Agent | 产出 | 耗时（预估） |
|:---|:---|:---|:---|
| 1 | Analyst | 需求卡（XYZ映射 + 验收标准） | 30s |
| 2 | Architect | 契约包（6个X轴文件 + 3个Y轴图 + 4个Z轴策略 + 编码指令） | 2min |
| 3a | Coder A | `Order.java` + `OrderStatus.java` + `CancelWindowRule.java` + `RefundAmountDecision.java` | 1min |
| 3b | Coder B | `CancelOrderUseCase.java` | 45s |
| 3c | Coder C | `PaymentGatewayImpl.java` + `OrderCancelledPublisher.java` | 1min |
| 3d | Coder D | `OrderController.java` + 单元测试 | 1min |
| 4 | Verifier | 合规报告（通过/修复指令） | 30s |
| **总计** | | **可运行代码 + 测试 + 架构文档** | **~6min** |

---

## 十、 设计原则总结

| 原则 | 体现 |
|:---|:---|
| **契约先于代码** | Coding Agent 永远在契约包约束下工作，不自由发挥 |
| **认知即协议** | XYZ框架不是文档，是注入Agent的System Prompt和Lint规则 |
| **档位即约束** | 低配不生成MQ代码，高配不允许硬编码配置 |
| **可追溯** | 每行代码通过注释映射回契约条目，支持变更影响分析 |
| **渐进式** | 允许从低配起步，升档时契约包自动扩展，代码渐进重构 |

---

**最终交付物：** 不是一个单体工具，而是一套 **"认知协议 + 编排引擎 + 执行适配器"** 的三层架构。认知协议（XYZ框架+契约包格式）是稳定的；编排引擎可替换（LangGraph/CrewAI/自研）；执行适配器可对接任何主流Coding Agent。