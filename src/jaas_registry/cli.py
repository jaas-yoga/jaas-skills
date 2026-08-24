"""jaasctl: CLI entrypoint for validating, publishing, and serving skills."""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from jaas_registry.common.errors import JaasError

if TYPE_CHECKING:
    from jaas_registry.guardrails.client import GuardrailsClient


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jaasctl")
    subparsers = parser.add_subparsers(dest="command")

    validate_parser = subparsers.add_parser(
        "validate", help="Validate a skill package against the manifest schema"
    )
    validate_parser.add_argument("path", help="Path to a skill package directory")

    publish_parser = subparsers.add_parser(
        "publish", help="Package, sign, and publish a skill to the registry"
    )
    publish_parser.add_argument("path", help="Path to a skill package directory")
    publish_parser.add_argument(
        "--actor", default=None, help="Publisher identity for the audit log"
    )

    serve_parser = subparsers.add_parser("serve", help="Run the registry API gateway")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8027)

    release_parser = subparsers.add_parser(
        "release",
        help="Release a skill from CI: package, upload, and publish via "
        "POST /api/v1/skills/release",
    )
    release_parser.add_argument("path", help="Path to a skill package directory")
    release_parser.add_argument(
        "--tag", required=True, help="The git tag that triggered this release, e.g. v1.2.3"
    )
    release_parser.add_argument(
        "--api-url", default="http://127.0.0.1:8027", help="Base URL of the registry API"
    )
    release_parser.add_argument(
        "--token", default=None, help="Personal access token (fallback auth path)"
    )
    release_parser.add_argument(
        "--oidc-token",
        default=None,
        help="GitHub Actions OIDC ID token (recommended auth path — see "
        "actions/github-script's core.getIDToken())",
    )
    release_parser.add_argument(
        "--repo-url", default=None, help="This skill's repo URL (required with --token)"
    )
    release_parser.add_argument(
        "--ci-run-url", default=None, help="Link to the CI run, for provenance"
    )
    release_parser.add_argument(
        "--release-branch",
        default=None,
        help="Branch this release comes from, checked against the repo link's allowed "
        "release branches (--token path only — with --oidc-token, the workflow's "
        "`environment:` claim is used instead and this is ignored)",
    )

    guardrails_parser = subparsers.add_parser(
        "guardrails", help="Manage a tenant's custom guardrail rules"
    )
    guardrails_subparsers = guardrails_parser.add_subparsers(dest="guardrails_command")

    push_parser = guardrails_subparsers.add_parser(
        "push", help="Sync local rule YAML files to a tenant's custom guardrail rule library"
    )
    push_parser.add_argument("dir", help="Directory of *.yaml custom rule files")
    push_parser.add_argument("--tenant-id", required=True)
    push_parser.add_argument("--token", required=True, help="Personal access token")
    push_parser.add_argument(
        "--api-url", default="http://127.0.0.1:8027", help="Base URL of the registry API"
    )

    validate_rule_parser = guardrails_subparsers.add_parser(
        "validate", help="Dry-run validate a single custom rule YAML file"
    )
    validate_rule_parser.add_argument("file", help="Path to a rule YAML file")

    return parser


def cmd_validate(
    args: argparse.Namespace, *, guardrails_client: GuardrailsClient | None = None
) -> int:
    from jaas_registry.artifact.publish import load_source_documents
    from jaas_registry.common.config import load_settings
    from jaas_registry.guardrails.client import HttpGuardrailsClient
    from jaas_registry.guardrails.custom_rules import CustomGuardrailRuleStore
    from jaas_registry.guardrails.policy import default_policy
    from jaas_registry.guardrails.skill_config import (
        parse_skill_guardrail_config,
        read_skill_guardrail_config,
        resolve_guardrails_for_skill,
    )
    from jaas_registry.validation.package import validate_skill_package

    try:
        files, manifest_data, io_schema_data, permissions_data, dependencies_data = (
            load_source_documents(Path(args.path))
        )
        docs = validate_skill_package(
            manifest=manifest_data,
            io_schema=io_schema_data,
            permissions=permissions_data,
            dependencies=dependencies_data,
        )
    except JaasError as exc:
        print(f"INVALID [{exc.code.value}]: {exc.message}")
        return 1
    except FileNotFoundError as exc:
        print(f"INVALID [MISSING_FILE]: {exc}")
        return 1

    # design.md §4.5: the standalone jaas-guardrails service, reached only
    # over HTTP — a clear, actionable error prints below if it's not running.
    # `guardrails_client` is a test-only override (mirrors api/deps.py's DI
    # pattern); real invocations always go through the real HTTP client.
    client = guardrails_client or HttpGuardrailsClient(load_settings().guardrails_service_url)
    settings = load_settings()
    try:
        catalog = client.fetch_catalog()
        policy = default_policy("local", catalog)
        skill_config = parse_skill_guardrail_config(
            read_skill_guardrail_config(Path(args.path))
        )
        enabled_ids, custom_rules = resolve_guardrails_for_skill(
            tenant_id="local",
            skill_id=docs.manifest.id,
            policy=policy,
            catalog_ids=frozenset(d.id for d in catalog),
            skill_config=skill_config,
            custom_rule_store=CustomGuardrailRuleStore(settings.policy_dir),
        )
        scan = client.scan(
            files=files,
            manifest=docs.manifest,
            permissions=docs.permissions.root,
            dependencies=docs.dependencies.root,
            enabled_check_ids=enabled_ids,
            custom_rules=custom_rules,
        )
    except JaasError as exc:
        print(f"INVALID [{exc.code.value}]: {exc.message}")
        return 1

    for finding in scan.warnings:
        print(f"WARN [{finding.check_id}] {finding.file}: {finding.message}")
    if scan.blocking:
        for finding in scan.blocking:
            print(f"BLOCKED [{finding.check_id}] {finding.file}: {finding.message}")
        print(f"GUARDRAILS FAILED: {docs.manifest.id}@{docs.manifest.version}")
        return 1

    print(f"VALID: {docs.manifest.id}@{docs.manifest.version}")
    return 0


def cmd_publish(
    args: argparse.Namespace, *, guardrails_client: GuardrailsClient | None = None
) -> int:
    from jaas_registry.artifact.publish import load_source_documents, publish_skill
    from jaas_registry.artifact.signing import load_or_create_keypair
    from jaas_registry.artifact.trust import ensure_key_registered, load_trust_policy
    from jaas_registry.common.audit import StructuredLogAuditSink
    from jaas_registry.common.config import load_settings
    from jaas_registry.guardrails.client import HttpGuardrailsClient
    from jaas_registry.guardrails.custom_rules import CustomGuardrailRuleStore
    from jaas_registry.guardrails.policy import GuardrailPolicy, default_policy
    from jaas_registry.guardrails.skill_config import (
        parse_skill_guardrail_config,
        read_skill_guardrail_config,
        resolve_guardrails_for_skill,
    )
    from jaas_registry.observability.tracing import build_tracer
    from jaas_registry.storage.local_filesystem import LocalFilesystemStore

    settings = load_settings()
    tracer = build_tracer(batch=True)
    store = LocalFilesystemStore(settings.storage_root, tracer=tracer)
    keypair = load_or_create_keypair(settings.policy_dir / "signing_key.pem")
    ensure_key_registered(settings.policy_dir, keypair.public_key_pem())
    trust_policy = load_trust_policy(settings.policy_dir)
    # test-only override, mirrors api/deps.py's DI pattern (see cmd_validate).
    guardrails_client = guardrails_client or HttpGuardrailsClient(settings.guardrails_service_url)

    try:
        # A lightweight pre-read (not full validation — publish_skill()
        # does that itself) just to get the manifest id, needed to resolve
        # this skill's own .jaas/guardrails.yaml before the real publish.
        _, manifest_data, *_ = load_source_documents(Path(args.path))
        skill_id = manifest_data.get("id", "") if isinstance(manifest_data, dict) else ""
        catalog = guardrails_client.fetch_catalog()
        skill_config = parse_skill_guardrail_config(
            read_skill_guardrail_config(Path(args.path))
        )
        enabled_ids, custom_rules = resolve_guardrails_for_skill(
            tenant_id="local",
            skill_id=skill_id,
            policy=default_policy("local", catalog),
            catalog_ids=frozenset(d.id for d in catalog),
            skill_config=skill_config,
            custom_rule_store=CustomGuardrailRuleStore(settings.policy_dir),
        )
        # One parent span per publish, so its storage-call spans nest under it
        # instead of each becoming its own unrelated trace (design.md §10.3).
        with tracer.start_as_current_span("jaasctl.publish"):
            result = publish_skill(
                source_dir=Path(args.path),
                store=store,
                signing_key=keypair,
                trust_policy=trust_policy,
                actor=args.actor or getpass.getuser(),
                audit_sink=StructuredLogAuditSink(),
                guardrails_client=guardrails_client,
                guardrail_policy=GuardrailPolicy(
                    tenant_id="local", enabled_check_ids=enabled_ids
                ),
                custom_rules=custom_rules,
            )
    except JaasError as exc:
        print(f"PUBLISH FAILED [{exc.code.value}]: {exc.message}")
        return 1
    except FileNotFoundError as exc:
        print(f"PUBLISH FAILED [MISSING_FILE]: {exc}")
        return 1

    print(
        f"PUBLISHED: {result.manifest.id}@{result.manifest.version} "
        f"digest={result.manifest.digest}"
    )
    return 0


def cmd_release(args: argparse.Namespace) -> int:
    """CI-facing: packages a skill directory and calls
    POST /api/v1/skills/release over HTTP — unlike cmd_publish, this
    never touches local storage directly, since a CI runner doesn't have
    (and shouldn't have) filesystem access to the registry's storage_root
    or signing key."""
    import base64
    import subprocess

    import httpx

    from jaas_registry.artifact.publish import load_source_documents

    api_url = args.api_url.rstrip("/")
    try:
        files, *_ = load_source_documents(Path(args.path))
    except FileNotFoundError as exc:
        print(f"RELEASE FAILED [MISSING_FILE]: {exc}")
        return 1

    # Best-effort: this skill directory's path relative to its own repo
    # root, e.g. "jira.create_ticket" for a repo hosting several skills,
    # or None at the repo root (the reference CI workflow's documented
    # "one repo per skill" convention). Lets the registry's "browse full
    # source at this tag" feature scope a GitHub tree fetch to just this
    # skill's own files instead of the whole repo. Never fails the release
    # if git isn't available or args.path isn't a git checkout — it's
    # purely descriptive metadata for a read-only UI feature, not anything
    # that gates or verifies the release itself.
    source_path: str | None = None
    try:
        prefix_result = subprocess.run(
            ["git", "-C", str(args.path), "rev-parse", "--show-prefix"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if prefix_result.returncode == 0:
            source_path = prefix_result.stdout.strip().rstrip("/") or None
    except (OSError, subprocess.TimeoutExpired):
        pass

    headers: dict[str, str] = {}
    if args.oidc_token:
        headers["X-Jaas-OIDC-Token"] = args.oidc_token
    elif args.token:
        headers["Authorization"] = f"Bearer {args.token}"
    else:
        print("RELEASE FAILED: one of --token or --oidc-token is required")
        return 1

    if args.release_branch and args.oidc_token:
        print(
            "note: --release-branch is ignored with --oidc-token; the workflow's "
            "environment: claim is used instead"
        )

    body = {
        "files": {p: base64.b64encode(c).decode("ascii") for p, c in files.items()},
        "tag": args.tag,
        "ciRunUrl": args.ci_run_url,
        "repoUrl": args.repo_url,
        "releaseBranch": args.release_branch,
        "sourcePath": source_path,
    }

    try:
        resp = httpx.post(
            f"{api_url}/api/v1/skills/release", json=body, headers=headers, timeout=30.0
        )
    except httpx.HTTPError as exc:
        print(f"RELEASE FAILED: could not reach {api_url}: {exc}")
        return 1

    if resp.status_code >= 400:
        try:
            error = resp.json()
            print(f"RELEASE FAILED [{error.get('code', 'HTTP_' + str(resp.status_code))}]: "
                  f"{error.get('message', resp.text)}")
        except ValueError:
            print(f"RELEASE FAILED [HTTP {resp.status_code}]: {resp.text}")
        return 1

    result = resp.json()
    print(f"RELEASED: {result['id']}@{result['version']} digest={result['digest']}")
    return 0


def cmd_guardrails_push(args: argparse.Namespace) -> int:
    """Syncs local *.yaml/*.yml rule files to a tenant's custom guardrail
    rule library, one PUT per file — the git-native alternative to
    authoring custom rules in the web UI (same PUT endpoint either way,
    see api/tenant_routes.py::put_custom_guardrail_rule)."""
    import httpx
    import yaml

    api_url = args.api_url.rstrip("/")
    headers = {"Authorization": f"Bearer {args.token}"}
    rule_files = sorted(Path(args.dir).glob("*.yaml")) + sorted(Path(args.dir).glob("*.yml"))
    if not rule_files:
        print(f"no rule files found in {args.dir}")
        return 1

    failed = False
    for path in rule_files:
        data = yaml.safe_load(path.read_text()) or {}
        slug = data.get("slug") or path.stem
        body = {
            "slug": slug,
            "name": data.get("name", ""),
            "description": data.get("description", ""),
            "category": data.get("category", ""),
            "severity": data.get("severity", ""),
            "standardRef": data.get("standard_ref", ""),
            "kind": data.get("kind", ""),
            "config": data.get("config", {}),
        }
        try:
            resp = httpx.put(
                f"{api_url}/api/v1/tenants/{args.tenant_id}/custom-guardrails/{slug}",
                json=body,
                headers=headers,
                timeout=30.0,
            )
        except httpx.HTTPError as exc:
            print(f"FAILED [{slug}]: could not reach {api_url}: {exc}")
            failed = True
            continue
        if resp.status_code >= 400:
            print(f"FAILED [{slug}]: {resp.text}")
            failed = True
            continue
        print(f"PUSHED: {slug}")

    return 1 if failed else 0


def cmd_guardrails_validate(args: argparse.Namespace) -> int:
    """Dry-run only — talks directly to the standalone guardrails service
    (not the backend API, no tenant/auth needed), same as how
    cmd_validate reaches it. Fast local feedback while authoring a rule,
    before it's ever pushed anywhere."""
    import yaml

    from jaas_registry.common.config import load_settings
    from jaas_registry.guardrails.client import HttpGuardrailsClient

    data = yaml.safe_load(Path(args.file).read_text()) or {}
    client = HttpGuardrailsClient(load_settings().guardrails_service_url)
    try:
        error = client.validate_rule(
            id=data.get("id") or data.get("slug", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            category=data.get("category", ""),
            severity=data.get("severity", ""),
            standard_ref=data.get("standard_ref", ""),
            kind=data.get("kind", ""),
            config=data.get("config", {}),
        )
    except JaasError as exc:
        print(f"INVALID [{exc.code.value}]: {exc.message}")
        return 1

    if error is not None:
        print(f"INVALID: {error}")
        return 1
    print(f"VALID: {data.get('id') or data.get('slug', '')}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from jaas_registry.api.app import create_app
    from jaas_registry.authz.policy import build_authorizer_from_settings
    from jaas_registry.common.config import load_settings
    from jaas_registry.index.bootstrap import bootstrap_index
    from jaas_registry.observability.logging import configure_logging
    from jaas_registry.observability.tracing import build_tracer
    from jaas_registry.storage.local_filesystem import LocalFilesystemStore

    configure_logging()

    settings = load_settings()
    tracer = build_tracer(batch=True)
    store = LocalFilesystemStore(settings.storage_root, tracer=tracer)
    index = bootstrap_index(store)
    authorizer = build_authorizer_from_settings(settings)

    app = create_app(
        index=index, store=store, settings=settings, authorizer=authorizer, tracer=tracer
    )
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


def main(
    argv: list[str] | None = None, *, guardrails_client: GuardrailsClient | None = None
) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "validate":
        return cmd_validate(args, guardrails_client=guardrails_client)
    if args.command == "publish":
        return cmd_publish(args, guardrails_client=guardrails_client)
    if args.command == "serve":
        return cmd_serve(args)
    if args.command == "release":
        return cmd_release(args)
    if args.command == "guardrails":
        if args.guardrails_command == "push":
            return cmd_guardrails_push(args)
        if args.guardrails_command == "validate":
            return cmd_guardrails_validate(args)
        parser.print_help()
        return 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
