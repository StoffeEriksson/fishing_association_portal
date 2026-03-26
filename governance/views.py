from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render, redirect, get_object_or_404

from .forms import BoardMembershipForm, BoardMatterForm
from .models import BoardMembership, GovernanceActivityLog, BoardMatter


User = get_user_model()


def get_board_membership(request):
    membership = BoardMembership.objects.filter(
        org=request.org,
        user=request.user,
        is_active=True,
    ).first()

    if not membership:
        raise PermissionDenied("Du har inte behörighet att komma åt governance-modulen.")

    return membership


@login_required
def dashboard(request):
    membership = get_board_membership(request)

    log_governance_activity(
        org=request.org,
        user=request.user,
        action="login_access",
        message="Användaren öppnade governance-modulen.",
    )

    return render(
        request,
        "governance/dashboard.html",
        {
            "membership": membership,
        },
    )


@login_required
def board_member_list(request):
    membership = get_board_membership(request)

    status = (request.GET.get("status") or "active").strip()

    members = BoardMembership.objects.filter(
        org=request.org
    ).select_related("user")

    if status == "active":
        members = members.filter(is_active=True)
    elif status == "inactive":
        members = members.filter(is_active=False)
    elif status == "all":
        pass
    else:
        status = "active"
        members = members.filter(is_active=True)

    members = members.order_by("role", "user__email")

    return render(
        request,
        "governance/board_member_list.html",
        {
            "membership": membership,
            "members": members,
            "status": status,
        },
    )


def log_governance_activity(org, user, action, message="", target_user=None):
    GovernanceActivityLog.objects.create(
        org=org,
        user=user,
        action=action,
        message=message,
        target_user=target_user,
    )


@login_required
def activity_log_list(request):
    membership = get_board_membership(request)

    activities = GovernanceActivityLog.objects.filter(
        org=request.org
    ).select_related("user", "target_user").order_by("-created_at")[:100]

    return render(
        request,
        "governance/activity_log_list.html",
        {
            "membership": membership,
            "activities": activities,
        },
    )


@login_required
def board_member_create(request):
    membership = get_board_membership(request)

    if not membership.can_manage_members:
        raise PermissionDenied("Du har inte behörighet att hantera styrelsemedlemmar.")

    if request.method == "POST":
        form = BoardMembershipForm(request.POST)
        if form.is_valid():
            board_member = form.save(commit=False)
            board_member.org = request.org
            board_member.save()

            log_governance_activity(
                org=request.org,
                user=request.user,
                action="member_created",
                message=f"Styrelsemedlem '{board_member.user}' lades till som {board_member.get_role_display()}.",
                target_user=board_member.user,
            )

            messages.success(request, "Styrelsemedlemmen har lagts till.")
            return redirect("governance:board_member_list")
    else:
        form = BoardMembershipForm()

    return render(
        request,
        "governance/board_member_form.html",
        {
            "membership": membership,
            "form": form,
            "page_title": "Lägg till styrelsemedlem",
            "submit_label": "Spara medlem",
        },
    )


@login_required
def board_member_update(request, pk):
    membership = get_board_membership(request)

    if not membership.can_manage_members:
        raise PermissionDenied("Du har inte behörighet att hantera styrelsemedlemmar.")

    board_member = get_object_or_404(
        BoardMembership.objects.filter(org=request.org).select_related("user"),
        pk=pk,
    )

    if request.method == "POST":
        form = BoardMembershipForm(request.POST, instance=board_member)
        if form.is_valid():
            updated_member = form.save()

            log_governance_activity(
                org=request.org,
                user=request.user,
                action="member_updated",
                message=f"Styrelsemedlem '{updated_member.user}' uppdaterades.",
                target_user=updated_member.user,
            )

            messages.success(request, "Styrelsemedlemmen har uppdaterats.")
            return redirect("governance:board_member_list")
    else:
        form = BoardMembershipForm(instance=board_member)

    return render(
        request,
        "governance/board_member_form.html",
        {
            "membership": membership,
            "form": form,
            "board_member": board_member,
            "page_title": "Redigera styrelsemedlem",
            "submit_label": "Spara ändringar",
        },
    )


@login_required
def board_member_deactivate(request, pk):
    membership = get_board_membership(request)

    if not membership.can_manage_members:
        raise PermissionDenied("Du har inte behörighet att hantera styrelsemedlemmar.")

    board_member = get_object_or_404(
        BoardMembership.objects.filter(org=request.org).select_related("user"),
        pk=pk,
    )

    if request.method == "POST":
        board_member.is_active = False
        board_member.save(update_fields=["is_active", "updated_at"])

        log_governance_activity(
            org=request.org,
            user=request.user,
            action="member_updated",
            message=f"Styrelsemedlem '{board_member.user}' markerades som inaktiv.",
            target_user=board_member.user,
        )

        messages.success(request, "Styrelsemedlemmen har markerats som inaktiv.")
        return redirect("governance:board_member_list")

    return render(
        request,
        "governance/board_member_confirm_deactivate.html",
        {
            "membership": membership,
            "board_member": board_member,
        },
    )


@login_required
def matter_list(request):
    membership = get_board_membership(request)

    status = request.GET.get("status", "all")

    matters = BoardMatter.objects.filter(org=request.org)

    if status != "all":
        matters = matters.filter(status=status)

    matters = matters.select_related("assigned_to", "submitted_by").order_by("-created_at")

    return render(
        request,
        "governance/matter_list.html",
        {
            "membership": membership,
            "matters": matters,
            "status": status,
        },
    )


@login_required
def matter_create(request):
    membership = get_board_membership(request)

    if not membership.can_manage_matters:
        raise PermissionDenied("Du har inte behörighet att hantera ärenden.")

    if request.method == "POST":
        form = BoardMatterForm(request.POST)
        form.fields["assigned_to"].queryset = User.objects.filter(
            board_memberships__org=request.org,
            board_memberships__is_active=True,
        ).distinct()

        if form.is_valid():
            matter = form.save(commit=False)
            matter.org = request.org
            matter.submitted_by = request.user
            matter.save()

            log_governance_activity(
                org=request.org,
                user=request.user,
                action="matter_created",
                message=f"Ärendet '{matter.title}' skapades.",
            )

            messages.success(request, "Ärendet har skapats.")
            return redirect("governance:matter_list")
    else:
        form = BoardMatterForm()
        form.fields["assigned_to"].queryset = User.objects.filter(
            board_memberships__org=request.org,
            board_memberships__is_active=True,
        ).distinct()

    return render(
        request,
        "governance/matter_form.html",
        {
            "membership": membership,
            "form": form,
            "page_title": "Skapa ärende",
            "submit_label": "Spara ärende",
        },
    )


@login_required
def matter_detail(request, pk):
    membership = get_board_membership(request)

    matter = get_object_or_404(
        BoardMatter.objects.filter(org=request.org).select_related("assigned_to", "submitted_by"),
        pk=pk,
    )

    return render(
        request,
        "governance/matter_detail.html",
        {
            "membership": membership,
            "matter": matter,
        },
    )


@login_required
def matter_update(request, pk):
    membership = get_board_membership(request)

    if not membership.can_manage_matters:
        raise PermissionDenied("Du har inte behörighet att hantera ärenden.")

    matter = get_object_or_404(
        BoardMatter.objects.filter(org=request.org).select_related("assigned_to", "submitted_by"),
        pk=pk,
    )

    old_status = matter.status
    old_status_display = matter.get_status_display()

    if request.method == "POST":
        form = BoardMatterForm(request.POST, instance=matter)
        form.fields["assigned_to"].queryset = User.objects.filter(
            board_memberships__org=request.org,
            board_memberships__is_active=True,
        ).distinct()

        if form.is_valid():
            updated_matter = form.save()
            new_status_display = updated_matter.get_status_display()

            if old_status != updated_matter.status:
                log_governance_activity(
                    org=request.org,
                    user=request.user,
                    action="matter_status_changed",
                    message=(
                        f"Ärendet '{updated_matter.title}' ändrade status "
                        f"från '{old_status_display}' till '{new_status_display}'."
                    ),
                )
            else:
                log_governance_activity(
                    org=request.org,
                    user=request.user,
                    action="matter_updated",
                    message=f"Ärendet '{updated_matter.title}' uppdaterades.",
                )

            messages.success(request, "Ärendet har uppdaterats.")
            return redirect("governance:matter_detail", pk=updated_matter.pk)
    else:
        form = BoardMatterForm(instance=matter)
        form.fields["assigned_to"].queryset = User.objects.filter(
            board_memberships__org=request.org,
            board_memberships__is_active=True,
        ).distinct()

    return render(
        request,
        "governance/matter_form.html",
        {
            "membership": membership,
            "form": form,
            "matter": matter,
            "page_title": "Redigera ärende",
            "submit_label": "Spara ändringar",
        },
    )


@login_required
def matter_change_status(request, pk, new_status):
    membership = get_board_membership(request)

    if not membership.can_manage_matters:
        raise PermissionDenied("Du har inte behörighet att hantera ärenden.")

    matter = get_object_or_404(
        BoardMatter.objects.filter(org=request.org),
        pk=pk,
    )

    allowed_statuses = {
        "received",
        "in_preparation",
        "ready_for_proposal",
        "ready_for_meeting",
        "decided",
        "closed",
    }

    if new_status not in allowed_statuses:
        raise PermissionDenied("Ogiltig status.")

    old_status_display = matter.get_status_display()
    matter.status = new_status
    matter.ready_for_meeting = new_status == "ready_for_meeting"
    matter.save(update_fields=["status", "ready_for_meeting", "updated_at"])

    new_status_display = matter.get_status_display()

    log_governance_activity(
        org=request.org,
        user=request.user,
        action="matter_status_changed",
        message=(
            f"Ärendet '{matter.title}' ändrade status "
            f"från '{old_status_display}' till '{new_status_display}'."
        ),
    )

    messages.success(request, f"Status uppdaterad till {new_status_display}.")
    return redirect("governance:matter_detail", pk=matter.pk)
