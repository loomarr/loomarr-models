from __future__ import annotations

import argparse
import json
from pathlib import Path

from .validator import ValidationError, load_contract, load_denylist, load_jsonl, validate_corpus


def main() -> None:
    parser = argparse.ArgumentParser(prog="loomarr-corpus")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("path", type=Path)
    validate.add_argument("--allow-pending", action="store_true")
    validate.add_argument(
        "--denylist",
        type=Path,
        default=Path("contracts/holdout-denylist-v1.json"),
    )
    validate.add_argument(
        "--contract",
        type=Path,
        default=Path("contracts/planner-contract-v3.json"),
    )
    args = parser.parse_args()

    identities, digests = load_denylist(args.denylist)
    contract = load_contract(args.contract)
    try:
        report = validate_corpus(
            load_jsonl(args.path),
            denylisted_identities=identities,
            denylisted_sha256=digests,
            contract_bundle=contract,
            allow_pending=args.allow_pending,
        )
    except ValidationError as exc:
        parser.error(str(exc))
    print(json.dumps(report.__dict__, sort_keys=True))


if __name__ == "__main__":
    main()
