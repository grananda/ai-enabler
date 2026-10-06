#!/usr/bin/env python3
"""Refresh the Amazon Bedrock section of a pricing file from the AWS Price List.

Reads the public AWS Price List bulk API (no credentials needed) for the offer
`AmazonBedrockFoundationModels`, keeps the on-demand, standard-tier token
prices of the Claude models, and writes them per region as

    providers.bedrock.regions.<region>.models.<model>.{global,regional}
        = {input, output, cache_read, cache_write_5m, cache_write_1h}   USD per million tokens

`regional` is the price of in-region and geographic cross-region inference
(`us.`, `eu.`, `apac.` ... profiles); `global` is the price of `global.` profiles.

Usage
    update_pricing.py [--region us-east-1 ...] [--file pricing.json] [--dry-run]

Without --file it updates the pricing.json next to this script. Point it at
<project>/.enabler/kpi/pricing.json to keep a project-level table instead.
Batch, reserved (provisioned TPM), priority/flex tiers and long-context
surcharges are not token-rate on-demand prices and are left out.
"""

import argparse
import json
import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OFFER = "AmazonBedrockFoundationModels"
URL = "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/%s/current/%s/index.json"
DEFAULT_REGIONS = ["us-east-1", "us-west-2", "eu-west-1", "eu-central-1", "eu-south-2"]
SKIP = ("batch", "reserved", "tpm", "priority", "flex", "longcontext", "long_context",
        "latency", "provisioned")


def model_id(service_name):
    """'Claude Opus 5.5 (Amazon Bedrock Edition)' -> 'claude-opus-5-5'."""
    m = re.match(r"^(Claude[^()]*?)\s*\(Amazon Bedrock Edition\)$", service_name)
    if not m:
        return None
    name = m.group(1).strip().lower()
    if not re.search(r"\d", name):
        return None  # 'Claude', 'Claude Instant': retired, never used by Claude Code
    return re.sub(r"[.\s]+", "-", name)


def classify(usage_type):
    """Which price a usage type is, and for which scope; None to ignore it."""
    u = usage_type.split("MP:")[-1].lower()
    u = re.sub(r"^[a-z0-9]+_", "", u, count=1)          # region code prefix (USE1_)
    flat = u.replace("-", "_")
    if any(s in flat.replace("_", "") or s in flat for s in SKIP):
        return None
    scope = "global" if "global" in flat else "regional"
    compact = flat.replace("_", "")
    if "cacheread" in compact:
        kind = "cache_read"
    elif "cachewrite" in compact:
        kind = "cache_write_1h" if "1h" in compact else "cache_write_5m"
    elif compact.startswith("input"):
        kind = "input"
    elif compact.startswith("output"):
        kind = "output"
    else:
        return None
    return kind, scope


def fetch_region(region):
    with urllib.request.urlopen(URL % (OFFER, region), timeout=60) as resp:
        data = json.load(resp)
    terms = data.get("terms", {}).get("OnDemand", {})
    models = {}
    for sku, product in data.get("products", {}).items():
        attrs = product.get("attributes", {})
        mid = model_id(attrs.get("servicename", ""))
        hit = classify(attrs.get("usagetype", "")) if mid else None
        if not hit:
            continue
        kind, scope = hit
        for term in terms.get(sku, {}).values():
            for dim in term.get("priceDimensions", {}).values():
                usd = dim.get("pricePerUnit", {}).get("USD")
                unit = (dim.get("unit") or "").lower()
                if usd is None or "token" not in unit:
                    continue
                price = float(usd) * (1000.0 if unit.startswith("1k") else 1.0)
                if price <= 0:
                    continue
                slot = models.setdefault(mid, {}).setdefault(scope, {})
                # Two SKUs for the same price point exist for some models; they agree.
                slot[kind] = round(price, 6)
    # A model is only usable for costing with at least input and output prices.
    models = {m: {s: p for s, p in scopes.items() if "input" in p and "output" in p}
              for m, scopes in models.items()}
    return {"published": data.get("publicationDate"),
            "models": {m: s for m, s in sorted(models.items()) if s}}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--region", action="append", help="AWS region; repeatable.")
    ap.add_argument("--file", default=os.path.join(HERE, "pricing.json"))
    ap.add_argument("--dry-run", action="store_true", help="Print the result, write nothing.")
    args = ap.parse_args()

    regions = {}
    for region in args.region or DEFAULT_REGIONS:
        try:
            regions[region] = fetch_region(region)
        except Exception as exc:  # one unreachable region must not lose the others
            print("warning: %s not updated: %s" % (region, exc), file=sys.stderr)
            continue
        print("%s: %d Claude models, published %s" %
              (region, len(regions[region]["models"]), regions[region]["published"]),
              file=sys.stderr)
    if not regions:
        sys.exit("No region could be fetched; pricing file left unchanged.")

    try:
        with open(args.file, encoding="utf-8") as fh:
            pricing = json.load(fh)
    except (OSError, ValueError):
        pricing = {}
    bedrock = pricing.setdefault("providers", {}).setdefault("bedrock", {})
    bedrock.setdefault("regions", {}).update(regions)
    bedrock["source"] = "AWS Price List bulk API, offer " + OFFER
    bedrock["updated"] = max(r["published"] or "" for r in bedrock["regions"].values())[:10]
    bedrock.setdefault("default_region", "us-east-1")

    text = json.dumps(pricing, indent=2) + "\n"
    if args.dry_run:
        print(text)
    else:
        with open(args.file, "w", encoding="utf-8") as fh:
            fh.write(text)
        print("Wrote %s" % args.file, file=sys.stderr)


if __name__ == "__main__":
    main()
