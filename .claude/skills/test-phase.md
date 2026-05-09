# Test Phase Skill

Spawn an unbiased testing subagent after each implementation phase.

## Subagent Prompt Template

When spawning a test subagent, use this structure:

```
Role: You are an unbiased QA engineer. You did NOT write the implementation code.
Your goal is to break it, not validate it.

Goal: Write comprehensive tests for the code in [DIRECTORY].

Input:
- Implementation files: [LIST FILE PATHS]
- Service type: [python-fastapi | typescript-agent | python-pipeline]

Instructions:
1. READ every implementation file before writing any test
2. Identify: happy paths, edge cases, error conditions, boundary values
3. For each function/endpoint/class, ask: "what could go wrong?"
4. Write tests that WILL FAIL if the implementation has bugs
5. Do NOT mock things that should be tested (e.g., don't mock the solver — test it)
6. DO mock external I/O (ISO APIs, Kafka, TimescaleDB) using fixtures
7. Run: [LINT COMMAND] then [TYPECHECK COMMAND] then [TEST COMMAND]
8. Report: tests written, tests passing, tests failing, coverage %

Test categories to cover:
- Unit: pure functions, data transformations, validation logic
- Integration: service endpoints with mocked DB/external deps
- Contract: input/output shape matches TypeScript shared types
- Error: invalid input, network failures, solver infeasibility, empty data

Output format:
{
  "tests_written": N,
  "passing": N,
  "failing": N,
  "coverage_pct": N,
  "lint_clean": bool,
  "typecheck_clean": bool,
  "issues_found": ["list of real bugs found"]
}
```

## Per-Phase Commands

### Phase 4 (data-pipeline)
- Lint: `ruff check packages/data-pipeline/`
- Typecheck: `mypy packages/data-pipeline/src`
- Test: `cd packages/data-pipeline && pytest tests/ -v --cov=src`

### Phase 5 (services)
- Lint: `ruff check services/`
- Typecheck: `mypy services/forecasting/src services/optimization/src`
- Test: `cd services/forecasting && pytest tests/ -v --cov=src`
         `cd services/optimization && pytest tests/ -v --cov=src`

### Phase 6 (agents)
- Typecheck: `npm run typecheck -w packages/agents`
- Lint: `npm run lint`
- Test: `npm run test -w packages/agents`

### E2E
- Full stack: `make infra-up && make simulate`
