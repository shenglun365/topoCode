from typing import Any

from ..ingredient import ContextIngredient


class TestCoverageIngredient(ContextIngredient):
    name = "test_coverage"

    def collect(self, ctx) -> dict:
        total = len(ctx.all_fp_map) if ctx.all_fp_map else 0
        test_cnt = sum(
            1 for fp in ctx.all_fp_map
            if '/test/' in fp or '/tests/' in fp
            or fp.endswith('_test.go') or fp.endswith('.spec.ts')
            or fp.endswith('.test.ts') or fp.endswith('.test.js')
        )
        return {"total": total, "test": test_cnt}

    def format(self, data: dict) -> str:
        total = data.get("total", 0)
        test = data.get("test", 0)
        if total == 0:
            return ""
        ratio = test / total
        return f"## 测试覆盖\n总文件 {total}, 测试文件 {test} ({ratio:.1%})"
