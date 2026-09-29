/**
 * 内嵌 TopoScript v2 样本（纯帧序列）。
 *
 * 单一来源：apps/web StoryHarness 与测试均 import 此处。
 * 帧 = 静态结构源文（mermaid/plantuml/dot 原文），帧间 = diff 过渡。
 */

export type TopoSampleName = 'bubble' | 'dot' | 'plantuml';

const bubble = `@version 2
@backend mermaid
@options step=1600

# 冒泡排序单趟：每帧是一份完整的 mermaid 源文。
# 键稳定示范：subgraph id 恒为 S（步骤计数只进标题文本 → 标题走 textCross，不整灭整生）；
# 边 V3~V5 方向键无关（f2/f3/f5 同一条边跨帧 morph 拉伸，不重建）。
@@frame f1
@@source
graph TD
  subgraph S["步骤 1 / 5 · 初始 [5] [3]"]
    V5["[5]"]
    V3["[3]"]
  end
@@/source

@@frame f2
@@source
graph TD
  subgraph S["步骤 2 / 5 · 建立比较连线"]
    V5["[5]"] --- V3["[3]"]
  end
@@/source

@@frame f3
@@source
graph TD
  subgraph S["步骤 3 / 5 · 逆序 → 交换位置（连线端点跟随拉伸）"]
    V3["[3]"] --- V5["[5]"]
  end
@@/source

@@frame f4
@@source
graph TD
  subgraph S["步骤 4 / 5 · 解除比较连线"]
    V3["[3]"]
    V5["[5]"]
  end
@@/source

@@frame f5
@@source
graph TD
  subgraph S["步骤 5 / 5 · 回到初始拓扑"]
    V5["[5]"] --- V3["[3]"]
  end
@@/source
`;

const dot = `@version 2
@backend dot
@options step=1800

# DOT：拓扑渐增（f1 起步即有两个可延续的键，增长叙事不触发低稳定度告警）
@@frame f1
@@source
digraph G {
  rankdir=LR;
  A [label="[A]"];
  B [label="[B]"];
  A -> B;
}
@@/source

@@frame f2
@@source
digraph G {
  rankdir=LR;
  A [label="[A]"];
  B [label="[B]"];
  C [label="[C]"];
  A -> B;
  B -> C;
}
@@/source

@@frame f3
@@source
digraph G {
  rankdir=LR;
  A [label="[A]"];
  B [label="[B]"];
  C [label="[C]"];
  D [label="[D]"];
  A -> B;
  B -> C;
  C -> D;
}
@@/source
`;

const plantuml = `@version 2
@backend plantuml
@options step=2000

# PlantUML 时序：登录消息链逐帧推进。
# 注意 participant 引用大小写一致（alice-> 小写别名会另开 lifeline）。
# 标准 jar 的时序图无元素身份键：消息累加使全图纵向重排，形状部件键随位置漂移（fp 指纹）→
# 帧间稳定性实测 ~0.4-0.6（⚠ 如实反映）；参与者名被绘制两遍（框顶/框底）→ keys/unique 恒 2 ⚠。
# 主项目定制 jar 注入 data-entity-uid 后身份稳定，无此特性。
@@frame f1
@@source
@startuml
participant Alice
participant Bob
Alice -> Bob : hello?
@enduml
@@/source

@@frame f2
@@source
@startuml
participant Alice
participant Bob
Alice -> Bob : hello?
Bob -> Alice : hi!
@enduml
@@/source

@@frame f3
@@source
@startuml
participant Alice
participant Bob
Alice -> Bob : hello?
Bob -> Alice : hi!
Alice -> Bob : login(id,pw)
@enduml
@@/source

@@frame f4
@@source
@startuml
participant Alice
participant Bob
Alice -> Bob : hello?
Bob -> Alice : hi!
Alice -> Bob : login(id,pw)
Bob -> Alice : OK(session)
@enduml
@@/source
`;

export const TOPO_SAMPLES: Record<TopoSampleName, string> = {
  bubble,
  dot,
  plantuml,
};
