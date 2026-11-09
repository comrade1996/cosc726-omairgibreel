#!/usr/bin/env python3
"""Developer helper for driving the server from a generic MCP client (e.g. MCP Inspector).

    python scripts/dev_session.py env --crew CREW-A
        prints AMBULANCE_* variables (fresh keys + a session token) to paste into the client's env
    python scripts/dev_session.py approve --case AMB-001 --version 1 --draft <draft_sha256> --org ORG-ED-02
        acts as the clinician approval gate and prints a one-off approval token

Both commands need the same keys: export the printed AMBULANCE_SESSION_KEY / AMBULANCE_APPROVAL_KEY
in the shell where you run `approve`. Dev use only.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from project.dataset import crews  # noqa: E402
from project.security import issue_clinician_approval, issue_session_token, new_key  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("env")
    e.add_argument("--crew", default="CREW-A", choices=sorted(crews()))
    a = sub.add_parser("approve")
    a.add_argument("--case", required=True)
    a.add_argument("--version", type=int, required=True)
    a.add_argument("--draft", required=True, help="draft_sha256 returned by create_handoff_draft")
    a.add_argument("--org", required=True)
    a.add_argument("--clinician", default="ED-CLIN-DEV-01")
    args = ap.parse_args()
    if args.cmd == "env":
        s = bytes.fromhex(os.environ["AMBULANCE_SESSION_KEY"]) if os.environ.get("AMBULANCE_SESSION_KEY") else new_key()
        k = os.environ.get("AMBULANCE_APPROVAL_KEY") or new_key().hex()
        c = crews()[args.crew]
        print(f"AMBULANCE_SESSION_KEY={s.hex()}\nAMBULANCE_APPROVAL_KEY={k}\n"
              f"AMBULANCE_SESSION_TOKEN={issue_session_token(s, args.crew, c['tenant'], c['cases'])}")
    else:
        key = bytes.fromhex(os.environ["AMBULANCE_APPROVAL_KEY"])
        print(issue_clinician_approval(key, case_id=args.case, case_version=args.version, draft_sha256=args.draft,
                                       receiving_org=args.org, clinician_id=args.clinician))


if __name__ == "__main__":
    main()
