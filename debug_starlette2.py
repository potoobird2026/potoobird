import starlette.templating
import inspect
src = inspect.getsource(starlette.templating)
# 找 TemplateResponse 方法
lines = src.split('\n')
in_template_response = False
for i, line in enumerate(lines):
    if 'def TemplateResponse' in line:
        in_template_response = True
    if in_template_response:
        print(f"{i}: {line}")
        if line.strip().startswith('def ') and 'TemplateResponse' not in line:
            break
    if in_template_response and i > 200:
        break
