"""批量修复 tests/ 目录的 ruff 错误"""
import os, subprocess

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# 1. 先运行 ruff --fix 自动修复
r = subprocess.run(
    ["E:\\QwenPaw\\python.exe", "-m", "ruff", "check", "src/", "tests/", "--fix"],
    capture_output=True, text=True
)
print("ruff --fix output:")
print(r.stdout[-1000:] if r.stdout else "(no stdout)")

# 2. 再检查剩余
r2 = subprocess.run(
    ["E:\\QwenPaw\\python.exe", "-m", "ruff", "check", "src/", "tests/"],
    capture_output=True, text=True
)
print(f"\n--- Remaining errors ---")
print(r2.stdout[-2000:] if r2.stdout else "(clean!)")
print(f"Exit code: {r2.returncode}")
