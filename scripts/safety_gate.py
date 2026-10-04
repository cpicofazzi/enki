import sys
import json

# Enki PreToolUse Safety Gate Hook
# Reads stdin json payload, outputs decision
def main():
    try:
        raw = sys.stdin.read()
        if raw.strip():
            data = json.loads(raw)
            # Default allow
            result = {"decision": "allow"}
        else:
            result = {"decision": "allow"}
    except Exception:
        result = {"decision": "allow"}

    print(json.dumps(result))
    sys.exit(0)

if __name__ == "__main__":
    main()
