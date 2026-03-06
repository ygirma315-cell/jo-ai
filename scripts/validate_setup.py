from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_GITHUB_PAGES_URL = "https://ygirma315-cell.github.io/jo-ai/"
DEFAULT_RENDER_BACKEND_URL = "https://jo-ai.onrender.com"
REQUIRED_ENV_KEYS = ("BOT_TOKEN", "NVIDIA_API_KEY")
MINIAPP_REQUIRED_FILES = (
    "miniapp/index.html",
    "miniapp/app.js",
    "miniapp/style.css",
    "miniapp/config.js",
)


@dataclass
class CheckReport:
    successes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    def ok(self, message: str) -> None:
        self.successes.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def fail(self, message: str) -> None:
        self.failures.append(message)

    def print(self) -> None:
        for message in self.successes:
            print(f"[OK] {message}")
        for message in self.warnings:
            print(f"[WARN] {message}")
        for message in self.failures:
            print(f"[FAIL] {message}")

        print()
        print(
            "Summary:"
            f" ok={len(self.successes)}"
            f" warn={len(self.warnings)}"
            f" fail={len(self.failures)}"
        )


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _is_valid_url(value: str | None, *, require_public_https: bool) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return False

    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return False

    if require_public_https:
        return parsed.scheme == "https" and parsed.hostname not in {"127.0.0.1", "localhost"}

    if parsed.scheme not in {"http", "https"}:
        return False
    return True


def _load_env_values(*, include_dotenv: bool = True, include_process: bool = True) -> dict[str, str]:
    values: dict[str, str] = {}
    env_path = PROJECT_ROOT / ".env"
    if include_dotenv and env_path.exists():
        for key, value in dotenv_values(env_path).items():
            if value:
                values[key] = value

    if include_process:
        for key in REQUIRED_ENV_KEYS + (
            "PUBLIC_BASE_URL",
            "MINIAPP_URL",
            "MINIAPP_API_BASE",
            "TELEGRAM_WEBHOOK_URL",
        ):
            current = os.getenv(key, "").strip()
            if current:
                values[key] = current
    return values


def _read_git_remote_url() -> str | None:
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    remote = result.stdout.strip()
    return remote or None


def _extract_render_miniapp_url() -> str | None:
    render_path = PROJECT_ROOT / "render.yaml"
    if not render_path.exists():
        return None

    text = _read_text(render_path)
    match = re.search(r"- key:\s*MINIAPP_URL\s*\r?\n\s*value:\s*(\S+)", text)
    return match.group(1).strip() if match else None


def _extract_configured_backend_url() -> str | None:
    config_path = PROJECT_ROOT / "miniapp" / "config.js"
    if not config_path.exists():
        return None

    text = _read_text(config_path)
    match = re.search(r'window\.JO_API_BASE\s*=\s*"([^"]+)"', text)
    return match.group(1).strip() if match else None


def _workflow_contains_required_steps() -> bool:
    workflow_path = PROJECT_ROOT / ".github" / "workflows" / "pages.yml"
    if not workflow_path.exists():
        return False
    text = _read_text(workflow_path)
    has_upload = 'actions/upload-pages-artifact' in text
    has_deploy = 'actions/deploy-pages' in text
    uploads_miniapp_only = ('path: miniapp' in text) or ('cp -R miniapp/. _site/' in text and 'path: _site' in text)
    return has_upload and has_deploy and uploads_miniapp_only


def _validate_env(report: CheckReport, *, skip_env: bool) -> None:
    env_path = PROJECT_ROOT / ".env"
    values = _load_env_values()

    if skip_env:
        report.warn("Environment variable presence check was skipped.")
        return

    if env_path.exists():
        report.ok(f"Local .env file found at {env_path}.")
    else:
        report.warn("Local .env file is missing. This is fine for CI, but local bot/API runs will need it.")

    for key in REQUIRED_ENV_KEYS:
        if values.get(key, "").strip():
            report.ok(f"Required environment value detected for {key}.")
        else:
            report.fail(f"Missing required environment value: {key}. Set it in .env or your shell.")


def _validate_repo_structure(report: CheckReport) -> None:
    expected_paths = (
        "main.py",
        "bot",
        "miniapp",
        ".github/workflows/ci.yml",
        ".github/workflows/pages.yml",
        "render.yaml",
    )

    for relative_path in expected_paths:
        path = PROJECT_ROOT / relative_path
        if path.exists():
            report.ok(f"Found {relative_path}.")
        else:
            report.fail(f"Missing required project path: {relative_path}.")

    for relative_path in MINIAPP_REQUIRED_FILES:
        path = PROJECT_ROOT / relative_path
        if path.exists():
            report.ok(f"Mini app asset present: {relative_path}.")
        else:
            report.fail(f"Missing mini app asset: {relative_path}.")


def _validate_urls(report: CheckReport, *, deployment: bool, include_local_overrides: bool) -> None:
    require_public_https = deployment
    render_miniapp_url = _extract_render_miniapp_url()
    configured_backend_url = _extract_configured_backend_url()
    env_values = _load_env_values() if include_local_overrides else {}
    origin_remote = _read_git_remote_url()

    if render_miniapp_url and _is_valid_url(render_miniapp_url, require_public_https=require_public_https):
        report.ok(f"Render MINIAPP_URL is configured: {render_miniapp_url}")
    else:
        report.fail("render.yaml is missing a valid public MINIAPP_URL value.")

    if render_miniapp_url == DEFAULT_GITHUB_PAGES_URL:
        report.ok("Render MINIAPP_URL matches the expected GitHub Pages URL.")
    elif render_miniapp_url:
        report.warn(
            "Render MINIAPP_URL does not match the default Pages URL. This is okay only if you intentionally use a custom Pages URL."
        )

    if configured_backend_url and _is_valid_url(configured_backend_url, require_public_https=require_public_https):
        report.ok(f"Mini app fallback backend URL is configured: {configured_backend_url}")
    else:
        report.fail("miniapp/config.js is missing a valid JO_API_BASE URL.")

    if configured_backend_url == DEFAULT_RENDER_BACKEND_URL:
        report.warn(
            "miniapp/config.js still uses the default Render backend URL. Confirm it matches your real Render hostname."
        )

    miniapp_override = env_values.get("MINIAPP_URL", "").strip()
    if miniapp_override:
        if _is_valid_url(miniapp_override, require_public_https=require_public_https):
            report.ok(f"MINIAPP_URL override is valid: {miniapp_override}")
            if "my-miniapp" in miniapp_override:
                report.fail(
                    "MINIAPP_URL override still points to the old my-miniapp site. Remove it or update it to the jo-ai GitHub Pages URL."
                )
            elif miniapp_override != DEFAULT_GITHUB_PAGES_URL:
                report.warn(
                    "MINIAPP_URL override differs from the default jo-ai GitHub Pages URL. Keep it only if you intentionally use a custom Pages URL."
                )
        else:
            report.fail("MINIAPP_URL override exists but is not a valid URL.")

    api_override = env_values.get("MINIAPP_API_BASE", "").strip()
    if api_override:
        if _is_valid_url(api_override, require_public_https=require_public_https):
            report.ok(f"MINIAPP_API_BASE override is valid: {api_override}")
        else:
            report.fail("MINIAPP_API_BASE override exists but is not a valid URL.")

    webhook_override = env_values.get("TELEGRAM_WEBHOOK_URL", "").strip()
    if webhook_override:
        if _is_valid_url(webhook_override, require_public_https=require_public_https):
            report.ok(f"TELEGRAM_WEBHOOK_URL override is valid: {webhook_override}")
        else:
            report.fail("TELEGRAM_WEBHOOK_URL override exists but is not a valid URL.")

    if origin_remote:
        report.ok(f"Git remote origin detected: {origin_remote}")
    else:
        report.warn("Could not resolve git remote origin. Expected repo is ygirma315-cell/jo-ai.")


def _validate_workflows(report: CheckReport) -> None:
    if _workflow_contains_required_steps():
        report.ok("GitHub Pages workflow uploads the miniapp folder and deploys it.")
    else:
        report.fail("GitHub Pages workflow is missing a required miniapp upload or deploy step.")

    ci_path = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"
    if ci_path.exists():
        report.ok("CI workflow exists.")
    else:
        report.fail("CI workflow is missing.")


def _validate_workspace(report: CheckReport) -> None:
    vscode_dir = PROJECT_ROOT / ".vscode"
    if not vscode_dir.exists():
        report.warn(".vscode folder is missing. VS Code task automation will not be available.")
        return

    for filename in ("settings.json", "extensions.json", "tasks.json", "launch.json"):
        path = vscode_dir / filename
        if path.exists():
            report.ok(f"VS Code workspace file present: .vscode/{filename}")
        else:
            report.warn(f"VS Code workspace file missing: .vscode/{filename}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate local and deployment setup for JO AI.")
    parser.add_argument(
        "--skip-env",
        action="store_true",
        help="Skip checking local required environment variables.",
    )
    parser.add_argument(
        "--deployment",
        action="store_true",
        help="Require public HTTPS URLs for deployment-facing checks.",
    )
    parser.add_argument(
        "--ci",
        action="store_true",
        help="Run in CI-friendly mode. This implies --skip-env.",
    )
    args = parser.parse_args()

    skip_env = args.skip_env or args.ci
    report = CheckReport()

    print("JO AI setup validation")
    print(f"Project root: {PROJECT_ROOT}")
    print()

    _validate_env(report, skip_env=skip_env)
    _validate_repo_structure(report)
    _validate_urls(
        report,
        deployment=args.deployment or args.ci,
        include_local_overrides=not skip_env,
    )
    _validate_workflows(report)
    _validate_workspace(report)
    report.print()

    if report.failures:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
