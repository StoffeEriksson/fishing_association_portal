# Safe Refactor Checklist (File-by-File)

Scope: `core`, `portal`, `documents`, `governance`, `fishingrights`  
Constraint: Do not change behavior that can break tenant isolation, legal workflow, or verification integrity.

---

## core

### `core/middleware.py` (`OrganizationMiddleware`)
- **Must not change**
  - `request.org` assignment contract (session -> active membership fallback -> `None`).
  - Session key semantics for active org selection.
- **Safe to change**
  - Internal code style, small readability improvements, comments.
  - Query optimization that returns identical org selection behavior.
- **Requires extra caution**
  - Any fallback logic changes (org picking order affects all modules).
  - Any behavior for unauthenticated users.
- **Always preserve**
  - Every downstream request must keep predictable `request.org` semantics.

### `core/tenancy.py` (`OrgModel`, `OrgManager`, `.for_org`)
- **Must not change**
  - `.for_org(None)` returning empty queryset (`none()`).
  - `OrgModel.org` required FK pattern.
- **Safe to change**
  - Docstrings, type hints, naming clarity (without API changes).
- **Requires extra caution**
  - Manager/queryset behavior; many modules depend on this baseline safety.
- **Always preserve**
  - Default safe tenant filtering primitives.

### `core/models.py` (`Organization`, `Membership`)
- **Must not change**
  - Membership-to-organization mapping semantics and uniqueness.
  - Role meaning used by access logic.
- **Safe to change**
  - Non-breaking metadata additions.
- **Requires extra caution**
  - Membership activity flags and uniqueness constraints.
- **Always preserve**
  - Active membership must remain the source of tenant access eligibility.

### `core/services.py` and `core/audit.py`
- **Must not change**
  - Audit event org attribution (`org=request.org` behavior).
- **Safe to change**
  - Logging message wording, helper extraction.
- **Requires extra caution**
  - Any early-return behavior when org is missing.
- **Always preserve**
  - No audit event should be written to the wrong org.

### `core/views.py`, `core/urls.py`
- **Must not change**
  - Home redirect flow for authenticated org users.
  - Route identity used as entry point.
- **Safe to change**
  - Minor UX text/messages.
- **Requires extra caution**
  - Redirect targets that alter initial app flow.
- **Always preserve**
  - No bypass around org-scoped dashboard flow.

---

## portal

### `portal/views.py` (documents + properties UI orchestration)
- **Must not change**
  - Org-scoped query baseline for all list/detail/update actions.
  - Draft-only edit restrictions for documents.
  - Archive/trash/workspace split semantics.
  - Verification lookup constraints for finalized+archived+not-deleted docs.
- **Safe to change**
  - Pagination size, sorting UI defaults (if same record set semantics).
  - Presentation-only helper refactors and template rendering structure.
- **Requires extra caution**
  - Document filtering logic (`is_deleted`, `is_archived`, `workflow_status` combinations).
  - Any behavior around `document_hash`, print/verify QR flow.
  - Property detail shares query changes (must remain tenant-safe by ownership chain).
- **Always preserve**
  - `request.org` filters on all tenant entities.
  - Workflow gate assumptions expected by templates and action routes.

### `portal/urls.py`
- **Must not change**
  - Existing route names/paths for document actions and verification.
- **Safe to change**
  - URL ordering/comments.
- **Requires extra caution**
  - Renames or path changes (breaks links, templates, reverse lookups).
- **Always preserve**
  - Stable endpoints for approval/signature/verify flows.

### `portal/templates/*` (if touched during refactor)
- **Must not change**
  - Status-driven action visibility tied to workflow states.
- **Safe to change**
  - Styling/layout/text-only changes.
- **Requires extra caution**
  - Conditional logic for lock/review/approve/sign/finalize/archive UI controls.
- **Always preserve**
  - Visibility rules that enforce process order.

---

## documents

### `documents/models.py`
- **Must not change**
  - Document status meanings and transition intent.
  - Approval/signature uniqueness constraints.
  - `Document.document_hash` purpose and lifecycle (set on finalization path).
- **Safe to change**
  - Non-breaking model metadata and admin conveniences.
- **Requires extra caution**
  - Enum/status definitions used across views/templates.
  - Foreign key behavior connecting meeting roles to signature generation.
- **Always preserve**
  - Org ownership on `Document` and legal-signoff data integrity.

### `documents/views.py` (lock/review/approve/sign)
- **Must not change**
  - Gate sequence: draft -> locked_for_review -> under_review -> approved -> finalized.
  - Rule: approvals complete before signatures.
  - Rule: signatures complete before finalization/archive/hash.
  - Meeting role prerequisites before lock (chair/secretary/adjuster requirements).
- **Safe to change**
  - Internal helper extraction, de-duplication, message text.
- **Requires extra caution**
  - Any transition condition, especially “all approved/all signed” checks.
  - Signature regeneration behavior after approval.
  - Reverting statuses when reviewer sets changes requested.
- **Always preserve**
  - Document/org authorization checks on every mutating action.
  - Strict workflow order and legal traceability.

### `documents/utils.py` (`build_document_hash`, activity logging)
- **Must not change**
  - Hash input contract: `org_id`, `title`, `category`, stripped `content`.
  - Hash algorithm output shape used by verification.
- **Safe to change**
  - Helper organization, comments.
- **Requires extra caution**
  - Any normalization/order/field changes in hash payload.
- **Always preserve**
  - Stable deterministic hash for verification continuity.

### `documents/forms.py`
- **Must not change**
  - Field intent that supports current workflow and template placeholders.
- **Safe to change**
  - Widget classes, labels, help text.
- **Requires extra caution**
  - Field removals/renames used by renderers and template replacement logic.
- **Always preserve**
  - Data required to generate valid document content and flow.

### `documents/urls.py`
- **Must not change**
  - Existing names consumed by templates or cross-app links.
- **Safe to change**
  - Reordering/import cleanup.
- **Requires extra caution**
  - Route renames/path changes.
- **Always preserve**
  - Endpoint stability for document navigation.

---

## governance

### `governance/models.py`
- **Must not change**
  - Board permission flags semantics (`can_manage_*`).
  - Matter and meeting status meaning.
  - Meeting role structure (`chairperson`, `secretary`, `MeetingAdjuster`).
  - Linking model semantics (`MeetingMatter`).
- **Safe to change**
  - Non-breaking display/order metadata.
- **Requires extra caution**
  - Status choices and default values affecting downstream transitions.
  - Uniqueness constraints preventing duplicate roles/links.
- **Always preserve**
  - Org ownership on governance entities and role-based governance control.

### `governance/views.py`
- **Must not change**
  - `get_board_membership` access gate.
  - Permission checks for member/matter/document management operations.
  - Meeting close preconditions (protocol exists + roles set + protocol locked/review-ready).
  - Meeting role sync behavior into document approvals.
- **Safe to change**
  - View decomposition, helper extraction, non-semantic refactors.
- **Requires extra caution**
  - Any logic that updates matter statuses from meeting/protocol actions.
  - Any logic generating protocol/notice documents from meetings.
  - Any place where governance action implicitly moves document workflow.
- **Always preserve**
  - Org scoping on all governance reads/writes.
  - Governance-to-document handshake order (roles -> reviewers -> signatures).

### `governance/forms.py`
- **Must not change**
  - Org-scoped eligible users in `MeetingRolesForm`.
  - Matter selection constraints in `MeetingForm` (`ready_for_meeting` semantics).
- **Safe to change**
  - Labels/widgets/help text and UI presentation.
- **Requires extra caution**
  - Querysets for matter/user selection; this is a common leak vector.
- **Always preserve**
  - Role/user selection limited to current org active board members.

### `governance/urls.py`
- **Must not change**
  - Existing governance route names and paths.
- **Safe to change**
  - Import/order/style cleanup.
- **Requires extra caution**
  - Route changes that break templates/redirect flows.
- **Always preserve**
  - Stable governance endpoints for meeting/document lifecycle actions.

---

## fishingrights

### `fishingrights/models.py`
- **Must not change**
  - Org-bound ownership model for `Property`, `RightHolder`, `FishingRightShare`.
  - Uniqueness constraints preventing duplicate property-holder shares.
- **Safe to change**
  - Non-breaking metadata, indexes, display formatting.
- **Requires extra caution**
  - FK and constraint changes that can create cross-org ambiguity.
- **Always preserve**
  - Every share must remain attributable to one org and consistent parent entities.

### `fishingrights/views.py` (currently minimal)
- **Must not change**
  - Any future query contract must remain org-filtered.
- **Safe to change**
  - Additive view logic if it preserves tenant boundaries.
- **Requires extra caution**
  - New endpoints with joins across `Property`/`RightHolder`/`FishingRightShare`.
- **Always preserve**
  - Tenant filtering on every read/write path.

### `fishingrights/admin.py`
- **Must not change**
  - Avoid admin behaviors that expose cross-org rows by default.
- **Safe to change**
  - Admin list display/search ergonomics.
- **Requires extra caution**
  - Any bulk actions or unrestricted queryset overrides.
- **Always preserve**
  - Org-aware administration patterns.

---

## Cross-Module Guardrails (Always On)

- Keep `request.org` as the tenancy anchor in every request-handling path.
- Never introduce unfiltered queries on tenant models.
- Preserve document sequencing and never bypass approval/signature ordering.
- Preserve governance role prerequisites before document lock/meeting close.
- Keep hash verification contract stable unless a migration strategy is explicitly approved.
- Do not rename critical routes in document approval/signature/verification flows.


## Critical mindset

This system represents legal and organizational processes.

Do not optimize for simplicity if it risks correctness.

If unsure:
- ask before changing workflow logic
- prefer explicit logic over implicit automation