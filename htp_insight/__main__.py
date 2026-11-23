import argparse
import json

from .core import Core
from .interfaces import OPERATIONS, operations


def main():
    cli = argparse.ArgumentParser(description="HTP Insight local analysis")
    cli.add_argument("operation", choices=(*OPERATIONS, "catalog", "report", "profile"))
    cli.add_argument("arguments", nargs="?", default="{}", help="JSON keyword arguments")
    args = cli.parse_args()
    core = Core()
    method = {**operations(core), "catalog": core.catalog, "report": core.report, "profile": core.profile}[args.operation]
    result = method(**json.loads(args.arguments))
    print(result if isinstance(result, str) else json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
