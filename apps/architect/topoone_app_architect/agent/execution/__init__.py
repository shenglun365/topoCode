"""执行层 — architect ↔ runner 作业桥接内核。

pumps.py        单一事件泵(WS 实时订阅优先 + snapshot 轮询校准兜底)
runner_client.py 类型化 runner 访问端(JobEvent schema 消费)
"""
