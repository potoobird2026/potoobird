with open('src/loop/agent_loop.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()
for i, line in enumerate(lines, 1):
    if 'background' in line.lower() or 'subagent' in line.lower():
        print(f'{i}: {line.rstrip()}')
