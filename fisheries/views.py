from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.db.models import F, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from maps.models import WaterBody
from core.models import Membership

from .labels import (
    get_action_priority_label,
    get_action_status_label,
    get_observation_category_label,
    get_observation_status_label,
)
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

_MONTHS_SV = (
    "jan",
    "feb",
    "mar",
    "apr",
    "maj",
    "jun",
    "jul",
    "aug",
    "sep",
    "okt",
    "nov",
    "dec",
)

_ATTENTION_NEXT_STEP_BY_RANK = {
    0: "Nästa steg: Uppdatera planen",
    1: "Nästa steg: Ta upp i styrelsen",
    2: "Nästa steg: Kontrollera läget",
    3: "Nästa steg: Tilldela ansvarig",
    4: "Nästa steg: Besluta om åtgärd",
}


def _format_short_date(value):
    return f"{value.day} {_MONTHS_SV[value.month - 1]}"


def _user_display_name(user):
    if not user:
        return None
    full_name = (user.get_full_name() or "").strip()
    if full_name:
        return full_name
    return user.email or user.get_username()


def _attention_rank_for_action(action, today, week_end):
    if action.deadline and action.deadline < today:
        return 0, "FÖRSENAD", "ccv2-priority-critical"
    if action.status == ActionStatus.URGENT:
        return 1, "AKUT", "ccv2-priority-critical"
    if action.deadline and today <= action.deadline <= week_end:
        return 2, "DEADLINE SNART", "ccv2-priority-deadline"
    if action.responsible_user_id is None:
        return 3, "SAKNAR ANSVARIG", "ccv2-priority-high"
    if action.status == ActionStatus.NEEDS_ACTION:
        return 4, "BEHÖVER BESLUT", "ccv2-priority-normal"
    return None


def _build_action_meta_badges(action):
    badges = []
    if action.deadline:
        badges.append(
            {
                "icon": "fa-calendar",
                "label": _format_short_date(action.deadline),
            }
        )
    if action.responsible_user:
        badges.append(
            {
                "icon": "fa-user",
                "label": _user_display_name(action.responsible_user),
            }
        )
    else:
        badges.append(
            {
                "icon": "fa-user",
                "label": "Saknar ansvarig",
                "muted": True,
            }
        )
    if action.status in (ActionStatus.NEEDS_ACTION, ActionStatus.URGENT):
        badges.append(
            {
                "icon": "fa-scale-balanced",
                "label": "Beslut krävs",
            }
        )
    elif action.status not in (ActionStatus.COMPLETED,):
        badges.append(
            {
                "icon": "fa-circle-info",
                "label": get_action_status_label(action.status),
            }
        )
    if action.water_body:
        badges.append(
            {
                "icon": "fa-water",
                "label": action.water_body.name,
            }
        )
    return badges


def _actions_with_status_label(actions):
    return [
        {
            "action": action,
            "status_label": get_action_status_label(action.status),
        }
        for action in actions
    ]


def _build_attention_items(active_actions, today, week_end):
    items_by_pk = {}
    for action in active_actions:
        ranked = _attention_rank_for_action(action, today, week_end)
        if ranked is None:
            continue
        rank, label, priority_class = ranked
        existing = items_by_pk.get(action.pk)
        if existing is not None and existing["rank"] <= rank:
            continue
        items_by_pk[action.pk] = {
            "action": action,
            "rank": rank,
            "label": label,
            "priority_class": priority_class,
            "meta_badges": _build_action_meta_badges(action),
            "next_step_text": _ATTENTION_NEXT_STEP_BY_RANK[rank],
            "url": reverse("fisheries:action_detail", args=[action.pk]),
        }

    def sort_key(item):
        action = item["action"]
        deadline_ord = action.deadline.toordinal() if action.deadline else date.max.toordinal()
        return (item["rank"], deadline_ord, action.created_at)

    sorted_items = sorted(items_by_pk.values(), key=sort_key)
    return sorted_items[:8], len(items_by_pk)


_FISHERIES_FLOW_LABELS = ("Beslut", "Planerad", "Pågår", "Klar / Uppföljning")

_PRIORITY_BADGE_ICONS = {
    ActionPriority.LOW: "fa-arrow-down",
    ActionPriority.MEDIUM: "fa-minus",
    ActionPriority.HIGH: "fa-arrow-up",
    ActionPriority.CRITICAL: "fa-fire",
}


def _flow_active_index(status):
    if status == ActionStatus.COMPLETED:
        return 4
    if status == ActionStatus.IN_PROGRESS:
        return 2
    if status == ActionStatus.PLANNED:
        return 1
    if status in (ActionStatus.NEEDS_ACTION, ActionStatus.URGENT):
        return 0
    return 0


def _build_fisheries_flow_steps(status):
    active_index = _flow_active_index(status)
    steps = []
    for index, label in enumerate(_FISHERIES_FLOW_LABELS):
        if active_index >= 4:
            state = "done"
        elif index < active_index:
            state = "done"
        elif index == active_index:
            state = "active"
        else:
            state = "pending"
        steps.append({"label": label, "state": state})
    return steps


def _build_action_header_badges(action):
    badges = [
        {
            "icon": _PRIORITY_BADGE_ICONS.get(action.priority, "fa-minus"),
            "label": get_action_priority_label(action.priority),
            "emphasis": action.priority in (ActionPriority.HIGH, ActionPriority.CRITICAL),
        },
        {
            "icon": "fa-circle-dot",
            "label": get_action_status_label(action.status),
        },
    ]
    if action.water_body:
        badges.append({"icon": "fa-water", "label": action.water_body.name})
    if action.responsible_user:
        badges.append({"icon": "fa-user", "label": _user_display_name(action.responsible_user)})
    else:
        badges.append({"icon": "fa-user", "label": "Ingen ansvarig", "muted": True})
    if action.status in (ActionStatus.NEEDS_ACTION, ActionStatus.URGENT):
        badges.append({"icon": "fa-scale-balanced", "label": "Beslut krävs"})
    return badges


def _build_action_next_step(action, today):
    week_end = today + timedelta(days=7)
    status_label = get_action_status_label(action.status)

    if action.status == ActionStatus.COMPLETED:
        return {
            "title": "Nästa steg",
            "body": "Åtgärden är genomförd.",
            "pill_label": status_label,
            "pill_class": "fv-next-pill--done",
            "cta_label": None,
            "cta_href": None,
        }

    if not action.responsible_user_id:
        return {
            "title": "Nästa steg",
            "body": "Tilldela ansvarig för att komma vidare.",
            "pill_label": "Saknar ansvarig",
            "pill_class": "fv-next-pill--warn",
            "cta_label": "Tilldela ansvarig",
            "cta_href": "#fv-manage-insats",
        }

    if action.deadline and action.deadline < today:
        return {
            "title": "Nästa steg",
            "body": "Åtgärden behöver uppdateras eller planeras om.",
            "pill_label": "Försenad",
            "pill_class": "fv-next-pill--critical",
            "cta_label": "Uppdatera plan",
            "cta_href": "#fv-manage-insats",
        }

    if action.status == ActionStatus.URGENT:
        return {
            "title": "Nästa steg",
            "body": "Den här åtgärden kräver uppmärksamhet nu.",
            "pill_label": status_label,
            "pill_class": "fv-next-pill--critical",
            "cta_label": "Uppdatera status",
            "cta_href": "#fv-manage-insats",
        }

    if action.status == ActionStatus.NEEDS_ACTION:
        return {
            "title": "Nästa steg",
            "body": "Ta upp frågan på nästa styrelsemöte.",
            "pill_label": status_label,
            "pill_class": "fv-next-pill--decision",
            "cta_label": "Uppdatera status",
            "cta_href": "#fv-manage-insats",
        }

    if action.deadline and today <= action.deadline <= week_end:
        return {
            "title": "Nästa steg",
            "body": "Kontrollera att arbetet går enligt plan.",
            "pill_label": f"Deadline {_format_short_date(action.deadline)}",
            "pill_class": "fv-next-pill--deadline",
            "cta_label": "Uppdatera plan",
            "cta_href": "#fv-manage-insats",
        }

    if action.status == ActionStatus.IN_PROGRESS:
        body = "Fortsätt arbetet och följ upp läget i vattnet."
    elif action.status == ActionStatus.PLANNED:
        body = "Förbered insatsen inför genomförande."
    else:
        body = "Fortsätt driva insatsen framåt."

    return {
        "title": "Nästa steg",
        "body": body,
        "pill_label": status_label,
        "pill_class": "fv-next-pill--neutral",
        "cta_label": None,
        "cta_href": None,
    }


def _humanize_action_log(log):
    user = _user_display_name(log.user) or "Någon"
    if log.event_type == "comment_added":
        return f"{user} lade till en anteckning"
    if log.event_type == "status_changed":
        if log.to_status:
            return f"{user} satte status till {get_action_status_label(log.to_status)}"
        if log.message:
            return f"{user} {log.message[0].lower()}{log.message[1:]}"
    if log.event_type == "updated":
        return f"{user} uppdaterade insatsen"
    if log.message:
        return f"{user}: {log.message}"
    return f"{user} registrerade aktivitet"


def _build_activity_feed(logs, comments):
    items = []
    for log in logs:
        items.append(
            {
                "created_at": log.created_at,
                "text": _humanize_action_log(log),
                "detail": None,
            }
        )
    for comment in comments:
        author = _user_display_name(comment.user) or "Någon"
        items.append(
            {
                "created_at": comment.created_at,
                "text": f"{author} lade till en anteckning",
                "detail": comment.body,
            }
        )
    items.sort(key=lambda row: row["created_at"], reverse=True)
    return items[:25]


def _build_action_blockers(action, comment_count):
    blockers = []
    if not action.responsible_user_id:
        blockers.append({"icon": "fa-user", "text": "Ansvarig saknas", "kind": "warn"})
    if not action.deadline:
        blockers.append({"icon": "fa-calendar", "text": "Ingen tidsplan satt", "kind": "neutral"})
    if comment_count == 0:
        blockers.append({"icon": "fa-comment", "text": "Inga anteckningar ännu", "kind": "neutral"})
    if not action.water_body_id:
        blockers.append({"icon": "fa-water", "text": "Inget vattendrag kopplat", "kind": "neutral"})
    if not (action.description or "").strip():
        blockers.append({"icon": "fa-file-lines", "text": "Ingen beskrivning av insatsen", "kind": "neutral"})
    return blockers


_OBSERVATION_STATUS_ORDER = (
    ObservationStatus.NEW,
    ObservationStatus.UNDER_REVIEW,
    ObservationStatus.LINKED_TO_ACTION,
    ObservationStatus.CLOSED,
)

_EMPTY_ACTION_GEOJSON = {"type": "FeatureCollection", "features": []}

_OBSERVATION_PROCESS_LABELS = ("Observation", "Granskning", "Beslut", "Insats")

_OBSERVATION_IMPORTANCE_BY_CATEGORY = {
    ObservationCategory.FISH_STOCK: (
        "Observationer om fiskbestånd hjälper styrelsen att följa utvecklingen i vattnen över tid."
    ),
    ObservationCategory.HABITAT: (
        "Habitatobservationer kan vara viktiga underlag för framtida fiskevårdsinsatser."
    ),
    ObservationCategory.WATER_QUALITY: (
        "Vattenkvalitet kan påverka fiskbestånd och bör dokumenteras tydligt."
    ),
    ObservationCategory.ILLEGAL_FISHING: (
        "Observationer om misstänkt tjuvfiske bör följas upp snabbt eftersom de kan "
        "påverka både fiskbestånd och förtroende för förvaltningen."
    ),
    ObservationCategory.INFRASTRUCTURE: (
        "Observationer om anläggningar och infrastruktur hjälper styrelsen att upptäcka "
        "behov av underhåll eller åtgärder."
    ),
    ObservationCategory.FISH_DEATH: (
        "Fiskdöd bör dokumenteras och följas upp skyndsamt eftersom det kan tyda på "
        "större problem i vattnet."
    ),
    ObservationCategory.ENVIRONMENT: (
        "Miljö- och nedskräpningsobservationer hjälper föreningen att skydda vattenmiljön "
        "och prioritera åtgärder."
    ),
    ObservationCategory.WATER_LEVEL: (
        "Förändringar i vattennivå eller erosion kan påverka både habitat, tillgänglighet "
        "och framtida fiskevårdsinsatser."
    ),
    ObservationCategory.MEMBER_SUGGESTION: (
        "Förslag från medlemmar kan vara viktiga signaler om behov eller förbättringar i området."
    ),
    ObservationCategory.NEEDS_ACTION: (
        "Observationen pekar på något som kan behöva beslut eller åtgärd från styrelsen."
    ),
    ObservationCategory.OTHER: (
        "Observationen hjälper styrelsen att fånga upp signaler från fältet och bedöma "
        "om en insats behövs."
    ),
}


def _observation_process_active_index(status):
    if status == ObservationStatus.CLOSED:
        return 4
    if status == ObservationStatus.LINKED_TO_ACTION:
        return 3
    if status == ObservationStatus.UNDER_REVIEW:
        return 1
    if status == ObservationStatus.NEW:
        return 0
    return 0


def _build_observation_process_steps(status):
    active_index = _observation_process_active_index(status)
    labels = list(_OBSERVATION_PROCESS_LABELS)
    if status == ObservationStatus.CLOSED:
        labels[-1] = "Klar / Avslutad"

    steps = []
    for index, label in enumerate(labels):
        if active_index >= 4:
            state = "done"
        elif index < active_index:
            state = "done"
        elif index == active_index:
            state = "active"
        else:
            state = "pending"
        steps.append({"label": label, "state": state})
    return steps


def _build_observation_importance_text(observation):
    return _OBSERVATION_IMPORTANCE_BY_CATEGORY.get(
        observation.category,
        _OBSERVATION_IMPORTANCE_BY_CATEGORY[ObservationCategory.OTHER],
    )


def _build_observation_next_step(observation):
    status_label = get_observation_status_label(observation.status)

    if observation.status == ObservationStatus.CLOSED:
        return {
            "title": "Nästa steg",
            "body": "Observationen är avslutad och kräver ingen åtgärd.",
            "pill_label": status_label,
            "pill_class": "fv-next-pill--done",
            "ctas": [],
        }

    if observation.status == ObservationStatus.LINKED_TO_ACTION and observation.linked_action_id:
        return {
            "title": "Nästa steg",
            "body": "Observationen är kopplad till en insats och kan följas där.",
            "pill_label": status_label,
            "pill_class": "fv-next-pill--neutral",
            "ctas": [
                {
                    "label": "Öppna åtgärd",
                    "kind": "link",
                    "url": reverse("fisheries:action_detail", args=[observation.linked_action_id]),
                },
            ],
        }

    if observation.status == ObservationStatus.UNDER_REVIEW:
        ctas = [
            {
                "label": "Skapa åtgärd",
                "kind": "create_action",
                "url": reverse("fisheries:create_action_from_observation", args=[observation.pk]),
            },
            {
                "label": "Avsluta utan åtgärd",
                "kind": "change_status",
                "status": ObservationStatus.CLOSED,
            },
        ]
        return {
            "title": "Nästa steg",
            "body": "Avgör om observationen ska bli en fiskevårdsinsats.",
            "pill_label": status_label,
            "pill_class": "fv-next-pill--decision",
            "ctas": ctas,
        }

    if observation.status == ObservationStatus.NEW:
        ctas = [
            {
                "label": "Markera under granskning",
                "kind": "change_status",
                "status": ObservationStatus.UNDER_REVIEW,
            },
            {
                "label": "Skapa åtgärd",
                "kind": "create_action",
                "url": reverse("fisheries:create_action_from_observation", args=[observation.pk]),
            },
        ]
        return {
            "title": "Nästa steg",
            "body": "Granska signalen från fältet och avgör om styrelsen behöver agera.",
            "pill_label": status_label,
            "pill_class": "fv-next-pill--neutral",
            "ctas": ctas,
        }

    return {
        "title": "Nästa steg",
        "body": "Fortsätt hantera observationen.",
        "pill_label": status_label,
        "pill_class": "fv-next-pill--neutral",
        "ctas": [],
    }


def _build_observation_header_badges(observation):
    badges = [
        {
            "icon": "fa-circle-dot",
            "label": get_observation_status_label(observation.status),
        },
        {
            "icon": "fa-tag",
            "label": get_observation_category_label(observation.category),
        },
    ]
    if observation.water_body:
        badges.append({"icon": "fa-water", "label": observation.water_body.name})
    else:
        badges.append({"icon": "fa-water", "label": "Vattendrag saknas", "muted": True})
    return badges


def _humanize_observation_log(log):
    user = _user_display_name(log.user) or "Någon"
    if log.event_type == "comment_added":
        return f"{user} lade till en anteckning"
    if log.event_type == "status_changed":
        return f"{user} uppdaterade status"
    if log.event_type == "linked_to_action":
        return f"{user} kopplade observationen till en åtgärd"
    if log.event_type == "updated":
        return f"{user} uppdaterade observationen"
    if log.message:
        return f"{user}: {log.message}"
    return f"{user} registrerade aktivitet"


def _build_observation_activity_feed(logs, comments):
    items = []
    for log in logs:
        items.append(
            {
                "created_at": log.created_at,
                "text": _humanize_observation_log(log),
                "detail": log.message if log.event_type != "comment_added" else None,
            }
        )
    for comment in comments:
        author = _user_display_name(comment.user) or "Någon"
        items.append(
            {
                "created_at": comment.created_at,
                "text": f"{author} lade till en anteckning",
                "detail": comment.body,
            }
        )
    items.sort(key=lambda row: row["created_at"], reverse=True)
    return items[:25]


def _build_observation_checklist(observation, comment_count):
    has_description = bool((observation.description or "").strip())
    has_water = bool(observation.water_body_id)
    has_action = bool(observation.linked_action_id)
    has_comments = comment_count > 0

    if observation.status == ObservationStatus.CLOSED:
        return [
            {
                "text": "Observationen är avslutad",
                "ok": True,
            },
            {
                "text": "Insats kopplad" if has_action else "Avslutad utan insats",
                "ok": True,
            },
        ]

    return [
        {
            "text": "Insats kopplad" if has_action else "Åtgärd saknas",
            "ok": has_action,
        },
        {
            "text": "Beskrivning finns" if has_description else "Beskrivning saknas",
            "ok": has_description,
        },
        {
            "text": "Vattendrag kopplat" if has_water else "Vattendrag saknas",
            "ok": has_water,
        },
        {
            "text": "Anteckningar finns" if has_comments else "Anteckningar saknas",
            "ok": has_comments,
        },
    ]


def _group_observations_by_status(observations):
    observations_list = list(observations)
    groups = []
    for status_value in _OBSERVATION_STATUS_ORDER:
        items = [
            {
                "observation": row,
                "category_label": get_observation_category_label(row.category),
            }
            for row in observations_list
            if row.status == status_value
        ]
        if items:
            groups.append(
                {
                    "status": status_value,
                    "label": get_observation_status_label(status_value),
                    "items": items,
                }
            )
    return groups


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
            .select_related("created_by", "updated_by", "water_body", "responsible_user")
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

    status_choices_labeled = [
        (value, get_action_status_label(value)) for value, _ in status_choices
    ]
    action_rows = [
        {
            "action": action,
            "status_label": get_action_status_label(action.status),
            "priority_label": get_action_priority_label(action.priority),
            "responsible_label": _user_display_name(action.responsible_user),
            "deadline_short": _format_short_date(action.deadline) if action.deadline else None,
        }
        for action in actions
    ]

    return render(
        request,
        "fisheries/action_list.html",
        {
            "actions": actions,
            "action_rows": action_rows,
            "selected_status": selected_status,
            "search_query": search_query,
            "selected_sort": selected_sort,
            "status_choices": status_choices,
            "status_choices_labeled": status_choices_labeled,
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

    status_choices_labeled = [
        (value, get_observation_status_label(value)) for value, _ in status_choices
    ]
    observation_groups = _group_observations_by_status(observations) if org is not None else []

    return render(
        request,
        "fisheries/observation_list.html",
        {
            "observations": observations,
            "observation_groups": observation_groups,
            "selected_status": selected_status,
            "search_query": search_query,
            "selected_sort": selected_sort,
            "status_choices": status_choices,
            "status_choices_labeled": status_choices_labeled,
        },
    )


@login_required
def observation_create(request):
    org = getattr(request, "org", None)
    if org is None:
        return redirect("fisheries:observation_list")

    water_bodies = WaterBody.objects.for_org(org).filter(is_active=True).order_by("name")
    category_choices = ObservationCategory.choices
    category_choices_labeled = [
        (value, get_observation_category_label(value)) for value, _ in category_choices
    ]
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
                    "category_choices": category_choices_labeled,
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
            "category_choices": category_choices_labeled,
            "form_data": {},
        },
    )


@login_required
def overview(request):
    org = getattr(request, "org", None)
    today = timezone.localdate()
    week_end = today + timedelta(days=7)

    attention_items = []
    attention_total_count = 0
    next_deadline_action = None
    next_deadline_chip_label = "Ingen deadline"
    planned_now_actions = []
    in_progress_sidebar = []
    recent_fisheries_logs = []

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
    needs_decision_actions = 0
    fisheries_year_stats = []
    latest_observations = Observation.objects.none()
    latest_actions = ActionArea.objects.none()
    urgent_actions_list = ActionArea.objects.none()
    overdue_actions_list = ActionArea.objects.none()
    unassigned_actions_list = ActionArea.objects.none()

    if org is not None:
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
        overdue_actions = action_qs.filter(
            deadline__isnull=False,
            deadline__lt=today,
        ).exclude(status=ActionStatus.COMPLETED).count()
        actions_without_water = action_qs.filter(water_body__isnull=True).count()
        needs_decision_actions = action_qs.filter(
            status__in=[ActionStatus.URGENT, ActionStatus.NEEDS_ACTION],
        ).count()

        fisheries_year_stats = [
            {"label": "insatser totalt", "value": total_actions},
            {"label": "pågår", "value": in_progress_actions},
            {"label": "klara", "value": completed_actions},
            {"label": "kräver beslut", "value": needs_decision_actions},
        ]

        latest_observations = observation_qs.select_related("water_body", "linked_action").order_by("-created_at")[:5]
        latest_actions = action_qs.select_related("water_body", "responsible_user").order_by("-created_at")[:5]
        urgent_actions_list = action_qs.filter(status=ActionStatus.URGENT).order_by("-created_at")[:5]
        overdue_actions_list = action_qs.filter(deadline__isnull=False, deadline__lt=today).order_by("deadline")[:5]
        unassigned_actions_list = action_qs.filter(responsible_user__isnull=True).order_by("-created_at")[:5]

        active_actions = (
            action_qs.exclude(status=ActionStatus.COMPLETED)
            .select_related("water_body", "responsible_user")
        )
        attention_items, attention_total_count = _build_attention_items(
            active_actions,
            today,
            week_end,
        )

        next_deadline_action = (
            action_qs.filter(deadline__isnull=False, deadline__gte=today)
            .exclude(status=ActionStatus.COMPLETED)
            .select_related("responsible_user", "water_body")
            .order_by("deadline")
            .first()
        )
        if next_deadline_action:
            next_deadline_chip_label = _format_short_date(next_deadline_action.deadline)

        planned_now_actions = _actions_with_status_label(
            action_qs.filter(status__in=[ActionStatus.PLANNED, ActionStatus.IN_PROGRESS])
            .select_related("responsible_user")
            .order_by(F("deadline").asc(nulls_last=True), "-created_at")[:4]
        )

        in_progress_sidebar = _actions_with_status_label(
            action_qs.filter(status=ActionStatus.IN_PROGRESS)
            .select_related("responsible_user")
            .order_by(F("deadline").asc(nulls_last=True), "-created_at")[:5]
        )

        recent_fisheries_logs = list(
            ActionLog.objects.for_org(org)
            .select_related("user", "action_area")
            .order_by("-created_at")[:6]
        )

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
            "attention_items": attention_items,
            "attention_total_count": attention_total_count,
            "next_deadline_action": next_deadline_action,
            "next_deadline_chip_label": next_deadline_chip_label,
            "planned_now_actions": planned_now_actions,
            "in_progress_sidebar": in_progress_sidebar,
            "recent_fisheries_logs": recent_fisheries_logs,
            "needs_decision_actions": needs_decision_actions,
            "fisheries_year_stats": fisheries_year_stats,
            "today": today,
        },
    )


@login_required
def observation_detail(request, pk):
    org = getattr(request, "org", None)
    status_choices = Observation._meta.get_field("status").choices
    valid_status_values = {value for value, _ in status_choices}
    status_labels = {value: get_observation_status_label(value) for value, _ in status_choices}
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

    comments = list(observation.comments.select_related("user").order_by("-created_at"))
    logs = list(observation.logs.select_related("user").order_by("-created_at"))

    status_choices_labeled = [
        (value, get_observation_status_label(value)) for value, _ in status_choices
    ]
    category_choices_labeled = [
        (value, get_observation_category_label(value)) for value, _ in category_choices
    ]

    return render(
        request,
        "fisheries/observation_detail.html",
        {
            "observation": observation,
            "comments": comments,
            "logs": logs,
            "status_choices": status_choices,
            "status_choices_labeled": status_choices_labeled,
            "category_choices": category_choices,
            "category_choices_labeled": category_choices_labeled,
            "water_bodies": water_bodies,
            "header_badges": _build_observation_header_badges(observation),
            "next_step": _build_observation_next_step(observation),
            "status_label": get_observation_status_label(observation.status),
            "category_label": get_observation_category_label(observation.category),
            "activity_feed": _build_observation_activity_feed(logs, comments),
            "process_steps": _build_observation_process_steps(observation.status),
            "importance_text": _build_observation_importance_text(observation),
            "readiness_checklist": _build_observation_checklist(observation, len(comments)),
            "create_action_url": reverse(
                "fisheries:create_action_from_observation",
                args=[observation.pk],
            ),
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

    geojson = _EMPTY_ACTION_GEOJSON
    if observation.water_body and observation.water_body.geojson:
        geojson = observation.water_body.geojson

    action = ActionArea.objects.create(
        org=request.org,
        name=observation.title,
        description=observation.description,
        water_body=observation.water_body,
        geojson=geojson,
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

    comments = list(action.comments.select_related("user").order_by("-created_at"))
    logs = list(action.logs.select_related("user").order_by("-created_at"))
    today = timezone.localdate()

    status_choices_labeled = [
        (value, get_action_status_label(value)) for value, _ in status_choices
    ]
    priority_choices_labeled = [
        (value, get_action_priority_label(value)) for value, _ in priority_choices
    ]

    return render(
        request,
        "fisheries/action_detail.html",
        {
            "action": action,
            "comments": comments,
            "logs": logs,
            "status_choices": status_choices,
            "status_choices_labeled": status_choices_labeled,
            "priority_choices": priority_choices,
            "priority_choices_labeled": priority_choices_labeled,
            "responsible_users": responsible_users,
            "header_badges": _build_action_header_badges(action),
            "next_step": _build_action_next_step(action, today),
            "flow_steps": _build_fisheries_flow_steps(action.status),
            "status_label": get_action_status_label(action.status),
            "priority_label": get_action_priority_label(action.priority),
            "responsible_label": _user_display_name(action.responsible_user),
            "activity_feed": _build_activity_feed(logs, comments),
            "blockers": _build_action_blockers(action, len(comments)),
            "deadline_short": _format_short_date(action.deadline) if action.deadline else None,
            "is_overdue": bool(
                action.deadline
                and action.deadline < today
                and action.status != ActionStatus.COMPLETED
            ),
        },
    )
