---
name: clarify-before-execute
description: Use when a user asks for a non-trivial task, especially if it involves code edits, SQL/data work, reports, long-running execution, external services, unclear scope, or multiple possible interpretations.
---

# Clarify Before Execute

## Core Principle

Do not start substantial work while the target is ambiguous. Make the user's goal, deliverables, assumptions, risks, and verification criteria explicit first so execution is aimed at the right outcome.

This skill exists because a plausible interpretation can still be the wrong one. A short alignment step is cheaper than rework after files, SQL, data, or reports have already drifted from the user's intent.

## When To Use

Use this for non-trivial tasks such as:

- code edits, bug fixes, refactors, reviews, or implementation work
- SQL, MaxCompute, report derivation, data analysis, or batch runs
- document/report/spec creation where structure and audience matter
- tasks involving external model calls, network access, credentials, or project data
- requests with words like "参考", "改一下", "跑全量", "再看下", "整理流程", "写方案", "输出数据", "修复", or "直接执行"

Do not slow down tiny one-step tasks with a formal checklist. If there is no meaningful ambiguity, briefly state the interpretation and proceed.

## Alignment Step

Before execution, state:

1. Understanding: goal, scope boundary, and expected deliverables.
2. Assumptions: separate confirmed facts from inferred context.
3. Possible ambiguities: fields, metric definitions, source files, directories, dates, data range, whether to edit files, whether to run full data, and whether external model or network use is allowed.
4. Verification criteria: what will prove the task is done.

If material ambiguity remains, ask the minimum necessary clarification questions and wait. Start execution only after the requirement is clear enough that a senior engineer would expect little rework from the answer.

## Execution Kickoff Format

Use concise language. For substantial work:

```text
我的理解：
- 目标：
- 交付物：
- 范围边界：

我的假设：
- 已确认：
- 推断：

可能歧义：
- ...

执行计划与验证：
1. [步骤] -> 验证: [检查]
2. [步骤] -> 验证: [检查]
```

For small tasks:

```text
我理解为 [具体解释]，没有明显歧义，我直接按这个执行。
```

## Clarification Rules

- Ask only questions that materially affect the result.
- Prefer one or two targeted questions over a broad questionnaire.
- If the repo, existing files, or memory can answer the question safely, inspect them instead of asking.
- If external model, network, secrets, or project CSV/data export is involved, get explicit authorization before sending data out.
- If the user says "中间有问题自己想办法解决", proceed through ordinary execution problems, but still ask before changing scope, sending data externally, or making destructive changes.

## Common Mistakes

| Mistake | Fix |
| --- | --- |
| Silently choosing one interpretation | Present the interpretation and assumptions first |
| Asking too many generic questions | Ask only blockers; inspect local context for the rest |
| Starting with implementation when the user asked for flow or principles | Clarify whether they want analysis, a spec, SQL/code, or all deliverables |
| Adding extra fields, abstractions, or features | Anchor to the user's stated output contract |
| Declaring success without a check | Define verification before doing the work, then report the check |

## Red Flags

Stop and clarify if you think:

- "I'll just assume..."
- "They probably mean..."
- "This extra field/helper will be useful."
- "I can skip the verification and explain the approach."
- "The old project structure is close enough."

These are signs that the task boundary is not yet reliable enough for execution.
