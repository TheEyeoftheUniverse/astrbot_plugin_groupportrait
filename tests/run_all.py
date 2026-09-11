"""测试总入口:python3 tests/run_all.py(无第三方测试框架依赖)。"""
import asyncio
import importlib
import inspect
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helpers  # noqa: F401  先导入以注入 stub 路径

MODULES = ["test_binding", "test_composer", "test_runninghub_nodes",
           "test_pipeline_dryrun", "test_bind_flow", "test_plugin_smoke"]


def main():
    passed = failed = 0
    for mod_name in MODULES:
        mod = importlib.import_module(mod_name)
        for name in sorted(vars(mod)):
            if not name.startswith("test_"):
                continue
            fn = getattr(mod, name)
            if not callable(fn):
                continue
            try:
                if inspect.iscoroutinefunction(fn):
                    asyncio.run(fn())
                else:
                    fn()
                passed += 1
                print(f"PASS {mod_name}.{name}")
            except Exception:
                failed += 1
                print(f"FAIL {mod_name}.{name}")
                traceback.print_exc()
    print(f"\n== {passed} passed, {failed} failed ==")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
