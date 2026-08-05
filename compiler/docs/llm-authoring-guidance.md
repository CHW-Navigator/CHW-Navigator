# LLM Authoring Guidance

This note explains which mechanical authoring requirements should be enforced by the compiler and linting layers, and which things should still be stated explicitly in prompts or human instructions.

## Let The Compiler Enforce These

Prefer code and lint over prompt micromanagement for:

- identifier-family checks such as `v_`, `p_`, `o_`, `d_`, `a_`, `st_`
- phrase-key checks such as `m_`
- DMN subset checks such as `FIRST` only
- prohibition of `AND`, `OR`, `NOT`, and parentheses in authored DMN v1 cells
- required fields and headers in catalogs
- provenance presence and shape
- phrase/output coverage gaps
- measurement-limit consistency
- patient-case shape rules such as using `missing` instead of `null`

If the compiler can reject or warn consistently, do not make the prompt carry the full burden.

## Keep These Explicit In Prompts Or Human Instructions

Still state these clearly in prompts:

- the clinical intent of the rule
- which guideline section or source is being encoded
- whether a fallback rule is desired
- whether a threshold change is intentional
- whether guidance text should change
- whether a source artifact is temporary, illustrative, or release-bound

These are content and policy questions, not just syntax questions.

## Recommended Prompt Style

Good prompt:

- explain the clinical scenario
- specify the source guideline or memo
- say which authored artifact should be changed
- let the compiler/lint stack judge mechanical validity

Bad prompt:

- spends most of its length restating every naming and file-shape rule
- asks the LLM to “remember” things the preflight tools can check directly

## Practical Rule

Move a rule out of prompts and into code when:

- it is mechanical
- it is repeated often
- it has a stable yes/no answer
- the compiler can explain failures better than a prompt can
