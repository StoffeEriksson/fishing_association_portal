# AGENTS.md

## Critical architecture rules

This is a multi-tenant Django SaaS system.

Every request is scoped by request.org (OrganizationMiddleware).
Never break this assumption.

## Multi-tenant rules (CRITICAL)

- All tenant data must be scoped by org
- Always use:
    - request.org
    - org_id
    - or .for_org(org)
- Never introduce unfiltered queries on tenant models
- If org is missing → return empty queryset or redirect

Breaking this = data leak

## OrgModel usage

- Models inheriting OrgModel must ALWAYS be queried with org
- Prefer:
    Model.objects.for_org(request.org)

- Do not bypass this pattern

## Document workflow (DO NOT BREAK)

The document system follows a strict pipeline:

1. draft
2. locked_for_review
3. under_review
4. approved
5. signed
6. finalized
7. archived

Rules:
- Do not skip steps
- Do not merge states
- Do not auto-complete steps
- Approvals must finish before signatures
- Signatures must finish before finalization
- Only finalized documents may be archived

## Governance rules

- Meeting roles control document signatures
- Chairperson, secretary, and adjusters must exist before locking
- Do not introduce parallel role systems
- Do not bypass meeting role validation

## Document integrity

- Hash must reflect:
    - org
    - title
    - category
    - content
- Do not change hashing logic without explicit instruction
- Hash must remain stable for verification

## URL and flow rules

- Do not rename routes
- Do not change URL structure
- Preserve:
    - document approval endpoints
    - signature endpoints
    - verification endpoints

## Editing rules for Cursor

Before editing:
- Identify:
    - org scope
    - workflow_status logic
    - meeting relationships

During editing:
- Make minimal changes only
- Do not refactor entire files
- Do not move logic across layers unless requested

After editing:
- Explain:
    - impact on workflow
    - impact on org scoping
    - if migrations are required

## UI rules

- Keep flows simple at top level
- Do not redesign UI unless explicitly requested
- Status visibility is more important than design

## General philosophy

This is a system of record, not a prototype.

Stability > cleverness
Clarity > abstraction
Correctness > speed