import json
import sys

print(json.dumps({"arguments": sys.argv[1:], "ok": True}))
