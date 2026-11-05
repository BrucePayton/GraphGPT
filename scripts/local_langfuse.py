"""Prepare an isolated, loopback-only Langfuse stack from the official compose file.

Run with the project's Python environment. Credentials are generated once, stored
with mode 0600 in ignored .local/langfuse, and never printed. No existing stack is
modified. Start with the command printed by this script.
"""

import json
import os
import secrets
from pathlib import Path
from urllib.request import urlopen

import yaml

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / ".local" / "langfuse"


def main() -> None:
    TARGET.mkdir(parents=True, exist_ok=True, mode=0o700)
    compose = TARGET / "compose.yaml"
    env = TARGET / ".env"
    if compose.exists() or env.exists():
        if not (compose.exists() and env.exists()):
            raise RuntimeError("Incomplete existing setup; inspect it before retrying")
        print("Reusing existing local configuration (credentials unchanged).")
    else:
        # Record the exact upstream revision for reproducibility.
        with urlopen(
            "https://api.github.com/repos/langfuse/langfuse/commits/main", timeout=30
        ) as r:
            revision = json.load(r)["sha"]
        url = f"https://raw.githubusercontent.com/langfuse/langfuse/{revision}/docker-compose.yml"
        with urlopen(url, timeout=30) as r:
            data = yaml.safe_load(r.read())
        services = data["services"]
        services.pop("langfuse-ai-gateway", None)
        for service in services.values():
            service.pop("ports", None)
            service["restart"] = "unless-stopped"
        services["langfuse-web"]["ports"] = ["127.0.0.1:3300:3000"]
        services["minio"]["ports"] = ["127.0.0.1:3390:9000"]
        data["name"] = "graphgpt-local-langfuse"
        password = secrets.token_hex(24)
        values = {
            "NEXTAUTH_URL": "http://localhost:3300",
            "NEXTAUTH_SECRET": secrets.token_hex(32),
            "SALT": secrets.token_hex(32),
            "ENCRYPTION_KEY": secrets.token_hex(32),
            "POSTGRES_PASSWORD": password,
            "DATABASE_URL": f"postgresql://postgres:{password}@postgres:5432/postgres",
            "CLICKHOUSE_PASSWORD": secrets.token_hex(24),
            "REDIS_AUTH": secrets.token_hex(24),
            "MINIO_ROOT_PASSWORD": secrets.token_hex(24),
            "TELEMETRY_ENABLED": "false",
            "LANGFUSE_INIT_ORG_ID": "graphgpt-local",
            "LANGFUSE_INIT_ORG_NAME": "GraphGPT Local",
            "LANGFUSE_INIT_PROJECT_ID": "graphgpt-local",
            "LANGFUSE_INIT_PROJECT_NAME": "GraphGPT Local",
            "LANGFUSE_INIT_PROJECT_PUBLIC_KEY": "pk-lf-" + secrets.token_hex(16),
            "LANGFUSE_INIT_PROJECT_SECRET_KEY": "sk-lf-" + secrets.token_hex(24),
            "LANGFUSE_INIT_USER_EMAIL": "developer@graphgpt.local",
            "LANGFUSE_INIT_USER_NAME": "GraphGPT Developer",
            "LANGFUSE_INIT_USER_PASSWORD": secrets.token_hex(24),
        }
        for kind in ("EVENT", "MEDIA", "BATCH_EXPORT"):
            values[
                f"LANGFUSE_S3_{kind}_UPLOAD_SECRET_ACCESS_KEY"
                if kind != "BATCH_EXPORT"
                else "LANGFUSE_S3_BATCH_EXPORT_SECRET_ACCESS_KEY"
            ] = values["MINIO_ROOT_PASSWORD"]
        # Keep the shared internal endpoint, override only the web browser-facing one.
        services["langfuse-web"]["environment"]["LANGFUSE_S3_MEDIA_UPLOAD_ENDPOINT"] = (
            "http://localhost:3390"
        )
        with os.fdopen(os.open(env, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as f:
            f.write("".join(f"{key}={value}\n" for key, value in values.items()))
        compose.write_text(yaml.safe_dump(data, sort_keys=False))
        (TARGET / "upstream.json").write_text(
            json.dumps({"revision": revision, "url": url}, indent=2)
        )
    print(f"docker compose --project-directory {TARGET} up -d")
    print("UI: http://localhost:3300 (login stored in .local/langfuse/.env)")


if __name__ == "__main__":
    main()
