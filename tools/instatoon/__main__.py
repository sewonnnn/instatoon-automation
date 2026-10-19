"""JSON CLI: python -m tools.instatoon COMMAND --request request.json."""
import argparse
import json
import sys
from .common import ToolError, Workspace, read_json
from . import render, state
from .migrate import migrate_project

COMMANDS = {name: getattr(state, name) for name in (
    "save_series", "save_revision", "load_project", "validate_episode", "record_approval", "export_episode")}
COMMANDS.update(migrate_project=migrate_project, render_panel=render.render_panel, build_preview=render.build_preview)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=sorted(COMMANDS))
    parser.add_argument("--root", default=".", help="Repository root; all artifact paths are relative to it")
    parser.add_argument("--request", required=True, help="JSON request path, or - for stdin")
    args = parser.parse_args()
    try:
        request = json.load(sys.stdin) if args.request == "-" else read_json(args.request)
        if not isinstance(request, dict):
            raise ToolError("invalid_input", "Request must be a JSON object")
        result = COMMANDS[args.command](Workspace(args.root), request)
        result = {"status": "ok", "artifacts": [], "warnings": [], "error": None, **result}
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except (ToolError, OSError, KeyError, ValueError, TypeError) as error:
        print(json.dumps({"status": "error", "artifacts": [], "warnings": [],
                          "error": {"code": getattr(error, "code", "invalid_input"),
                                    "message": str(error), "retryable": False}}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
