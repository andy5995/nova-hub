#!/usr/bin/env python3
"""Write the hub's API docs: an OpenAPI spec and a Markdown page per API.

    .venv/bin/python export_api_docs.py            # rewrite docs/
    .venv/bin/python export_api_docs.py --check    # exit 1 if docs/ is stale

docs/service-api.{json,md}     the contract with every client (OAuth2)
docs/management-api.{json,md}  the console's own API (session cookie)

Kept apart because they change on different terms: the Service API only on
purpose, with nova-client in step; the Management API whenever the console
needs it. Each spec is what that API serves at <mount>/openapi.json, keys
sorted. tests/test_api_docs.py fails while docs/ is stale, so regenerate in
the same commit as any API change -- a release's version bump included.
"""

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List


def format_parameter(param: Dict[str, Any]) -> str:
    """Format a parameter for markdown display"""
    name = param.get("name", "")
    location = param.get("in", "")
    required = " *(required)*" if param.get("required", False) else ""
    param_type = param.get("schema", {}).get("type", "string")
    description = param.get("description", "")

    parts = [f"**{name}**"]
    if description:
        parts.append(f"- {description}")
    parts.append(f"  - Type: `{param_type}`")
    parts.append(f"  - Location: {location}{required}")

    # Add pattern if it exists
    if "schema" in param and "pattern" in param["schema"]:
        parts.append(f"  - Pattern: `{param['schema']['pattern']}`")

    return "\n".join(parts)


def format_request_body(request_body: Dict[str, Any]) -> str:
    """Format request body for markdown display"""
    if not request_body:
        return ""

    content = request_body.get("content", {})
    description = request_body.get("description", "")

    lines = ["### Request Body\n"]
    if description:
        lines.append(f"{description}\n")

    for content_type, schema_info in content.items():
        lines.append(f"**Content-Type:** `{content_type}`\n")

        schema = schema_info.get("schema", {})
        if "type" in schema:
            lines.append(f"**Type:** `{schema['type']}`\n")

    return "\n".join(lines)


def format_response(status_code: str, response: Dict[str, Any]) -> str:
    """Format a response for markdown display"""
    description = response.get("description", "")
    content = response.get("content", {})

    lines = [f"#### {status_code}"]
    if description:
        lines.append(f"\n{description}\n")

    for content_type, schema_info in content.items():
        lines.append(f"\n**Content-Type:** `{content_type}`")

        # Show example if available
        if "example" in schema_info:
            lines.append(f"\n```json\n{json.dumps(schema_info['example'], indent=2)}\n```")

    return "\n".join(lines)


def generate_markdown(openapi_spec: Dict[str, Any]) -> str:
    """Convert OpenAPI spec to Markdown"""

    lines = []

    # Paths are written whole, mount included, so the page needs no Servers section.
    servers = openapi_spec.get("servers") or [{}]
    prefix = servers[0].get("url", "")

    # Title and Description
    info = openapi_spec.get("info", {})
    lines.append(f"# {info.get('title', 'API Documentation')}\n")
    lines.append(f"**Version:** {info.get('version', '1.0.0')}\n")

    if "description" in info:
        lines.append(f"{info['description']}\n")

    # Contact and License
    if "contact" in info:
        contact = info["contact"]
        lines.append("## Contact\n")
        if "name" in contact:
            lines.append(f"- **Name:** {contact['name']}")
        if "url" in contact:
            lines.append(f"- **URL:** {contact['url']}")
        if "email" in contact:
            lines.append(f"- **Email:** {contact['email']}")
        lines.append("")

    if "license" in info:
        license_info = info["license"]
        lines.append(f"**License:** {license_info.get('name', 'N/A')}\n")

    lines.append("---\n")

    # Table of Contents
    lines.append("## Table of Contents\n")

    # Group paths by tags
    paths = openapi_spec.get("paths", {})
    tags_dict: Dict[str, List[tuple]] = {}

    for path, methods in paths.items():
        for method, operation in methods.items():
            if method in ["get", "post", "put", "delete", "patch", "options", "head"]:
                tags = operation.get("tags", ["Default"])
                summary = operation.get("summary", path)

                for tag in tags:
                    if tag not in tags_dict:
                        tags_dict[tag] = []
                    tags_dict[tag].append((method.upper(), path, summary, operation))

    # Generate TOC
    for tag in sorted(tags_dict.keys()):
        lines.append(f"- [{tag}](#{tag.lower().replace(' ', '-')})")
    lines.append("")

    # Generate endpoint documentation by tag
    for tag in sorted(tags_dict.keys()):
        lines.append(f"## {tag}\n")

        for method, path, summary, operation in tags_dict[tag]:
            # Endpoint header
            lines.append(f"### {method} `{prefix}{path}`\n")
            lines.append(f"**{summary}**\n")

            # Description
            if "description" in operation:
                lines.append(f"{operation['description']}\n")

            # Parameters
            if "parameters" in operation and operation["parameters"]:
                lines.append("#### Parameters\n")
                for param in operation["parameters"]:
                    lines.append(format_parameter(param))
                    lines.append("")

            # Request Body
            if "requestBody" in operation:
                lines.append(format_request_body(operation["requestBody"]))

            # Responses
            if "responses" in operation:
                lines.append("#### Responses\n")
                for status_code, response in operation["responses"].items():
                    lines.append(format_response(status_code, response))
                    lines.append("")

            # Security
            if "security" in operation:
                lines.append("#### Security\n")
                for security_req in operation["security"]:
                    for scheme_name in security_req.keys():
                        lines.append(f"- **{scheme_name}**")
                lines.append("")

            lines.append("---\n")

    # Security Schemes
    if "components" in openapi_spec and "securitySchemes" in openapi_spec["components"]:
        lines.append("## Security Schemes\n")
        for scheme_name, scheme in openapi_spec["components"]["securitySchemes"].items():
            lines.append(f"### {scheme_name}\n")
            lines.append(f"**Type:** {scheme.get('type', 'N/A')}\n")
            if "description" in scheme:
                lines.append(f"{scheme['description']}\n")
            if scheme.get("type") == "oauth2":
                flows = scheme.get("flows", {})
                for flow_type, flow_data in flows.items():
                    lines.append(f"**Flow:** {flow_type}")
                    if "tokenUrl" in flow_data:
                        lines.append(f"- Token URL: `{flow_data['tokenUrl']}`")
                    if "scopes" in flow_data:
                        lines.append("- Scopes:")
                        for scope, desc in flow_data["scopes"].items():
                            lines.append(f"  - `{scope}`: {desc}")
            lines.append("")

    return "\n".join(lines)


DOCS = Path(__file__).resolve().parent / "docs"


def rendered() -> Dict[Path, str]:
    """Every file under docs/ this script owns, and what it should contain."""
    from export_openapi import dumps, management_spec, service_spec

    files = {}
    for name, spec in (("service-api", service_spec()), ("management-api", management_spec())):
        files[DOCS / f"{name}.json"] = dumps(spec)
        files[DOCS / f"{name}.md"] = generate_markdown(spec).rstrip("\n") + "\n"
    return files


def stale() -> List[Path]:
    return [path for path, text in rendered().items()
            if not path.exists() or path.read_text() != text]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="change nothing; exit 1 if any file is out of date")
    args = parser.parse_args()

    if args.check:
        out_of_date = stale()
        for path in out_of_date:
            print(f"stale: {path.relative_to(DOCS.parent)}", file=sys.stderr)
        if out_of_date:
            print("Run .venv/bin/python export_api_docs.py and commit docs/.", file=sys.stderr)
        return 1 if out_of_date else 0

    DOCS.mkdir(exist_ok=True)
    for path, text in rendered().items():
        path.write_text(text)
        print(f"Wrote {path.relative_to(DOCS.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
