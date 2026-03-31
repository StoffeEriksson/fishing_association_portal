from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.utils import timezone

from .forms import DocumentApprovalCreateForm
from .models import (
    Document,
    DocumentApproval,
    DocumentApprovalStatus,
    DocumentWorkflowStatus,
    DocumentSignature,
    DocumentSignatureRole,
    DocumentSignatureStatus,
)
from governance.models import BoardMembership, BoardRole
from .utils import log_document_activity


@login_required
def lock_document_for_review(request, pk):
    document = get_object_or_404(
        Document.objects.filter(org=request.org),
        pk=pk,
    )

    # Bara tillåtet om dokument är i utkast
    if document.workflow_status != DocumentWorkflowStatus.DRAFT:
        messages.error(request, "Dokumentet är redan låst eller hanteras.")
        return redirect("portal:document_detail", pk=document.pk)

    document.workflow_status = DocumentWorkflowStatus.LOCKED_FOR_REVIEW
    document.locked_at = timezone.now()
    document.locked_by = request.user
    document.save(update_fields=["workflow_status", "locked_at", "locked_by", "updated_at"])

    messages.success(request, "Dokumentet är nu låst för justering.")

    return redirect("portal:document_detail", pk=document.pk)


@login_required
def add_document_reviewer(request, pk):
    from django.contrib.auth import get_user_model

    User = get_user_model()

    document = get_object_or_404(
        Document.objects.filter(org=request.org),
        pk=pk,
    )

    if document.workflow_status not in [
        DocumentWorkflowStatus.DRAFT,
        DocumentWorkflowStatus.LOCKED_FOR_REVIEW,
        DocumentWorkflowStatus.UNDER_REVIEW,
    ]:
        messages.error(request, "Justerare kan bara läggas till när dokumentet är låst för justering.")
        return redirect("portal:document_detail", pk=document.pk)

    reviewer_queryset = User.objects.filter(
        board_memberships__org=request.org,
        board_memberships__is_active=True,
    ).distinct().order_by("email")

    if request.method == "POST":
        form = DocumentApprovalCreateForm(request.POST)
        form.fields["reviewer"].queryset = reviewer_queryset

        if form.is_valid():
            approval = form.save(commit=False)
            approval.document = document

            exists = DocumentApproval.objects.filter(
                document=document,
                reviewer=approval.reviewer,
            ).exists()

            if exists:
                messages.warning(request, "Den användaren är redan tillagd som justerare.")
                return redirect("portal:document_detail", pk=document.pk)

            approval.save()

            if document.workflow_status == DocumentWorkflowStatus.LOCKED_FOR_REVIEW:
                document.workflow_status = DocumentWorkflowStatus.UNDER_REVIEW
                document.save(update_fields=["workflow_status", "updated_at"])

            messages.success(request, "Justerare har lagts till.")
            return redirect("portal:document_detail", pk=document.pk)
    else:
        form = DocumentApprovalCreateForm()
        form.fields["reviewer"].queryset = reviewer_queryset

    return render(
        request,
        "portal/document_add_reviewer.html",
        {
            "document": document,
            "form": form,
        },
    )


@login_required
def approve_document(request, pk):
    from governance.models import BoardMembership, BoardRole

    approval = get_object_or_404(
        DocumentApproval.objects.select_related("document"),
        pk=pk,
        reviewer=request.user,
    )

    document = approval.document

    if request.method == "POST":
        approval.status = DocumentApprovalStatus.APPROVED
        approval.responded_at = timezone.now()
        approval.save(update_fields=["status", "responded_at"])

        all_approved = not document.approvals.filter(
            status=DocumentApprovalStatus.PENDING
        ).exists()

        if all_approved:
            document.workflow_status = DocumentWorkflowStatus.APPROVED
            document.save(update_fields=["workflow_status", "updated_at"])

            # Skapa signeringsposter för ordförande
            chair_memberships = BoardMembership.objects.filter(
                org=document.org,
                is_active=True,
                role=BoardRole.CHAIR,
            ).select_related("user")

            for membership in chair_memberships:
                DocumentSignature.objects.get_or_create(
                    document=document,
                    user=membership.user,
                    role=DocumentSignatureRole.CHAIR,
                    defaults={"status": DocumentSignatureStatus.PENDING},
                )

            # Skapa signeringsposter för sekreterare
            secretary_memberships = BoardMembership.objects.filter(
                org=document.org,
                is_active=True,
                role=BoardRole.SECRETARY,
            ).select_related("user")

            for membership in secretary_memberships:
                DocumentSignature.objects.get_or_create(
                    document=document,
                    user=membership.user,
                    role=DocumentSignatureRole.SECRETARY,
                    defaults={"status": DocumentSignatureStatus.PENDING},
                )

            # Skapa signeringsposter för alla justerare
            for approval_obj in document.approvals.select_related("reviewer").all():
                DocumentSignature.objects.get_or_create(
                    document=document,
                    user=approval_obj.reviewer,
                    role=DocumentSignatureRole.ADJUSTER,
                    defaults={"status": DocumentSignatureStatus.PENDING},
                )

            log_document_activity(
                document=document,
                user=request.user,
                action="updated",
                message="Alla justerare har godkänt dokumentet. Redo för signering.",
            )

            messages.success(
                request,
                "Dokumentet är nu godkänt av alla justerare och redo för signering.",
            )
        else:
            messages.success(request, "Dokumentet har godkänts.")

        return redirect("portal:document_detail", pk=document.pk)

    return render(
        request,
        "portal/document_approval_confirm.html",
        {
            "approval": approval,
            "action_type": "approve",
        },
    )


@login_required
def request_document_changes(request, pk):
    approval = get_object_or_404(
        DocumentApproval.objects.select_related("document"),
        pk=pk,
        reviewer=request.user,
    )

    if request.method == "POST":
        comment = (request.POST.get("comment") or "").strip()

        approval.status = DocumentApprovalStatus.CHANGES_REQUESTED
        approval.comment = comment
        approval.responded_at = timezone.now()
        approval.save(update_fields=["status", "comment", "responded_at"])

        document = approval.document
        document.workflow_status = DocumentWorkflowStatus.UNDER_REVIEW
        document.save(update_fields=["workflow_status", "updated_at"])

        messages.success(request, "Ändringsbegäran har skickats.")
        return redirect("portal:document_detail", pk=document.pk)

    return render(
        request,
        "portal/document_approval_confirm.html",
        {
            "approval": approval,
            "action_type": "changes_requested",
        },
    )


@login_required
def remove_document_reviewer(request, pk):
    approval = get_object_or_404(
        DocumentApproval.objects.select_related("document", "reviewer"),
        pk=pk,
        document__org=request.org,
    )

    document = approval.document

    if document.workflow_status in [
        DocumentWorkflowStatus.APPROVED,
        DocumentWorkflowStatus.FINALIZED,
    ]:
        messages.error(request, "Justerare kan inte tas bort när dokumentet redan är godkänt eller avslutat.")
        return redirect("portal:document_detail", pk=document.pk)

    if approval.status != DocumentApprovalStatus.PENDING:
        messages.error(request, "Du kan bara ta bort justerare som ännu inte har svarat.")
        return redirect("portal:document_detail", pk=document.pk)

    reviewer_name = approval.reviewer.email or approval.reviewer.username

    if request.method == "POST":
        approval.delete()

        remaining_approvals = document.approvals.exists()
        if not remaining_approvals and document.workflow_status == DocumentWorkflowStatus.UNDER_REVIEW:
            document.workflow_status = DocumentWorkflowStatus.LOCKED_FOR_REVIEW
            document.save(update_fields=["workflow_status", "updated_at"])

        messages.success(request, f"Justeraren '{reviewer_name}' har tagits bort.")
        return redirect("portal:document_detail", pk=document.pk)

    return render(
        request,
        "portal/document_remove_reviewer_confirm.html",
        {
            "approval": approval,
            "document": document,
        },
    )


@login_required
def sign_document(request, pk):
    signature = get_object_or_404(
        DocumentSignature.objects.select_related("document", "user"),
        pk=pk,
        user=request.user,
        document__org=request.org,
    )

    document = signature.document

    if document.workflow_status != DocumentWorkflowStatus.APPROVED:
        messages.error(request, "Dokumentet måste vara godkänt innan det kan signeras.")
        return redirect("portal:document_detail", pk=document.pk)

    if request.method == "POST":
        if signature.status == DocumentSignatureStatus.SIGNED:
            messages.warning(request, "Dokumentet är redan signerat av dig.")
            return redirect("portal:document_detail", pk=document.pk)

        signature.status = DocumentSignatureStatus.SIGNED
        signature.signed_at = timezone.now()
        signature.save(update_fields=["status", "signed_at"])

        all_signed = not document.signatures.filter(
            status=DocumentSignatureStatus.PENDING
        ).exists()

        if all_signed:
            document.workflow_status = DocumentWorkflowStatus.FINALIZED
            document.is_archived = True
            document.save(update_fields=["workflow_status", "is_archived", "updated_at"])

            log_document_activity(
                document=document,
                user=request.user,
                action="updated",
                message="Dokumentet är färdigsignerat, finaliserat och arkiverat.",
            )

            messages.success(
                request,
                "Dokumentet är nu färdigsignerat, finaliserat och arkiverat.",
            )
        else:
            messages.success(request, "Dokumentet har signerats.")

        return redirect("portal:document_detail", pk=document.pk)

    return render(
        request,
        "portal/document_sign_confirm.html",
        {
            "signature": signature,
        },
    )
