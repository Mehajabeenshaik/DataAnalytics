"""
CLI for tenant/org administration.

Usage:
    python -m tenant.cli create-org <name>
    python -m tenant.cli create-tenant <org_id> <name>
    python -m tenant.cli create-user <email> [--name "Display"]
    python -m tenant.cli add-user <user_email> --role <role> --tenant <tenant_id>
    python -m tenant.cli list-orgs
    python -m tenant.cli list-tenants [--org <org_id>]
    python -m tenant.cli usage <tenant_id>
    python -m tenant.cli export-audit <tenant_id> [--days 30]
"""

from __future__ import annotations

import argparse
import sys

from .service import TenantService


def cmd_create_org(args) -> int:
    svc = TenantService()
    org = svc.create_org(args.name)
    print(f"Created org: {org.id} ({org.name})")
    return 0


def cmd_create_tenant(args) -> int:
    svc = TenantService()
    tenant = svc.create_tenant(args.org_id, args.name)
    print(f"Created tenant: {tenant.id} ({tenant.name}) org={tenant.org_id}")
    return 0


def cmd_create_user(args) -> int:
    svc = TenantService()
    user = svc.create_user(args.email, display_name=args.name or "")
    print(f"Created user: {user.id} ({user.email})")
    return 0


def cmd_add_user(args) -> int:
    svc = TenantService()
    user = svc.find_user_by_email(args.email)
    if not user:
        print(f"User not found: {args.email}", file=sys.stderr)
        return 1
    membership = svc.add_user(
        user_id=user.id,
        role=args.role,
        tenant_id=args.tenant,
        org_id=args.org,
    )
    print(f"Added user {user.email} as {args.role} (membership {membership.id})")
    return 0


def cmd_list_orgs(args) -> int:
    svc = TenantService()
    for org in svc.list_orgs():
        print(f"  {org.id}: {org.name} ({org.status})")
    return 0


def cmd_list_tenants(args) -> int:
    svc = TenantService()
    tenants = svc.list_tenants_for_org(args.org) if args.org else []
    if not args.org:
        # list all across orgs
        tenants = []
        for org in svc.list_orgs():
            tenants.extend(svc.list_tenants_for_org(org.id))
    for t in tenants:
        print(f"  {t.id}: {t.name} (org={t.org_id}, {t.status})")
    return 0


def cmd_usage(args) -> int:
    from tenant_quotas import get_usage
    print(get_usage(args.tenant_id))
    return 0


def cmd_export_audit(args) -> int:
    from audit_logger import export_audit
    logs = export_audit(args.tenant_id, days=args.days)
    for entry in logs:
        print(f"  {entry['timestamp']} | {entry['username']} | {entry['action_type']} | {entry['details']}")
    print(f"\n{len(logs)} audit records for tenant {args.tenant_id} (last {args.days}d)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tenant.cli", description="Tenant administration.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list-orgs").set_defaults(func=cmd_list_orgs)
    sub.add_parser("list-tenants").add_argument("--org").set_defaults(func=cmd_list_tenants)

    p = sub.add_parser("create-org")
    p.add_argument("name")
    p.set_defaults(func=cmd_create_org)

    p = sub.add_parser("create-tenant")
    p.add_argument("org_id")
    p.add_argument("name")
    p.set_defaults(func=cmd_create_tenant)

    p = sub.add_parser("create-user")
    p.add_argument("email")
    p.add_argument("--name", default=None)
    p.set_defaults(func=cmd_create_user)

    p = sub.add_parser("add-user")
    p.add_argument("email")
    p.add_argument("--role", required=True, choices=["owner", "admin", "analyst", "viewer"])
    p.add_argument("--tenant", default=None)
    p.add_argument("--org", default=None)
    p.set_defaults(func=cmd_add_user)

    p = sub.add_parser("usage")
    p.add_argument("tenant_id")
    p.set_defaults(func=cmd_usage)

    p = sub.add_parser("export-audit")
    p.add_argument("tenant_id")
    p.add_argument("--days", type=int, default=30)
    p.set_defaults(func=cmd_export_audit)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())