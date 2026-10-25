#!/usr/bin/env bash
# Reproducible evidence run for the customer-ops-bot template package.
#
#   bash evidence/run.sh
#
# Renders both worked instances, runs the executable checks against each, and
# writes the transcript to evidence/run.log plus a machine-readable report to
# evidence/report.json. Exit code is non-zero if any check fails.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
PY="${PYTHON:-python3}"
LOG="$HERE/run.log"
REPORT="$HERE/report.json"

: > "$LOG"
overall=0

run_instance() {
  local name="$1" file="$2"
  echo "==============================================================" >> "$LOG"
  echo "instance: $name  ($file)" >> "$LOG"
  echo "template: template/bot.template.yaml" >> "$LOG"
  echo "python:   $($PY -V 2>&1)" >> "$LOG"
  echo "pyyaml:   $($PY -c 'import yaml; print(yaml.__version__)' 2>&1)" >> "$LOG"
  echo "--------------------------------------------------------------" >> "$LOG"
  "$PY" "$ROOT/checks/check_instance.py" \
    --template "$ROOT/template/bot.template.yaml" \
    --instance "$ROOT/instances/$file" \
    --report "$HERE/report-$name.json" >> "$LOG" 2>&1
  local rc=$?
  echo "exit_code: $rc" >> "$LOG"
  echo "" >> "$LOG"
  [ $rc -ne 0 ] && overall=1
  return 0
}

run_instance "retail" "example-retail.yaml"
run_instance "saas"   "example-saas.yaml"

# merge the per-instance reports into one
"$PY" - "$HERE" <<'PY' >> "$LOG" 2>&1
import json, sys, pathlib
here = pathlib.Path(sys.argv[1])
merged = {"instances": []}
for p in sorted(here.glob("report-*.json")):
    merged["instances"].append(json.loads(p.read_text()))
# An empty set of reports must NOT read as a pass: require both instances to
# be present and each to be fully green. (all([]) is True — a vacuous assert.)
expected = 2
merged["all_passed"] = (
    len(merged["instances"]) == expected
    and all(i["passed"] == i["total"] and i["total"] > 0 for i in merged["instances"])
)
(here / "report.json").write_text(json.dumps(merged, indent=2, ensure_ascii=False))
print(f"== merged report: instances={len(merged['instances'])}/{expected} all_passed={merged['all_passed']}")
for i in merged["instances"]:
    print(f"   {pathlib.Path(i['instance']).name}: {i['passed']}/{i['total']} passed")
if len(merged["instances"]) != expected:
    print(f"   FAIL: expected {expected} instance reports, got {len(merged['instances'])}")
PY

echo "==============================================================" >> "$LOG"
echo "OVERALL: $([ $overall -eq 0 ] && echo PASS || echo FAIL)" >> "$LOG"
echo "log:    $LOG" >> "$LOG"
echo "report: $REPORT" >> "$LOG"

tail -n 24 "$LOG"
exit $overall
