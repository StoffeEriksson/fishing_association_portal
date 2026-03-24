from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render, redirect

from .forms import BoardMembershipForm
from .models import BoardMembership, GovernanceActivityLog


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

    members = BoardMembership.objects.filter(
        org=request.org
    ).select_related("user").order_by("role", "user__email")

    return render(
        request,
        "governance/board_member_list.html",
        {
            "membership": membership,
            "members": members,
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

