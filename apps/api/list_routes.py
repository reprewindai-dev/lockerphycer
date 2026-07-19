import importlib, json, os, sys
# Ensure project root is in sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.append(project_root)
app = importlib.import_module('apps.api.main').app
routes = []
for r in app.routes:
    methods = list(getattr(r, 'methods', []))
    routes.append({"path": r.path, "methods": methods})
print(json.dumps(routes, indent=2))
