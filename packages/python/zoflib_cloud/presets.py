"""Data-only S3 presets from spec/providers.json. Presets hold defaults and caveats, never credentials."""
import json


def load_presets(providers_json):
    with open(providers_json, encoding="utf-8") as f: data = json.load(f)
    return {p["id"]: p for p in data["providers"] if p["protocol"] == "s3"}


def config_from_preset(preset, root, credential_ref, endpoint=None, region=None, **kw):
    """Build an S3Config. Self-hosted presets need an explicit endpoint; templates with <placeholders> must be filled in."""
    from .s3 import S3Config
    endpoint = endpoint or preset["endpoint_template"]
    if not endpoint or "<" in endpoint: raise ValueError(f"{preset['id']} needs an explicit endpoint (template: {preset['endpoint_template']})")
    addressing = "virtual" if preset["addressing"] == "virtual" else "path"
    return S3Config(endpoint=endpoint, region=region or preset["region"] or "us-east-1", credential_ref=credential_ref,
                    root=root, addressing=addressing, provider=preset["id"], **kw)
