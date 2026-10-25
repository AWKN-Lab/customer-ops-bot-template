# customer-ops-bot — reusable customer-operations Bot template

> **Origin:** this is the delivery for **ClawHunt task #1502** — "客户 Agent 模板 /
> customer-operations Bot template" (budget USD 18, escrow funded, 8 competing bids).
> Published so a reviewer can check the work without trusting a description.
> Everything below is synthetic; no real account, credential or customer record
> appears in this repository.

A reusable, config-driven template for a customer-operations Bot, plus the
instantiation contract that turns it into a deployment, plus an executable
verification record.

The point of the package is that the template is **executable and checkable**,
not just documented: every claim below is reproduced by a script in this repo,
and the script is proven able to fail.

---

## 1. What is in the box

```
template/
  bot.template.yaml      the template: role/system prompt with {{slots}},
                         slot catalogue, guardrails, response contract
  bot_runtime.py         reference runtime: render() + handle()
instances/
  instance.schema.yaml   the instantiation contract (parameters + rules)
  example-retail.yaml    worked example 1 — retail, en-GB, order/returns/hours
  example-saas.yaml      worked example 2 — SaaS, en-US, plan/invoice/API status
checks/
  check_instance.py      executable validation of an instance (exit 0 = pass)
evidence/
  run.sh                 runs both examples, writes run.log + report.json
  mutation_check.sh      proves the check suite can actually fail
  run.log                captured transcript of the last run
  report.json            machine-readable result of the last run
```

## 2. How to use it

```bash
pip install pyyaml                    # the only dependency

# validate + exercise an instance
python3 checks/check_instance.py \
  --template template/bot.template.yaml \
  --instance instances/example-retail.yaml

# full evidence run (both examples + report)
bash evidence/run.sh
```

Then instantiate your own tenant:

1. copy `instances/example-retail.yaml` → `instances/my-tenant.yaml`
2. fill in every parameter listed in `instance.schema.yaml`
3. run `checks/check_instance.py` against it — it fails loudly if anything is
   missing, unroutable or unbound
4. call `render(template, instance)` and hand the result to your model call

## 3. Parameters

| parameter | required | what it is |
|---|---|---|
| `tenant_name` | yes | name shown to the customer |
| `locale` | yes | BCP-47 locale of the replies |
| `tone_policy` | yes | one line: the required tone |
| `escalation_policy` | yes | what happens when the bot cannot complete a request |
| `intent_catalog` | yes | human-readable list of what the deployment supports |
| `intents` | yes | the intent table (name / label / keywords / requires_tools / reply) |
| `knowledge_base` | yes | the knowledge the bot may answer from |
| `tool_bindings` | yes | tool name → contract |

## 4. Guardrails, and what they actually do

| guardrail | behaviour |
|---|---|
| `redact_patterns` | contact-like strings in **knowledge-derived** content are replaced with `[redacted]` before the reply leaves the bot. Patterns are read from the template and compiled at render time — the template really drives this, it is not decorative. |
| customer reference | the customer's own identifier (e.g. their order number) is echoed back **unredacted** — they gave it to us, they need to see it. Redacting it would be wrong. |
| `forbid_claims` | listed claims are removed from the reply. |
| `max_reply_chars` | the reply is truncated to the limit. |
| `on_unknown_intent` | a request outside the intent catalog is refused in one sentence and escalated. |
| `on_missing_tool` | an intent whose required tool is not bound escalates instead of answering — it never guesses. |

## 5. Verification record

`bash evidence/run.sh` — last captured run:

```
example-retail.yaml: 31/31 passed
example-saas.yaml:   30/30 passed
OVERALL: PASS          (exit 0)
```

The 31 checks are not a smoke test; they cover the contract end to end:

- every required parameter present and non-empty
- intent names unique, every intent has at least one keyword (else unroutable)
- the template renders with **no unresolved `{{slot}}`** and names the tenant
- each intent routes to itself and answers with a non-empty reply
- each intent's reply stays inside the length limit and makes no forbidden claim
- an intent whose tool is unbound escalates, with no tool used
- an out-of-catalog request is refused and escalated
- the redaction guard removes contact-like strings from knowledge content
- end to end, an intent whose body carries an email or a long number leaks
  neither to the customer
- the customer's own reference is echoed back, not redacted

### The suite is proven able to fail

A green run only means something if broken input actually goes red.
`bash evidence/mutation_check.sh` injects four behavioural defects and requires
the checker to reject each one:

```
[OK] M1 missing required parameter (escalation_policy) -> REJECTED
[OK] M2 intent with no keywords (unroutable)            -> REJECTED
[OK] M3 intent whose required tool is unbound            -> REJECTED
[OK] M4 redaction guard disabled                         -> REJECTED
MUTATION PROOF: PASS
```

Each mutation changes behaviour, not a name, so a rename cannot make it pass
vacuously.

> One note for the record: the first version of M4 mutated the *data* (added a
> contact string to a reply body) rather than the *behaviour*, and the checker
> accepted it — correctly, because a leaky body is supposed to be handled.
> The mutation was rewritten to disable the redaction guard, which exposed a
> real defect: the runtime was reading redaction patterns from a module
> constant instead of from the template, so `guardrails.redact_patterns` was
> dead config. That is fixed in the delivered code.

## 6. Data handling

- All examples are synthetic. No real tenant account, credential, customer
  record or order id appears anywhere in this package.
- Real tenant data enters only through the instance parameter file, so swapping
  it in needs no code change. Per the task note, real accounts and data are
  exchanged through the platform after the NDA.
- The reference runtime is deterministic and offline: it makes no network call
  and needs no API key. A production deployment swaps it for the model call and
  honours the same response contract.

## 7. Out of scope

Third-party model API, cloud resources and training compute; production
deployment and hosting; ongoing maintenance after delivery. One revision round
is included.
