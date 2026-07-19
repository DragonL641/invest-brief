"""验证 macro pipeline 把估值数据接进了各渲染环节（占位，T14 e2e dry-run 覆盖真实流程）。"""


def test_placeholder():
    # pipeline 集成测试依赖完整 config + provider，本占位由 T14 端到端 dry-run 覆盖。
    # 保留文件以记录 wiring 意图；T14 删除。
    assert True
