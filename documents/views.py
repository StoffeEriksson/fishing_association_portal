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
)


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
    document = get_object_or_404(
        Document.objects.filter(org=request.org),
        pk=pk,
    )

    if document.workflow_status not in [
        DocumentWorkflowStatus.LOCKED_FOR_REVIEW,
        DocumentWorkflowStatus.UNDER_REVIEW,
    ]:
        messages.error(request, "Justerare kan bara läggas till när dokumentet är låst för justering.")
        return redirect("portal:document_detail", pk=document.pk)

    if request.method == "POST":
        form = DocumentApprovalCreateForm(request.POST)
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
    approval = get_object_or_404(
        DocumentApproval.objects.select_related("document"),
        pk=pk,
        reviewer=request.user,
    )

    if request.method == "POST":
        approval.status = DocumentApprovalStatus.APPROVED
        approval.responded_at = timezone.now()
        approval.save(update_fields=["status", "responded_at"])

        document = approval.document
        pending_exists = document.approvals.filter(
            status=DocumentApprovalStatus.PENDING
        ).exists()
        changes_requested_exists = document.approvals.filter(
            status=DocumentApprovalStatus.CHANGES_REQUESTED
        ).exists()

        if not pending_exists and not changes_requested_exists:
            document.workflow_status = DocumentWorkflowStatus.APPROVED
            document.save(update_fields=["workflow_status", "updated_at"])

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
