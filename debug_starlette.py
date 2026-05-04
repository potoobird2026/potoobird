import starlette.templating
import inspect
src = inspect.getsource(starlette.templating)
print(src[:3000])
