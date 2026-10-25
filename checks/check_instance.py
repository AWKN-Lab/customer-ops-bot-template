#!/usr/bin/env python3
"""Executable validation of a customer-ops-bot instance.

Every assertion here is one a buyer (or a reviewer) can re-run:

  1. the instance satisfies the instantiation contract
  2. the template renders with no unresolved {{slot}}
  3. a message that matches an intent routes to that intent
  4. an intent whose required tool is not bound escalates instead of answering
  5. an out-of-catalog request is refused and escalated
  6. contact-like strings are redacted from the reply

Exit code 0 = all checks passed. Non-zero = at least one failed, and the
failure is printed, so the log can be read by a human or by a machine.

    python3 check_instance.py --template T --instance I [--report out.json]
"""
from __future__ import annotations

import argparse
import re
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "template"))
from bot_runtime import InstanceError, render  # noqa: E402

SLOT_RE = "{{"


class Checks:
    def __init__(self):
        self.results: list[dict] = []

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.results.append({"check": name, "passed": bool(ok), "detail": detail})
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
        return bool(ok)

    @property
    def failed(self) -> list[dict]:
        return [r for r in self.results if not r["passed"]]


def load_yaml(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def validate_instance(template: dict, instance: dict, c: Checks) -> None:
    slots = template.get("slots", {})
    for name, spec in slots.items():
        if not spec.get("required"):
            continue
        present = name in instance and str(instance[name]).strip() != ""
        c.check(f"required parameter present and non-empty: {name}", present)

    intents = instance.get("intents") or []
    names = [i.get("name") for i in intents]
    c.check("intent names are unique", len(names) == len(set(names)),
            f"{len(names)} intents")

    for intent in intents:
        c.check(
            f"intent '{intent.get('name')}' has at least one keyword",
            len(intent.get("keywords") or []) > 0,
        )

    bound = set((instance.get("tool_bindings") or {}).keys())
    for intent in intents:
        missing = [t for t in intent.get("requires_tools", []) if t not in bound]
        if missing:
            c.check(
                f"intent '{intent['name']}' expects escalation for unbound tool(s) {missing}",
                True,
                "no tool bound -> runtime must escalate, verified below",
            )
        else:
            c.check(
                f"intent '{intent['name']}' has all required tools bound",
                True,
                ", ".join(intent.get("requires_tools", [])) or "no tool required",
            )


def run_behaviour(template: dict, instance: dict, c: Checks) -> None:
    try:
        bot = render(template, instance)
    except InstanceError as exc:
        c.check("template renders without unresolved slots", False, str(exc))
        return

    c.check("template renders without unresolved slots", True)
    c.check(
        "rendered prompt contains no leftover {{slot}}",
        SLOT_RE not in bot.system_prompt,
    )
    c.check(
        "rendered prompt names the tenant",
        instance["tenant_name"] in bot.system_prompt,
    )

    bound = set((instance.get("tool_bindings") or {}).keys())

    # 3. a matching message routes to the right intent
    for intent in instance["intents"]:
        if not intent.get("keywords"):
            continue
        msg = intent["keywords"][0]
        out = bot.handle(msg)
        expected_escalation = any(t not in bound for t in intent.get("requires_tools", []))
        if expected_escalation:
            c.check(
                f"intent '{intent['name']}' escalates when its tool is unbound",
                out["escalated"] is True and out["used_tools"] == [],
                f"escalated={out['escalated']}",
            )
        else:
            c.check(
                f"intent '{intent['name']}' routes and answers",
                out["route_to"] == intent["name"]
                and bool(out["reply"].strip())
                and out["escalated"] is False,
                f"route={out['route_to']} tools={out['used_tools']}",
            )
            c.check(
                f"intent '{intent['name']}' reply stays inside the length limit",
                len(out["reply"]) <= template["guardrails"]["max_reply_chars"],
                f"{len(out['reply'])} chars",
            )
            c.check(
                f"intent '{intent['name']}' made no forbidden claim",
                not any(
                    claim.lower() in out["reply"].lower()
                    for claim in template["guardrails"].get("forbid_claims", [])
                ),
            )

    # 5. out-of-catalog request is refused and escalated
    out = bot.handle("qwertyuiop asdfghjkl")
    c.check(
        "out-of-catalog request is refused and escalated",
        out["route_to"] is None and out["escalated"] is True and bool(out["reply"].strip()),
        f"route={out['route_to']} escalated={out['escalated']}",
    )

    # 6a. the redaction guard itself, always exercised with a fixed sample so
    #     this check can never be vacuously true.
    probe_text = "write to buyer@example.com or quote 4000123456789"
    redacted = bot._redact(probe_text)
    c.check(
        "redaction guard removes contact-like strings from knowledge content",
        "[redacted]" in redacted
        and "buyer@example.com" not in redacted
        and "4000123456789" not in redacted,
        redacted,
    )

    # 6b. end-to-end, for every intent whose body actually carries such a string
    for intent in instance["intents"]:
        body = intent.get("reply", "")
        hits = [s for s in ("@",) if s in body] + [
            s for s in re.findall(r"\b\d{6,}\b", body)
        ]
        if not hits:
            continue
        if not intent.get("keywords"):
            continue
        out = bot.handle(intent["keywords"][0])
        leaked = [
            s
            for s in re.findall(r"[\w.+-]+@[\w.-]+", body) + re.findall(r"\b\d{6,}\b", body)
            if s in out["reply"]
        ]
        c.check(
            f"intent '{intent['name']}' leaks no contact-like string to the customer",
            not leaked and "[redacted]" in out["reply"],
            f"leaked={leaked}",
        )

    # 6c. the customer's own reference must survive — redacting it would be wrong
    sample = instance["intents"][0]
    if sample.get("keywords"):
        own_ref = "987654321"
        out = bot.handle(f"{sample['keywords'][0]} {own_ref}")
        c.check(
            "the customer's own reference is echoed back, not redacted",
            own_ref in out["reply"],
            out["reply"][:90],
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", required=True)
    ap.add_argument("--instance", required=True)
    ap.add_argument("--report")
    args = ap.parse_args()

    template = load_yaml(args.template)
    instance = load_yaml(args.instance)

    c = Checks()
    print(f"== instance: {args.instance}")
    validate_instance(template, instance, c)
    print("== behaviour")
    run_behaviour(template, instance, c)

    failed = c.failed
    print(f"\n== {len(c.results) - len(failed)}/{len(c.results)} checks passed")
    if args.report:
        Path(args.report).write_text(
            json.dumps(
                {
                    "instance": args.instance,
                    "template": args.template,
                    "passed": len(c.results) - len(failed),
                    "total": len(c.results),
                    "failed": failed,
                    "checks": c.results,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
