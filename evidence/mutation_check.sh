#!/usr/bin/env bash
# Mutation proof: the check suite must be able to FAIL.
#
# A green run only means something if a broken input actually goes red. This
# script takes the real instance files, injects four behavioural defects, and
# asserts that the checker rejects each one. Every mutation changes behaviour
# (missing parameter / unroutable intent / unbound tool / leaky knowledge),
# never a name, so a passing mutation run cannot be a rename no-op.
#
#   bash evidence/mutation_check.sh
#
# Exit 0 = the checker rejected all four mutations (suite is meaningful).
# Exit non-zero = a mutation slipped through => the suite has a hole.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
PY="${PYTHON:-python3}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

TEMPLATE="$ROOT/template/bot.template.yaml"
CHECK="$ROOT/checks/check_instance.py"
SRC="$ROOT/instances/example-retail.yaml"

pass=0
fail=0

expect_fail() {
  local name="$1" file="$2"
  "$PY" "$CHECK" --template "$TEMPLATE" --instance "$file" > "$WORK/out.txt" 2>&1
  local rc=$?
  if [ $rc -ne 0 ]; then
    echo "  [OK]   $name -> checker REJECTED (exit $rc)"
    pass=$((pass + 1))
  else
    echo "  [BAD]  $name -> checker ACCEPTED a broken instance (exit 0)"
    fail=$((fail + 1))
  fi
}

echo "== mutation proof: the suite must reject broken instances"

# M1: a required parameter is removed -> render must refuse
"$PY" - "$SRC" "$WORK/m1.yaml" <<'PY'
import sys, yaml
d = yaml.safe_load(open(sys.argv[1]))
d.pop("escalation_policy")
yaml.safe_dump(d, open(sys.argv[2], "w"))
PY
expect_fail "M1 missing required parameter (escalation_policy)" "$WORK/m1.yaml"

# M2: an intent loses all its keywords -> it becomes unroutable
"$PY" - "$SRC" "$WORK/m2.yaml" <<'PY'
import sys, yaml
d = yaml.safe_load(open(sys.argv[1]))
for it in d["intents"]:
    if it["name"] == "returns":
        it["keywords"] = []
yaml.safe_dump(d, open(sys.argv[2], "w"))
PY
expect_fail "M2 intent with no keywords (unroutable)" "$WORK/m2.yaml"

# M3: a required tool is unbound -> the intent must escalate, not answer
"$PY" - "$SRC" "$WORK/m3.yaml" <<'PY'
import sys, yaml
d = yaml.safe_load(open(sys.argv[1]))
d["tool_bindings"].pop("order_lookup")
yaml.safe_dump(d, open(sys.argv[2], "w"))
PY
expect_fail "M3 intent whose required tool is unbound" "$WORK/m3.yaml"

# M4: the redaction GUARD is disabled -> contact strings must leak and the
#     checker has to catch it. (Mutating the data instead would not be a
#     mutation at all: a leaky body is supposed to be handled correctly.)
"$PY" - "$TEMPLATE" "$WORK/m4-template.yaml" <<'PY'
import sys, yaml
d = yaml.safe_load(open(sys.argv[1]))
d["guardrails"]["redact_patterns"] = []
yaml.safe_dump(d, open(sys.argv[2], "w"))
PY
"$PY" "$CHECK" --template "$WORK/m4-template.yaml" --instance "$SRC" > "$WORK/out.txt" 2>&1
rc=$?
if [ $rc -ne 0 ]; then
  echo "  [OK]   M4 redaction guard disabled -> checker REJECTED (exit $rc)"
  pass=$((pass + 1))
else
  echo "  [BAD]  M4 redaction guard disabled -> checker ACCEPTED a leaky template (exit 0)"
  fail=$((fail + 1))
fi

echo "== $pass rejected, $fail slipped through"
if [ $fail -ne 0 ]; then
  echo "MUTATION PROOF: FAIL"
  exit 1
fi
echo "MUTATION PROOF: PASS (the suite can fail, so a green run means something)"
exit 0
