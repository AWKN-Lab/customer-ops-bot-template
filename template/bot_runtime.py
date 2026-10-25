"""Reference runtime for the customer-ops-bot template.

Deliberately dependency-free and deterministic: the point of this package is
that the template's parameterisation, routing and guardrails are *executable
and checkable*, not just documented. A production deployment swaps this
runtime for the model call; the contract it honours is the same.

Public surface:
    render(template, instance) -> RenderedBot
    RenderedBot.handle(message) -> dict   # response contract fields
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

SLOT_RE = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")
REDACT_RE = [
    re.compile(r"\b\d{6,}\b"),
    re.compile(r"\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b", re.IGNORECASE),
]


class InstanceError(ValueError):
    """Raised when an instance does not satisfy the template's contract."""


@dataclass
class RenderedBot:
    system_prompt: str
    intents: dict
    guardrails: dict
    knowledge: str
    tools: dict
    redact_patterns: list = field(default_factory=list)
    used_tools: list = field(default_factory=list)

    # -- routing ----------------------------------------------------------
    def _route(self, message: str) -> tuple[str | None, float]:
        """Deterministic keyword router: longest matching keyword wins."""
        text = message.lower()
        best, best_score = None, 0.0
        for name, spec in self.intents.items():
            hits = sum(1 for kw in spec.get("keywords", []) if kw.lower() in text)
            if not hits:
                continue
            score = hits / max(len(spec.get("keywords", [])), 1)
            if score > best_score:
                best, best_score = name, score
        if best is None:
            return None, 0.0
        # confidence scales with how much of the intent's keyword set matched
        return best, round(min(1.0, 0.5 + 0.5 * best_score), 3)

    # -- guardrails --------------------------------------------------------
    def _redact(self, text: str) -> str:
        # Patterns come from the template's guardrails, so the template really
        # drives the behaviour (a declared guardrail that the runtime ignores
        # would be dead config).
        for pattern in self.redact_patterns:
            text = pattern.sub("[redacted]", text)
        return text

    def _guard(self, reply: str) -> tuple[str, bool]:
        limit = self.guardrails.get("max_reply_chars", 600)
        escalated = False
        for claim in self.guardrails.get("forbid_claims", []):
            if claim.lower() in reply.lower():
                reply = reply.replace(claim, "[removed-claim]")
        if len(reply) > limit:
            reply = reply[: limit - 3] + "..."
        return reply, escalated

    # -- public ------------------------------------------------------------
    def handle(self, message: str) -> dict:
        route, confidence = self._route(message)
        if route is None:
            reply = (
                "That request is outside the supported intent catalog for this "
                "deployment. Escalating to a human agent now."
            )
            return {
                "route_to": None,
                "confidence": 0.0,
                "reply": reply,
                "used_tools": [],
                "escalated": True,
            }

        spec = self.intents[route]
        used: list[str] = []
        missing = [t for t in spec.get("requires_tools", []) if t not in self.tools]
        if missing:
            reply = (
                f"This request needs {', '.join(missing)}, which is not bound in "
                "this deployment. Escalating to a human agent now."
            )
            return {
                "route_to": route,
                "confidence": confidence,
                "reply": reply,
                "used_tools": [],
                "escalated": True,
            }

        for tool in spec.get("requires_tools", []):
            used.append(tool)

        # The body is knowledge-derived, so contact-like strings in it are
        # redacted before it reaches the customer. The customer's own reference
        # is echoed back untouched — redacting it would be wrong, they need to
        # see the number they gave us.
        body = self._redact(spec.get("reply", "Handled."))
        reply = f"{spec['label']}: {body}"
        reference = self._reference(message)
        if reference:
            reply = f"{reply} (reference {reference})"
        reply, _ = self._guard(reply)
        return {
            "route_to": route,
            "confidence": confidence,
            "reply": reply,
            "used_tools": used,
            "escalated": False,
        }

    def _reference(self, message: str) -> str | None:
        """The customer's own long identifier, if the message carries one."""
        m = re.search(r"\b\d{6,}\b", message)
        return m.group(0) if m else None


def render(template: dict, instance: dict) -> RenderedBot:
    """Fill the template's slots from an instance and return a runnable bot.

    Raises InstanceError when a required slot is missing or still unresolved —
    the failure is loud on purpose, so a broken instance can never reach a
    customer.
    """
    slots = template.get("slots", {})
    for name, spec in slots.items():
        if spec.get("required") and name not in instance:
            raise InstanceError(f"missing required slot: {name}")

    # Structured instance values are rendered for humans; the structured
    # objects themselves are kept for the runtime.
    display = dict(instance)
    display["intents"] = "\n".join(
        f"  - {e.get('name')} ({e.get('label', e.get('name'))}): "
        f"keywords={e.get('keywords', [])}; requires_tools={e.get('requires_tools', [])}"
        for e in instance.get("intents", [])
    )
    display["tool_bindings"] = "\n".join(
        f"  - {name}: {spec.get('contract', spec) if isinstance(spec, dict) else spec}"
        for name, spec in (instance.get("tool_bindings") or {}).items()
    )

    def fill(value):
        if not isinstance(value, str):
            return value
        def repl(m):
            key = m.group(1)
            if key not in display:
                raise InstanceError(f"unresolved slot: {key}")
            return str(display[key])
        return SLOT_RE.sub(repl, value)

    prompt = fill(template["system_prompt"])
    unresolved = SLOT_RE.findall(prompt)
    if unresolved:
        raise InstanceError(f"unresolved slots remain: {sorted(set(unresolved))}")

    intents = {}
    for entry in instance["intents"]:
        intents[entry["name"]] = {
            "label": entry.get("label", entry["name"]),
            "keywords": entry.get("keywords", []),
            "requires_tools": entry.get("requires_tools", []),
            "reply": entry.get("reply", "Handled."),
        }

    return RenderedBot(
        system_prompt=prompt,
        intents=intents,
        guardrails=template.get("guardrails", {}),
        knowledge=fill(instance["knowledge_base"]),
        tools=instance.get("tool_bindings", {}),
        redact_patterns=[
            re.compile(p) for p in template.get("guardrails", {}).get("redact_patterns", [])
        ],
    )
