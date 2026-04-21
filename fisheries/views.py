from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from maps.models import WaterBody
from core.models import Membership

from .models import (
    ActionArea,
    ActionComment,
    ActionLog,
    ActionPriority,
    ActionStatus,
    Observation,
    ObservationCategory,
    ObservationComment,
    ObservationLog,
    ObservationStatus,
)

User = get_user_model()


@login_required
def action_list(request):
    org = getattr(request, "org", None)
    status_choices = ActionStatus.choices
    valid_status_values = {value for value, _ in status_choices}

    if request.method == "POST":
        action_type = (request.POST.get("action_type") or "").strip()
        if action_type == "update_status_inline" and org is not None:
            action_id = (request.POST.get("action_id") or "").strip()
            new_status = (request.POST.get("status") or "").strip()
            action = ActionArea.objects.for_org(org).filter(pk=action_id, is_active=True).first()
            if action and new_status in valid_status_values and new_status != action.status:
                old_status = action.status
                action.status = new_status
                action.updated_by = request.user
                action.save(update_fields=["status", "updated_by", "updated_at"])
                ActionLog.objects.create(
                    org=request.org,
                    action_area=action,
                    user=request.user,
                    event_type="status_changed",
                    message="Status uppdaterad via lista",
                    from_status=old_status,
                    to_status=new_status,
                )
        return redirect("fisheries:action_list")

    selected_status = (request.GET.get("status") or "").strip()
    search_query = (request.GET.get("q") or "").strip()
    selected_sort = (request.GET.get("sort") or "").strip()
    allowed_sort_values = {
        "created_desc": "-created_at",
        "created_asc": "created_at",
        "deadline_asc": "deadline",
        "priority": "priority",
        "status": "status",
    }

    if org is None:
        actions = ActionArea.objects.none()
        selected_status = ""
        search_query = ""
        selected_sort = "created_desc"
    else:
        actions = (
            ActionArea.objects.for_org(org)
            .filter(is_active=True)
            .select_related("created_by", "updated_by")
        )
        if selected_status in valid_status_values:
            actions = actions.filter(status=selected_status)
        else:
            selected_status = ""
        if search_query:
            actions = actions.filter(
                Q(name__icontains=search_query) | Q(description__icontains=search_query)
            )
        if selected_sort not in allowed_sort_values:
            selected_sort = "created_desc"
        actions = actions.order_by(allowed_sort_values[selected_sort])

    return render(
        request,
        "fisheries/action_list.html",
        {
            "actions": actions,
            "selected_status": selected_status,
            "search_query": search_query,
            "selected_sort": selected_sort,
            "status_choices": status_choices,
        },
    )


@login_required
def action_board(request):
    org = getattr(request, "org", None)

    if org is None:
        urgent_actions = ActionArea.objects.none()
        needs_action_actions = ActionArea.objects.none()
        planned_actions = ActionArea.objects.none()
        in_progress_actions = ActionArea.objects.none()
        completed_actions = ActionArea.objects.none()
    else:
        base_qs = (
            ActionArea.objects.for_org(org)
            .filter(is_active=True)
            .select_related("responsible_user")
        )
        urgent_actions = base_qs.filter(status=ActionStatus.URGENT).order_by("-created_at")
        needs_action_actions = base_qs.filter(status=ActionStatus.NEEDS_ACTION).order_by("-created_at")
        planned_actions = base_qs.filter(status=ActionStatus.PLANNED).order_by("-created_at")
        in_progress_actions = base_qs.filter(status=ActionStatus.IN_PROGRESS).order_by("-created_at")
        completed_actions = base_qs.filter(status=ActionStatus.COMPLETED).order_by("-created_at")

    return render(
        request,
        "fisheries/action_board.html",
        {
            "urgent_actions": urgent_actions,
            "needs_action_actions": needs_action_actions,
            "planned_actions": planned_actions,
            "in_progress_actions": in_progress_actions,
            "completed_actions": completed_actions,
        },
    )


@login_required
def action_create(request):
    org = getattr(request, "org", None)
    if org is None:
        return redirect("fisheries:action_list")

    water_bodies = WaterBody.objects.for_org(org).filter(is_active=True).order_by("name")
    priority_choices = ActionPriority.choices
    valid_priority_values = {value for value, _ in priority_choices}

    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        description = (request.POST.get("description") or "").strip()
        water_body_id = (request.POST.get("water_body") or "").strip()
        priority = (request.POST.get("priority") or "").strip()
        deadline = (request.POST.get("deadline") or "").strip()

        if not name:
            return render(
                request,
                "fisheries/action_create.html",
                {
                    "water_bodies": water_bodies,
                    "priority_choices": priority_choices,
                    "error": "Namn är obligatoriskt.",
                    "form_data": {
                        "name": name,
                        "description": description,
                        "water_body": water_body_id,
                        "priority": priority,
                        "deadline": deadline,
                    },
                },
            )

        water_body = None
        if water_body_id:
            water_body = WaterBody.objects.for_org(org).filter(pk=water_body_id).first()

        if priority not in valid_priority_values:
            priority = ActionPriority.MEDIUM

        action = ActionArea.objects.create(
            org=request.org,
            name=name,
            description=description,
            water_body=water_body,
            priority=priority,
            deadline=deadline or None,
            created_by=request.user,
            updated_by=request.user,
            status=ActionStatus.NEEDS_ACTION,
        )
        ActionLog.objects.create(
            org=request.org,
            action_area=action,
            user=request.user,
            event_type="created",
            message="Åtgärd skapad",
        )
        return redirect("fisheries:action_detail", pk=action.pk)

    return render(
        request,
        "fisheries/action_create.html",
        {
            "water_bodies": water_bodies,
            "priority_choices": priority_choices,
            "form_data": {},
        },
    )


@login_required
def observation_list(request):
    org = getattr(request, "org", None)
    status_choices = ObservationStatus.choices
    valid_status_values = {value for value, _ in status_choices}

    if request.method == "POST":
        action_type = (request.POST.get("action_type") or "").strip()
        if action_type == "update_status_inline" and org is not None:
            observation_id = (request.POST.get("observation_id") or "").strip()
            new_status = (request.POST.get("status") or "").strip()
            observation = Observation.objects.for_org(org).filter(pk=observation_id, is_active=True).first()
            if observation and new_status in valid_status_values and new_status != observation.status:
                observation.status = new_status
                observation.updated_by = request.user
                observation.save(update_fields=["status", "updated_by", "updated_at"])
                ObservationLog.objects.create(
                    org=request.org,
                    observation=observation,
                    user=request.user,
                    event_type="status_changed",
                    message="Status uppdaterad via lista",
                )
        return redirect("fisheries:observation_list")

    selected_status = (request.GET.get("status") or "").strip()
    search_query = (request.GET.get("q") or "").strip()
    selected_sort = (request.GET.get("sort") or "").strip()
    allowed_sort_values = {
        "created_desc": "-created_at",
        "created_asc": "created_at",
        "status": "status",
        "category": "category",
    }

    if org is None:
        observations = Observation.objects.none()
        selected_status = ""
        search_query = ""
        selected_sort = "created_desc"
    else:
        observations = (
            Observation.objects.for_org(org)
            .filter(is_active=True)
            .select_related("water_body", "linked_action", "created_by", "updated_by")
        )
        if selected_status in valid_status_values:
            observations = observations.filter(status=selected_status)
        else:
            selected_status = ""
        if search_query:
            observations = observations.filter(
                Q(title__icontains=search_query) | Q(description__icontains=search_query)
            )
        if selected_sort not in allowed_sort_values:
            selected_sort = "created_desc"
        observations = observations.order_by(allowed_sort_values[selected_sort])

    return render(
        request,
        "fisheries/observation_list.html",
        {
            "observations": observations,
            "selected_status": selected_status,
            "search_query": search_query,
            "selected_sort": selected_sort,
            "status_choices": status_choices,
        },
    )


@login_required
def observation_create(request):
    org = getattr(request, "org", None)
    if org is None:
        return redirect("fisheries:observation_list")

    water_bodies = WaterBody.objects.for_org(org).filter(is_active=True).order_by("name")
    category_choices = Observation._meta.get_field("category").choices
    valid_category_values = {value for value, _ in category_choices}

    if request.method == "POST":
        title = (request.POST.get("title") or "").strip()
        category = (request.POST.get("category") or "").strip()
        description = (request.POST.get("description") or "").strip()
        water_body_id = (request.POST.get("water_body") or "").strip()

        if not title:
            return render(
                request,
                "fisheries/observation_create.html",
                {
                    "water_bodies": water_bodies,
                    "category_choices": category_choices,
                    "error": "Titel är obligatorisk.",
                    "form_data": {
                        "title": title,
                        "category": category,
                        "description": description,
                        "water_body": water_body_id,
                    },
                },
            )

        if category not in valid_category_values:
            category = ObservationCategory.OTHER

        water_body = None
        if water_body_id:
            water_body = WaterBody.objects.for_org(org).filter(pk=water_body_id).first()

        observation = Observation.objects.create(
            org=request.org,
            title=title,
            category=category,
            water_body=water_body,
            description=description,
            status=ObservationStatus.NEW,
            created_by=request.user,
            updated_by=request.user,
        )
        ObservationLog.objects.create(
            org=request.org,
            observation=observation,
            user=request.user,
            event_type="created",
            message="Observation skapad",
        )
        return redirect("fisheries:observation_detail", pk=observation.pk)

    return render(
        request,
        "fisheries/observation_create.html",
        {
            "water_bodies": water_bodies,
            "category_choices": category_choices,
            "form_data": {},
        },
    )


@login_required
def overview(request):
    org = getattr(request, "org", None)
    today = timezone.localdate()

    if org is None:
        total_observations = 0
        new_observations = 0
        under_review_observations = 0
        linked_observations = 0

        total_actions = 0
        urgent_actions = 0
        planned_actions = 0
        in_progress_actions = 0
        completed_actions = 0

        actions_without_responsible = 0
        overdue_actions = 0
        actions_without_water = 0

        latest_observations = Observation.objects.none()
        latest_actions = ActionArea.objects.none()
        urgent_actions_list = ActionArea.objects.none()
        overdue_actions_list = ActionArea.objects.none()
        unassigned_actions_list = ActionArea.objects.none()
    else:
        observation_qs = Observation.objects.for_org(org).filter(is_active=True)
        action_qs = ActionArea.objects.for_org(org).filter(is_active=True)

        total_observations = observation_qs.count()
        new_observations = observation_qs.filter(status=ObservationStatus.NEW).count()
        under_review_observations = observation_qs.filter(status=ObservationStatus.UNDER_REVIEW).count()
        linked_observations = observation_qs.filter(status=ObservationStatus.LINKED_TO_ACTION).count()

        total_actions = action_qs.count()
        urgent_actions = action_qs.filter(status=ActionStatus.URGENT).count()
        planned_actions = action_qs.filter(status=ActionStatus.PLANNED).count()
        in_progress_actions = action_qs.filter(status=ActionStatus.IN_PROGRESS).count()
        completed_actions = action_qs.filter(status=ActionStatus.COMPLETED).count()

        actions_without_responsible = action_qs.filter(responsible_user__isnull=True).count()
        overdue_actions = action_qs.filter(deadline__isnull=False, deadline__lt=today).count()
        actions_without_water = action_qs.filter(water_body__isnull=True).count()

        latest_observations = observation_qs.select_related("water_body", "linked_action").order_by("-created_at")[:5]
        latest_actions = action_qs.select_related("water_body", "responsible_user").order_by("-created_at")[:5]
        urgent_actions_list = action_qs.filter(status=ActionStatus.URGENT).order_by("-created_at")[:5]
        overdue_actions_list = action_qs.filter(deadline__isnull=False, deadline__lt=today).order_by("deadline")[:5]
        unassigned_actions_list = action_qs.filter(responsible_user__isnull=True).order_by("-created_at")[:5]

    return render(
        request,
        "fisheries/overview.html",
        {
            "total_observations": total_observations,
            "new_observations": new_observations,
            "under_review_observations": under_review_observations,
            "linked_observations": linked_observations,
            "total_actions": total_actions,
            "urgent_actions": urgent_actions,
            "planned_actions": planned_actions,
            "in_progress_actions": in_progress_actions,
            "completed_actions": completed_actions,
            "actions_without_responsible": actions_without_responsible,
            "overdue_actions": overdue_actions,
            "actions_without_water": actions_without_water,
            "latest_observations": latest_observations,
            "latest_actions": latest_actions,
            "urgent_actions_list": urgent_actions_list,
            "overdue_actions_list": overdue_actions_list,
            "unassigned_actions_list": unassigned_actions_list,
        },
    )


@login_required
def observation_detail(request, pk):
    org = getattr(request, "org", None)
    status_choices = Observation._meta.get_field("status").choices
    valid_status_values = {value for value, _ in status_choices}
    status_labels = {value: label for value, label in status_choices}
    category_choices = ObservationCategory.choices
    valid_category_values = {value for value, _ in category_choices}
    water_bodies = WaterBody.objects.for_org(org).filter(is_active=True).order_by("name")
    observation = get_object_or_404(
        Observation.objects.for_org(org).select_related(
            "water_body",
            "linked_action",
            "created_by",
            "updated_by",
        ),
        pk=pk,
    )

    if request.method == "POST":
        action_type = (request.POST.get("action_type") or "").strip()

        if action_type == "change_status":
            new_status = (request.POST.get("status") or "").strip()
            if new_status in valid_status_values and new_status != observation.status:
                old_status = observation.status
                old_label = status_labels.get(old_status, old_status)
                new_label = status_labels.get(new_status, new_status)

                observation.status = new_status
                observation.updated_by = request.user
                observation.save(update_fields=["status", "updated_by", "updated_at"])

                ObservationLog.objects.create(
                    org=request.org,
                    observation=observation,
                    user=request.user,
                    event_type="status_changed",
                    message=f"Status ändrad från {old_label} till {new_label}",
                )

        elif action_type == "update_fields":
            category = (request.POST.get("category") or "").strip()
            water_body_id = (request.POST.get("water_body") or "").strip()
            description = (request.POST.get("description") or "").strip()

            if category not in valid_category_values:
                category = observation.category

            water_body = None
            if water_body_id:
                water_body = WaterBody.objects.for_org(org).filter(pk=water_body_id).first()

            observation.category = category
            observation.water_body = water_body
            observation.description = description
            observation.updated_by = request.user
            observation.save(update_fields=["category", "water_body", "description", "updated_by", "updated_at"])

            ObservationLog.objects.create(
                org=request.org,
                observation=observation,
                user=request.user,
                event_type="updated",
                message="Observation uppdaterad",
            )

        elif action_type == "add_comment":
            body = (request.POST.get("body") or "").strip()
            if body:
                ObservationComment.objects.create(
                    org=request.org,
                    observation=observation,
                    user=request.user,
                    body=body,
                )
                ObservationLog.objects.create(
                    org=request.org,
                    observation=observation,
                    user=request.user,
                    event_type="comment_added",
                    message="Kommentar tillagd",
                )
        return redirect("fisheries:observation_detail", pk=observation.pk)

    comments = observation.comments.select_related("user").order_by("-created_at")
    logs = observation.logs.select_related("user").order_by("-created_at")

    return render(
        request,
        "fisheries/observation_detail.html",
        {
            "observation": observation,
            "comments": comments,
            "logs": logs,
            "status_choices": status_choices,
            "category_choices": category_choices,
            "water_bodies": water_bodies,
        },
    )


@login_required
def create_action_from_observation(request, pk):
    org = getattr(request, "org", None)
    if org is None:
        return redirect("fisheries:observation_list")

    if request.method != "POST":
        return redirect("fisheries:observation_list")

    observation = get_object_or_404(
        Observation.objects.for_org(org).select_related("linked_action", "water_body"),
        pk=pk,
    )

    if observation.linked_action_id:
        return redirect("fisheries:action_detail", pk=observation.linked_action_id)

    action = ActionArea.objects.create(
        org=request.org,
        name=observation.title,
        description=observation.description,
        water_body=observation.water_body,
        created_by=request.user,
        updated_by=request.user,
        status=ActionStatus.NEEDS_ACTION,
    )

    observation.linked_action = action
    observation.updated_by = request.user
    observation.status = ObservationStatus.LINKED_TO_ACTION
    observation.save(update_fields=["linked_action", "updated_by", "status", "updated_at"])

    ObservationLog.objects.create(
        org=request.org,
        observation=observation,
        user=request.user,
        event_type="linked_to_action",
        message=f"Kopplad till åtgärd: {action.name}",
    )

    ActionLog.objects.create(
        org=request.org,
        action_area=action,
        user=request.user,
        event_type="created_from_observation",
        message=f"Åtgärd skapad från observation: {observation.title}",
    )

    return redirect("fisheries:action_detail", pk=action.pk)


@login_required
def action_detail(request, pk):
    org = getattr(request, "org", None)
    status_choices = ActionArea._meta.get_field("status").choices
    valid_status_values = {value for value, _ in status_choices}
    status_labels = {value: label for value, label in status_choices}
    priority_choices = ActionPriority.choices
    valid_priority_values = {value for value, _ in priority_choices}
    responsible_users = (
        User.objects.filter(
            membership__organization=org,
            membership__is_active=True,
        )
        .distinct()
        .order_by("email", "username")
    )

    action = get_object_or_404(
        ActionArea.objects.for_org(org)
        .select_related("created_by", "updated_by", "water_body", "responsible_user"),
        pk=pk,
    )

    if request.method == "POST":
        action_type = (request.POST.get("action_type") or "").strip()

        if action_type == "change_status":
            new_status = (request.POST.get("status") or "").strip()
            if new_status in valid_status_values and new_status != action.status:
                old_status = action.status
                old_label = status_labels.get(old_status, old_status)
                new_label = status_labels.get(new_status, new_status)

                action.status = new_status
                action.updated_by = request.user
                action.save(update_fields=["status", "updated_by", "updated_at"])

                ActionLog.objects.create(
                    org=request.org,
                    action_area=action,
                    user=request.user,
                    event_type="status_changed",
                    message=f"Status ändrad från {old_label} till {new_label}",
                    from_status=old_status,
                    to_status=new_status,
                )

        elif action_type == "add_comment":
            body = (request.POST.get("body") or "").strip()
            if body:
                ActionComment.objects.create(
                    org=request.org,
                    action_area=action,
                    user=request.user,
                    body=body,
                )
                ActionLog.objects.create(
                    org=request.org,
                    action_area=action,
                    user=request.user,
                    event_type="comment_added",
                    message="Kommentar tillagd",
                )

        elif action_type == "update_fields":
            responsible_user_id = (request.POST.get("responsible_user") or "").strip()
            priority = (request.POST.get("priority") or "").strip()
            deadline = (request.POST.get("deadline") or "").strip()

            old_responsible = action.responsible_user
            old_priority = action.priority
            old_deadline = action.deadline

            new_responsible = None
            if responsible_user_id:
                new_responsible = responsible_users.filter(pk=responsible_user_id).first()

            if priority not in valid_priority_values:
                priority = action.priority

            action.responsible_user = new_responsible
            action.priority = priority
            action.deadline = deadline or None
            action.updated_by = request.user
            action.save(update_fields=["responsible_user", "priority", "deadline", "updated_by", "updated_at"])

            if (
                old_responsible != action.responsible_user
                or old_priority != action.priority
                or old_deadline != action.deadline
            ):
                ActionLog.objects.create(
                    org=request.org,
                    action_area=action,
                    user=request.user,
                    event_type="updated",
                    message="Fält uppdaterade (ansvarig/prioritet/deadline)",
                )

        return redirect("fisheries:action_detail", pk=action.pk)

    comments = action.comments.select_related("user").order_by("-created_at")
    logs = action.logs.select_related("user").order_by("-created_at")

    return render(
        request,
        "fisheries/action_detail.html",
        {
            "action": action,
            "comments": comments,
            "logs": logs,
            "status_choices": status_choices,
            "priority_choices": priority_choices,
            "responsible_users": responsible_users,
        },
    )
