"""
CLI for the metric catalog approval workflow.

Usage:
    python -m catalog.cli list-pending
    python -m catalog.cli list-proposals
    python -m catalog.cli list-versions
    python -m catalog.cli approve <proposal_id> --by <user> [--note "..."]
    python -m catalog.cli reject <proposal_id> --by <user> --reason "..."
"""

from __future__ import annotations

import argparse
import sys

from .service import CatalogService


def _print_proposal(p) -> None:
    print(f"  id:          {p.proposal_id}")
    print(f"  status:      {p.status}")
    print(f"  proposed_by: {p.proposed_by}")
    print(f"  question:    {p.question}")
    print(f"  reason:      {p.reason}")
    print(f"  metric:      {p.metric.name} ({p.metric.agg} of {p.metric.column})")
    if p.metric.groupby:
        print(f"  groupby:     {p.metric.groupby}")
    if p.review_note:
        print(f"  review_note: {p.review_note}")
    print()


def cmd_list_pending(args) -> int:
    svc = CatalogService()
    pending = svc.list_pending()
    if not pending:
        print("No pending proposals.")
        return 0
    print(f"{len(pending)} pending proposal(s):\n")
    for p in pending:
        _print_proposal(p)
    return 0


def cmd_list_proposals(args) -> int:
    svc = CatalogService()
    proposals = svc.list_proposals()
    if not proposals:
        print("No proposals.")
        return 0
    print(f"{len(proposals)} proposal(s):\n")
    for p in proposals:
        _print_proposal(p)
    return 0


def cmd_list_versions(args) -> int:
    svc = CatalogService()
    versions = svc.list_versions()
    if not versions:
        print("No catalog versions yet.")
        return 0
    print("Catalog version history (newest first):")
    for v in versions:
        note = f"  ({v.get('note')})" if v.get("note") else ""
        print(f"  {v['version']}: {v.get('count', 0)} metrics @ {v.get('timestamp', '?')}{note}")
    return 0


def cmd_approve(args) -> int:
    svc = CatalogService()
    try:
        metric = svc.approve(args.proposal_id, args.by, note=args.note)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(f"Approved '{metric.name}' (proposal {args.proposal_id}).")
    print(f"  approved_by: {metric.approved_by}")
    print(f"  approved_at: {metric.approved_at}")
    return 0


def cmd_reject(args) -> int:
    svc = CatalogService()
    try:
        svc.reject(args.proposal_id, args.by, args.reason)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(f"Rejected proposal {args.proposal_id}.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="catalog.cli",
        description="Metric catalog approval workflow.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list-pending", help="List proposals awaiting review").set_defaults(func=cmd_list_pending)
    sub.add_parser("list-proposals", help="List all proposals").set_defaults(func=cmd_list_proposals)
    sub.add_parser("list-versions", help="List catalog version history").set_defaults(func=cmd_list_versions)

    p_approve = sub.add_parser("approve", help="Approve a pending proposal")
    p_approve.add_argument("proposal_id")
    p_approve.add_argument("--by", required=True, help="Username approving the proposal")
    p_approve.add_argument("--note", default=None, help="Optional review note")
    p_approve.set_defaults(func=cmd_approve)

    p_reject = sub.add_parser("reject", help="Reject a pending proposal")
    p_reject.add_argument("proposal_id")
    p_reject.add_argument("--by", required=True, help="Username rejecting the proposal")
    p_reject.add_argument("--reason", required=True, help="Reason for rejection")
    p_reject.set_defaults(func=cmd_reject)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())