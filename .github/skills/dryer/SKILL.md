---
name: dryer
description: Use when looking for duplicated or copy-pasted code, when two functions look alike and might be merged, when dryer prints a DUPLICATE pair, or when .metrics/dry.edn needs refreshing, in Clojure, Java, Go, TypeScript, JavaScript, Rust, Python, C#, or PowerShell projects.
---

# dryer

## Overview

dryer reports pairs of functions whose normalized structure is similar. A pair
is a candidate, not a verdict. DRY is about knowledge, not shape: merge two
functions only when they encode the same rule and would change for the same
reason. Same shape with different knowledge stays apart.

## Run

Run from the examined project's root. Use `dryer` if it is on `PATH`;
otherwise run `<base>/../../../dryer`, where `<base>` is this skill's base
directory (Python 3.11+; the first run builds the tool's own `.venv`).

| Command | Scope |
|---|---|
| `dryer` | whole project; skips `test`, `spec`, `vendor`, `node_modules`, `target` |
| `dryer src/billing` | these files or trees |
| `dryer --changed` | git additions and edits |
| `dryer tests/test_a.py tests/test_b.py` | test code: name the files (a test directory is skipped) |
| `dryer --edn`, `--threshold 0.9`, `--min-lines 3` | format and sensitivity |

Every run replaces `.metrics/dry.edn` with that run's scope. Finish with a
plain `dryer`.

## Decide each pair

Read both functions and ask: if this rule changed, would both change together?

- **Same knowledge:** pin the current behavior of both with tests, then make
  one call the other or extract the shared function. Keep the tests green.
- **Different knowledge** (same shape, different rule): keep both. Never
  reshape code just to lower the score.

## Report every pair (REQUIRED)

| Pair (score) | Verdict | Reason | Recorded |
|---|---|---|---|
| `orders.py:10-24` ~ `refunds.py:8-22` (0.91) | merged | same discount rule | the commit |
| `fees.py:3-15` ~ `tax.py:5-17` (0.86) | kept | fee schedule vs. tax law | comment in `fees.py` |

dryer has no suppression list, so record a kept pair in the code: a one-line
comment at one site naming the other function and why they stay separate.
Without it, every later run reopens the question.

## `.metrics/` is not clutter

`.metrics/` holds the snapshots uml-viewer reads (`dry.edn`, `crap.edn`,
`mutate/`). Never delete it or gitignore it to tidy up.

- `git ls-files .metrics` lists files: commit the refreshed `dry.edn` with
  the change.
- It lists nothing: leave `.metrics/` untracked and tell the user it is
  there (uml-viewer recommends committing it).

## Red flags

| Thought | Do instead |
|---|---|
| "dry.edn is untracked, so delete it" | Keep it and mention it. |
| "It scores 0.95, so merge" | Score is shape. Decide on knowledge. |
| "Reshape it so dryer stops flagging it" | Keep the code and record the decision. |

## More

- [dryer README](../../../README.md)
- [dry4clj](https://github.com/unclebob/dry4clj), the Clojure original
- [The Single Responsibility Principle](https://blog.cleancoder.com/uncle-bob/2014/05/08/SingleReponsibilityPrinciple.html)
