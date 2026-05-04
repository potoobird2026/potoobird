"""代码审查脚本 — 检查标准对齐"""
import os, re, sys

def print_sep(title):
    print(f"\n=== {title} ===")

def check_hardcoded():
    print_sep("G-001: 硬编码检查")
    found = 0
    for root, dirs, files in os.walk('src'):
        if '__pycache__' in dirs: dirs.remove('__pycache__')
        for f in files:
            if not f.endswith('.py'): continue
            path = os.path.join(root, f)
            with open(path, encoding='utf-8', errors='ignore') as fp:
                content = fp.read()
            for m in re.finditer(r"(api_key|secret|token|password)\s*=\s*['\"][^'\"]{8,}['\"]", content, re.I):
                if 'settings' not in path.replace('\\','/'):
                    print(f"  ⚠️  可能的硬编码密钥: {path}")
                    found += 1
    if not found: print("  ✅ 无硬编码问题")

def check_empty_catch():
    print_sep("G-002: 空catch检查")
    found = 0
    for root, dirs, files in os.walk('src'):
        if '__pycache__' in dirs: dirs.remove('__pycache__')
        for f in files:
            if not f.endswith('.py'): continue
            path = os.path.join(root, f)
            with open(path, encoding='utf-8', errors='ignore') as fp:
                lines = fp.readlines()
            for i, line in enumerate(lines, 1):
                if line.strip() in ('except:', 'except Exception:'):
                    print(f"  ⚠️  空catch块: {path}:{i}")
                    found += 1
    if not found: print("  ✅ 无空catch块")

def check_print():
    print_sep("G-005: print语句检查")
    found = 0
    for root, dirs, files in os.walk('src'):
        if '__pycache__' in dirs: dirs.remove('__pycache__')
        for f in files:
            if not f.endswith('.py'): continue
            path = os.path.join(root, f)
            with open(path, encoding='utf-8', errors='ignore') as fp:
                lines = fp.readlines()
            for i, line in enumerate(lines, 1):
                if 'logger' in line: continue
                if 'print(' in line and '#' not in line.split('print(')[0]:
                    print(f"  ⚠️  print语句: {path}:{i}: {line.strip()[:80]}")
                    found += 1
    if not found: print("  ✅ 无print语句")

if __name__ == '__main__':
    os.chdir(r'D:\github\三家PK\qwenpaw\代码')
    check_hardcoded()
    check_empty_catch()
    check_print()
