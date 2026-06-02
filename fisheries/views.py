from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.db.models import Count, F, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from maps.models import WaterBody, WaterBodyHealthSnapshot
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
from .trash import (
    empty_trash,
    move_action_to_trash,
    move_all_to_trash,
    move_observation_to_trash,
    purge_action,
    purge_observation,
    restore_action,
    restore_observation,
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


_OBSERVATION_ATTENTION_STATUSES = (
    ObservationStatus.NEW,
    ObservationStatus.UNDER_REVIEW,
)

_OBSERVATION_ATTENTION_STATUS_RANK = {
    ObservationStatus.NEW: 0,
    ObservationStatus.UNDER_REVIEW: 1,
}


def _build_observation_meta_badges(observation):
    badges = [
        {
            "icon": "fa-circle-info",
            "label": get_observation_status_label(observation.status),
        },
        {
            "icon": "fa-tag",
            "label": get_observation_category_label(observation.category),
        },
    ]
    if observation.water_body:
        badges.append(
            {
                "icon": "fa-water",
                "label": observation.water_body.name,
            }
        )
    return badges


def _build_observation_attention_items(observation_qs, limit=8):
    candidates = list(
        observation_qs.filter(status__in=_OBSERVATION_ATTENTION_STATUSES)
        .select_related("water_body")
    )

    items = []
    for observation in candidates:
        status_rank = _OBSERVATION_ATTENTION_STATUS_RANK.get(observation.status, 9)
        priority_class = (
            "ccv2-priority-high"
            if observation.status == ObservationStatus.NEW
            else "ccv2-priority-normal"
        )
        items.append(
            {
                "observation": observation,
                "rank": status_rank,
                "label": "Observation",
                "priority_class": priority_class,
                "meta_badges": _build_observation_meta_badges(observation),
                "next_step_text": (
                    "Ny signal från fältet — granska och avgör om insats behövs."
                    if observation.status == ObservationStatus.NEW
                    else "Fortsätt granskningen och ta ställning till nästa steg."
                ),
                "url": reverse("fisheries:observation_detail", args=[observation.pk]),
                "cta_text": "Granska",
            }
        )

    items.sort(
        key=lambda item: (
            item["rank"],
            -item["observation"].created_at.timestamp(),
        )
    )
    total_count = len(items)
    return items[:limit], total_count


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


def _parse_lat_lng(lat_raw, lng_raw):
    lat_str = (lat_raw or "").strip() if lat_raw is not None else ""
    lng_str = (lng_raw or "").strip() if lng_raw is not None else ""
    if not lat_str or not lng_str:
        return None, None
    try:
        lat = float(lat_str)
        lng = float(lng_str)
    except (TypeError, ValueError):
        return None, None
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lng <= 180.0):
        return None, None
    try:
        return Decimal(f"{lat:.6f}"), Decimal(f"{lng:.6f}")
    except InvalidOperation:
        return None, None


def _prefill_water_body_id(org, water_id_raw):
    if org is None:
        return ""
    water_id = (water_id_raw or "").strip()
    if not water_id.isdigit():
        return ""
    if WaterBody.objects.for_org(org).filter(pk=water_id, is_active=True).exists():
        return water_id
    return ""


def _resolve_selected_water(org, water_id_raw):
    if org is None:
        return None
    water_id = (water_id_raw or "").strip()
    if not water_id.isdigit():
        return None
    return (
        WaterBody.objects.for_org(org)
        .filter(pk=water_id, is_active=True)
        .first()
    )


def _redirect_fisheries_list(request, url_name, org):
    water_id_raw = (request.POST.get("water_id") or request.GET.get("water_id") or "").strip()
    url = reverse(url_name)
    selected_water = _resolve_selected_water(org, water_id_raw)
    if selected_water:
        url = f"{url}?{urlencode({'water_id': selected_water.pk})}"
    return redirect(url)


def _map_position_context(latitude, longitude):
    if latitude is None or longitude is None:
        return {"map_position": None}
    return {
        "map_position": {
            "latitude": latitude,
            "longitude": longitude,
            "latitude_display": f"{latitude:.6f}",
            "longitude_display": f"{longitude:.6f}",
        }
    }


def _point_geojson_from_lat_lng(latitude, longitude):
    if latitude is None or longitude is None:
        return None
    return {
        "type": "Point",
        "coordinates": [float(longitude), float(latitude)],
    }


def _action_create_geojson_and_position(latitude, longitude, water_body):
    point_geojson = _point_geojson_from_lat_lng(latitude, longitude)
    if point_geojson is not None:
        return point_geojson, latitude, longitude
    if water_body and water_body.geojson:
        return water_body.geojson, None, None
    return _EMPTY_ACTION_GEOJSON, None, None


def _create_map_position_from_request(request):
    if request.method == "POST":
        return _parse_lat_lng(
            request.POST.get("latitude") or request.POST.get("lat"),
            request.POST.get("longitude") or request.POST.get("lng"),
        )
    return _parse_lat_lng(request.GET.get("lat"), request.GET.get("lng"))


def _map_position_log_message(latitude, longitude, synced_from=None):
    coords = f"({latitude:.6f}, {longitude:.6f})"
    if synced_from == "observation":
        return f"Kartposition synkad från kopplad observation {coords}"
    if synced_from == "action":
        return f"Kartposition synkad från kopplad insats {coords}"
    return f"Kartposition uppdaterad {coords}"


def _save_observation_map_position(
    observation,
    org,
    latitude,
    longitude,
    water_body_id,
    user,
    *,
    sync_linked=True,
    synced_from=None,
):
    if latitude is None or longitude is None:
        return False

    update_fields = ["latitude", "longitude", "updated_by", "updated_at"]
    observation.latitude = latitude
    observation.longitude = longitude

    if water_body_id:
        water_body = WaterBody.objects.for_org(org).filter(
            pk=water_body_id,
            is_active=True,
        ).first()
        if water_body:
            observation.water_body = water_body
            update_fields.append("water_body")

    observation.updated_by = user
    observation.save(update_fields=update_fields)

    ObservationLog.objects.create(
        org=org,
        observation=observation,
        user=user,
        event_type="updated",
        message=_map_position_log_message(latitude, longitude, synced_from),
    )

    if sync_linked and observation.linked_action_id:
        action = (
            ActionArea.objects.for_org(org)
            .not_trashed()
            .filter(pk=observation.linked_action_id)
            .first()
        )
        if action:
            _save_action_map_position(
                action,
                org,
                latitude,
                longitude,
                water_body_id,
                user,
                sync_linked=False,
                synced_from="observation",
            )

    return True


def _save_action_map_position(
    action,
    org,
    latitude,
    longitude,
    water_body_id,
    user,
    *,
    sync_linked=True,
    synced_from=None,
):
    geojson = _point_geojson_from_lat_lng(latitude, longitude)
    if geojson is None:
        return False

    update_fields = [
        "latitude",
        "longitude",
        "geojson",
        "updated_by",
        "updated_at",
    ]
    action.latitude = latitude
    action.longitude = longitude
    action.geojson = geojson

    if water_body_id:
        water_body = WaterBody.objects.for_org(org).filter(
            pk=water_body_id,
            is_active=True,
        ).first()
        if water_body:
            action.water_body = water_body
            update_fields.append("water_body")

    action.updated_by = user
    action.save(update_fields=update_fields)

    ActionLog.objects.create(
        org=org,
        action_area=action,
        user=user,
        event_type="updated",
        message=_map_position_log_message(latitude, longitude, synced_from),
    )

    if sync_linked:
        linked_observations = Observation.objects.for_org(org).not_trashed().filter(
            linked_action=action,
        )
        for linked_observation in linked_observations:
            _save_observation_map_position(
                linked_observation,
                org,
                latitude,
                longitude,
                water_body_id,
                user,
                sync_linked=False,
                synced_from="action",
            )

    return True


def _try_apply_map_pick_from_query(request, org, *, observation=None, action=None):
    if request.method != "GET" or org is None:
        return None

    latitude, longitude = _parse_lat_lng(
        request.GET.get("lat"),
        request.GET.get("lng"),
    )
    if latitude is None:
        return None

    water_body_id = _prefill_water_body_id(org, request.GET.get("water_id"))

    if observation is not None:
        if _save_observation_map_position(
            observation,
            org,
            latitude,
            longitude,
            water_body_id,
            request.user,
        ):
            success_message = "Kartposition sparad."
            if observation.linked_action_id:
                success_message += " Kopplad insats uppdaterades."
            messages.success(request, success_message)
            return redirect("fisheries:observation_detail", pk=observation.pk)

    if action is not None:
        if _save_action_map_position(
            action,
            org,
            latitude,
            longitude,
            water_body_id,
            request.user,
        ):
            success_message = "Kartposition sparad."
            if Observation.objects.for_org(org).not_trashed().filter(
                linked_action=action,
            ).exists():
                success_message += " Kopplad observation uppdaterades."
            messages.success(request, success_message)
            return redirect("fisheries:action_detail", pk=action.pk)

    return None


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
            "body": "Observationen är kopplad till en insats. Fortsätt arbetet där.",
            "pill_label": status_label,
            "pill_class": "fv-next-pill--neutral",
            "ctas": [
                {
                    "label": "Öppna insats",
                    "kind": "link",
                    "variant": "primary",
                    "url": reverse("fisheries:action_detail", args=[observation.linked_action_id]),
                },
            ],
        }

    if observation.status == ObservationStatus.UNDER_REVIEW:
        ctas = [
            {
                "label": "Skapa insats",
                "kind": "create_action",
                "variant": "primary",
                "url": reverse("fisheries:create_action_from_observation", args=[observation.pk]),
            },
            {
                "label": "Avsluta utan åtgärd",
                "kind": "change_status",
                "variant": "secondary",
                "status": ObservationStatus.CLOSED,
            },
        ]
        return {
            "title": "Nästa steg",
            "body": "Bedöm om observationen kräver en fiskevårdsinsats eller kan avslutas.",
            "pill_label": status_label,
            "pill_class": "fv-next-pill--decision",
            "ctas": ctas,
        }

    if observation.status == ObservationStatus.NEW:
        ctas = [
            {
                "label": "Starta granskning",
                "kind": "change_status",
                "variant": "primary",
                "status": ObservationStatus.UNDER_REVIEW,
            },
            {
                "label": "Skapa insats direkt",
                "kind": "create_action",
                "variant": "secondary",
                "url": reverse("fisheries:create_action_from_observation", args=[observation.pk]),
            },
        ]
        return {
            "title": "Nästa steg",
            "body": "Börja med att granska observationen. Om problemet är tydligt kan ni skapa en insats direkt.",
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
            action = ActionArea.objects.for_org(org).not_trashed().filter(pk=action_id).first()
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
        return _redirect_fisheries_list(request, "fisheries:action_list", org)

    selected_status = (request.GET.get("status") or "").strip()
    search_query = (request.GET.get("q") or "").strip()
    selected_sort = (request.GET.get("sort") or "").strip()
    selected_water = _resolve_selected_water(org, request.GET.get("water_id"))
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
        selected_water = None
    else:
        actions = (
            ActionArea.objects.for_org(org)
            .not_trashed()
            .select_related("created_by", "updated_by", "water_body", "responsible_user")
        )
        if selected_water:
            actions = actions.filter(water_body=selected_water)
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
            "selected_water": selected_water,
            "status_choices": status_choices,
            "status_choices_labeled": status_choices_labeled,
        },
    )


def _board_action_rows(qs):
    return [
        {
            "action": action,
            "priority_label": get_action_priority_label(action.priority),
        }
        for action in qs
    ]


@login_required
def action_board(request):
    org = getattr(request, "org", None)

    if org is None:
        urgent_actions = []
        needs_action_actions = []
        planned_actions = []
        in_progress_actions = []
        completed_actions = []
    else:
        base_qs = (
            ActionArea.objects.for_org(org)
            .not_trashed()
            .select_related("responsible_user", "water_body")
        )
        urgent_actions = _board_action_rows(
            base_qs.filter(status=ActionStatus.URGENT).order_by("-created_at")
        )
        needs_action_actions = _board_action_rows(
            base_qs.filter(status=ActionStatus.NEEDS_ACTION).order_by("-created_at")
        )
        planned_actions = _board_action_rows(
            base_qs.filter(status=ActionStatus.PLANNED).order_by("-created_at")
        )
        in_progress_actions = _board_action_rows(
            base_qs.filter(status=ActionStatus.IN_PROGRESS).order_by("-created_at")
        )
        completed_actions = _board_action_rows(
            base_qs.filter(status=ActionStatus.COMPLETED).order_by("-created_at")
        )

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
    priority_choices_labeled = [
        (value, get_action_priority_label(value)) for value, _ in priority_choices
    ]
    valid_priority_values = {value for value, _ in priority_choices}

    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        description = (request.POST.get("description") or "").strip()
        water_body_id = (request.POST.get("water_body") or "").strip()
        priority = (request.POST.get("priority") or "").strip()
        deadline = (request.POST.get("deadline") or "").strip()
        latitude, longitude = _create_map_position_from_request(request)

        if not name:
            return render(
                request,
                "fisheries/action_create.html",
                {
                    "water_bodies": water_bodies,
                    "priority_choices": priority_choices_labeled,
                    "error": "Namn är obligatoriskt.",
                    "form_data": {
                        "name": name,
                        "description": description,
                        "water_body": water_body_id,
                        "priority": priority,
                        "deadline": deadline,
                    },
                    **_map_position_context(latitude, longitude),
                },
            )

        water_body = None
        if water_body_id:
            water_body = WaterBody.objects.for_org(org).filter(pk=water_body_id, is_active=True).first()

        if priority not in valid_priority_values:
            priority = ActionPriority.MEDIUM

        geojson, saved_lat, saved_lng = _action_create_geojson_and_position(
            latitude, longitude, water_body
        )
        create_kwargs = {
            "org": request.org,
            "name": name,
            "description": description,
            "water_body": water_body,
            "priority": priority,
            "deadline": deadline or None,
            "created_by": request.user,
            "updated_by": request.user,
            "status": ActionStatus.NEEDS_ACTION,
            "geojson": geojson,
        }
        if saved_lat is not None and saved_lng is not None:
            create_kwargs["latitude"] = saved_lat
            create_kwargs["longitude"] = saved_lng

        action = ActionArea.objects.create(**create_kwargs)
        ActionLog.objects.create(
            org=request.org,
            action_area=action,
            user=request.user,
            event_type="created",
            message="Åtgärd skapad",
        )
        return redirect("fisheries:action_detail", pk=action.pk)

    form_data = {}
    prefill_water = _prefill_water_body_id(org, request.GET.get("water_id"))
    if prefill_water:
        form_data["water_body"] = prefill_water
    latitude, longitude = _create_map_position_from_request(request)

    return render(
        request,
        "fisheries/action_create.html",
        {
            "water_bodies": water_bodies,
            "priority_choices": priority_choices_labeled,
            "form_data": form_data,
            **_map_position_context(latitude, longitude),
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
            observation = Observation.objects.for_org(org).not_trashed().filter(pk=observation_id).first()
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
        return _redirect_fisheries_list(request, "fisheries:observation_list", org)

    selected_status = (request.GET.get("status") or "").strip()
    search_query = (request.GET.get("q") or "").strip()
    selected_sort = (request.GET.get("sort") or "").strip()
    selected_water = _resolve_selected_water(org, request.GET.get("water_id"))
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
        selected_water = None
    else:
        observations = (
            Observation.objects.for_org(org)
            .not_trashed()
            .select_related("water_body", "linked_action", "created_by", "updated_by")
        )
        if selected_water:
            observations = observations.filter(water_body=selected_water)
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
            "selected_water": selected_water,
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
        latitude, longitude = _create_map_position_from_request(request)

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
                    **_map_position_context(latitude, longitude),
                },
            )

        if category not in valid_category_values:
            category = ObservationCategory.OTHER

        water_body = None
        if water_body_id:
            water_body = WaterBody.objects.for_org(org).filter(pk=water_body_id, is_active=True).first()

        create_kwargs = {
            "org": request.org,
            "title": title,
            "category": category,
            "water_body": water_body,
            "description": description,
            "status": ObservationStatus.NEW,
            "created_by": request.user,
            "updated_by": request.user,
        }
        if latitude is not None and longitude is not None:
            create_kwargs["latitude"] = latitude
            create_kwargs["longitude"] = longitude

        observation = Observation.objects.create(**create_kwargs)
        ObservationLog.objects.create(
            org=request.org,
            observation=observation,
            user=request.user,
            event_type="created",
            message="Observation skapad",
        )
        return redirect("fisheries:observation_detail", pk=observation.pk)

    form_data = {}
    prefill_water = _prefill_water_body_id(org, request.GET.get("water_id"))
    if prefill_water:
        form_data["water_body"] = prefill_water
    latitude, longitude = _create_map_position_from_request(request)

    return render(
        request,
        "fisheries/observation_create.html",
        {
            "water_bodies": water_bodies,
            "category_choices": category_choices_labeled,
            "form_data": form_data,
            **_map_position_context(latitude, longitude),
        },
    )


def _water_health_snapshot_for(water_body):
    try:
        return water_body.health_snapshot
    except WaterBodyHealthSnapshot.DoesNotExist:
        return None


def _water_health_tone_and_risk(snapshot):
    if snapshot is None or (snapshot.fetch_error or "").strip():
        return "neutral", False
    return snapshot.eco_tone or "neutral", bool(snapshot.risk_flag)


def _water_attention_priority_score(snapshot, observation_count, action_count):
    score = 0
    eco_tone = "neutral"
    has_risk = False

    if snapshot is not None and not (snapshot.fetch_error or "").strip():
        eco_tone = snapshot.eco_tone or "neutral"
        has_risk = bool(snapshot.risk_flag)

    if eco_tone == "bad":
        score += 3
    elif eco_tone == "moderate":
        score += 1

    if has_risk:
        score += 2

    if observation_count > 0:
        score += 1
    if observation_count >= 5:
        score += 2

    if action_count == 0 and observation_count > 0:
        score += 1

    return score


def _water_attention_reason(snapshot, observation_count, action_count):
    _, has_risk = _water_health_tone_and_risk(snapshot)
    eco_tone = "neutral"
    if snapshot is not None and not (snapshot.fetch_error or "").strip():
        eco_tone = snapshot.eco_tone or "neutral"

    if has_risk:
        return "Risk enligt VISS"
    if eco_tone == "bad":
        return "Otillfredsställande status"
    if observation_count > 0 and action_count == 0:
        return "Observationer utan insats"
    return "Kräver uppmärksamhet"


def _build_water_attention_items(org, limit=5):
    water_bodies = (
        WaterBody.objects.for_org(org)
        .filter(is_active=True)
        .select_related("health_snapshot")
        .annotate(
            observation_count=Count(
                "observations",
                filter=Q(
                    observations__org_id=org.pk,
                    observations__deleted_at__isnull=True,
                ),
                distinct=True,
            ),
            action_count=Count(
                "action_areas",
                filter=Q(
                    action_areas__org_id=org.pk,
                    action_areas__deleted_at__isnull=True,
                ),
                distinct=True,
            ),
        )
    )

    candidates = []
    for water_body in water_bodies:
        snapshot = _water_health_snapshot_for(water_body)
        health_tone, has_risk = _water_health_tone_and_risk(snapshot)
        observation_count = water_body.observation_count
        action_count = water_body.action_count
        priority_score = _water_attention_priority_score(
            snapshot,
            observation_count,
            action_count,
        )

        if priority_score < 2:
            continue

        candidates.append(
            {
                "water_body": water_body,
                "health_tone": health_tone,
                "has_risk": has_risk,
                "reason": _water_attention_reason(
                    snapshot,
                    observation_count,
                    action_count,
                ),
                "priority_score": priority_score,
                "detail_url": reverse("maps:waterbody_detail", args=[water_body.pk]),
            }
        )

    candidates.sort(
        key=lambda row: (
            -row["priority_score"],
            (row["water_body"].name or "").strip().lower(),
            row["water_body"].pk,
        )
    )
    return candidates[:limit]


def _next_deadline_status_pill_class(action, today):
    week_end = today + timedelta(days=7)
    if action.status == ActionStatus.URGENT:
        return "fv-next-pill--critical"
    if action.status == ActionStatus.NEEDS_ACTION:
        return "fv-next-pill--decision"
    if action.deadline and action.deadline < today:
        return "fv-next-pill--critical"
    if action.deadline and today <= action.deadline <= week_end:
        return "fv-next-pill--deadline"
    return "fv-next-pill--neutral"


def _build_next_deadline_action_card(action, today):
    if action is None:
        return None

    week_end = today + timedelta(days=7)
    missing_responsible = action.responsible_user_id is None
    is_overdue = bool(action.deadline and action.deadline < today)
    deadline_soon = bool(
        action.deadline and not is_overdue and today <= action.deadline <= week_end
    )

    return {
        "action": action,
        "status_label": get_action_status_label(action.status),
        "priority_label": get_action_priority_label(action.priority),
        "status_pill_class": _next_deadline_status_pill_class(action, today),
        "responsible_label": (
            None if missing_responsible else _user_display_name(action.responsible_user)
        ),
        "water_body_name": (
            (action.water_body.name or "").strip() if action.water_body else None
        ),
        "deadline_short": (
            _format_short_date(action.deadline) if action.deadline else ""
        ),
        "is_overdue": is_overdue,
        "deadline_soon": deadline_soon,
        "missing_responsible": missing_responsible,
        "detail_url": reverse("fisheries:action_detail", args=[action.pk]),
    }


@login_required
def overview(request):
    org = getattr(request, "org", None)
    today = timezone.localdate()
    week_end = today + timedelta(days=7)

    attention_items = []
    attention_total_count = 0
    observation_attention_items = []
    observation_attention_total_count = 0
    attention_grand_total = 0
    next_deadline_action = None
    next_deadline_card = None
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
    water_attention_items = []

    if org is not None:
        observation_qs = Observation.objects.for_org(org).not_trashed()
        action_qs = ActionArea.objects.for_org(org).not_trashed()

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
        observation_attention_items, observation_attention_total_count = (
            _build_observation_attention_items(observation_qs)
        )
        attention_grand_total = (
            attention_total_count + observation_attention_total_count
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
            next_deadline_card = _build_next_deadline_action_card(
                next_deadline_action,
                today,
            )

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

        water_attention_items = _build_water_attention_items(org, limit=5)

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
            "observation_attention_items": observation_attention_items,
            "observation_attention_total_count": observation_attention_total_count,
            "attention_grand_total": attention_grand_total,
            "next_deadline_action": next_deadline_action,
            "next_deadline_card": next_deadline_card,
            "next_deadline_chip_label": next_deadline_chip_label,
            "planned_now_actions": planned_now_actions,
            "in_progress_sidebar": in_progress_sidebar,
            "recent_fisheries_logs": recent_fisheries_logs,
            "needs_decision_actions": needs_decision_actions,
            "fisheries_year_stats": fisheries_year_stats,
            "water_attention_items": water_attention_items,
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
        Observation.objects.for_org(org)
        .not_trashed()
        .select_related(
            "water_body",
            "linked_action",
            "created_by",
            "updated_by",
        ),
        pk=pk,
    )

    pick_redirect = _try_apply_map_pick_from_query(
        request, org, observation=observation
    )
    if pick_redirect is not None:
        return pick_redirect

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
                water_body = WaterBody.objects.for_org(org).filter(pk=water_body_id, is_active=True).first()

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

        elif action_type == "trash":
            move_observation_to_trash(observation, org, request.user)
            messages.success(
                request,
                f"Observationen «{observation.title}» flyttades till papperskorgen.",
            )
            return redirect("fisheries:trash")

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
        Observation.objects.for_org(org)
        .not_trashed()
        .select_related("linked_action", "water_body"),
        pk=pk,
    )

    if observation.linked_action_id:
        return redirect("fisheries:action_detail", pk=observation.linked_action_id)

    geojson = _EMPTY_ACTION_GEOJSON
    latitude = None
    longitude = None
    if observation.has_exact_position:
        latitude = observation.latitude
        longitude = observation.longitude
        geojson = _point_geojson_from_lat_lng(latitude, longitude)
    elif observation.water_body and observation.water_body.geojson:
        from maps.views import _geometry_bbox_center

        center = _geometry_bbox_center(observation.water_body.geojson)
        if center:
            geojson = _point_geojson_from_lat_lng(center[1], center[0])

    create_kwargs = {
        "org": request.org,
        "name": observation.title,
        "description": observation.description,
        "water_body": observation.water_body,
        "geojson": geojson,
        "created_by": request.user,
        "updated_by": request.user,
        "status": ActionStatus.NEEDS_ACTION,
    }
    if latitude is not None and longitude is not None:
        create_kwargs["latitude"] = latitude
        create_kwargs["longitude"] = longitude

    action = ActionArea.objects.create(**create_kwargs)

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
    status_labels = {
        value: get_action_status_label(value) for value, _ in status_choices
    }
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
        .not_trashed()
        .select_related("created_by", "updated_by", "water_body", "responsible_user"),
        pk=pk,
    )

    pick_redirect = _try_apply_map_pick_from_query(request, org, action=action)
    if pick_redirect is not None:
        return pick_redirect

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

        elif action_type == "trash":
            move_action_to_trash(action, org, request.user)
            messages.success(
                request,
                f"Insatsen «{action.name}» flyttades till papperskorgen.",
            )
            return redirect("fisheries:trash")

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


@login_required
def fisheries_trash(request):
    org = getattr(request, "org", None)
    if org is None:
        messages.error(request, "Ingen aktiv organisation vald.")
        return redirect("portal:dashboard")

    if request.method == "POST":
        action_type = (request.POST.get("action_type") or "").strip()
        confirm = (request.POST.get("confirm") or "").strip() == "yes"

        if action_type == "move_all_to_trash" and confirm:
            obs_count, act_count = move_all_to_trash(org, request.user)
            messages.success(
                request,
                f"{obs_count} observationer och {act_count} insatser flyttades till papperskorgen.",
            )
        elif action_type == "empty_trash" and confirm:
            obs_count, act_count = empty_trash(org)
            messages.success(
                request,
                f"{obs_count} observationer och {act_count} insatser raderades permanent.",
            )
        elif action_type in ("move_all_to_trash", "empty_trash"):
            messages.error(request, "Bekräfta åtgärden genom att kryssa i rutan.")
        return redirect("fisheries:trash")

    trashed_observations = list(
        Observation.objects.for_org(org)
        .trashed_only()
        .select_related("water_body", "linked_action", "deleted_by")
        .order_by("-deleted_at")
    )
    trashed_actions = list(
        ActionArea.objects.for_org(org)
        .trashed_only()
        .select_related("water_body", "deleted_by")
        .order_by("-deleted_at")
    )
    active_observation_count = Observation.objects.for_org(org).not_trashed().count()
    active_action_count = ActionArea.objects.for_org(org).not_trashed().count()

    return render(
        request,
        "fisheries/trash.html",
        {
            "trashed_observations": trashed_observations,
            "trashed_actions": trashed_actions,
            "active_observation_count": active_observation_count,
            "active_action_count": active_action_count,
        },
    )


@login_required
def trash_observation(request, pk):
    org = getattr(request, "org", None)
    if org is None or request.method != "POST":
        return redirect("fisheries:observation_list")

    observation = get_object_or_404(
        Observation.objects.for_org(org).not_trashed(),
        pk=pk,
    )
    move_observation_to_trash(observation, org, request.user)
    messages.success(request, f"Observationen «{observation.title}» flyttades till papperskorgen.")
    return redirect("fisheries:trash")


@login_required
def trash_action(request, pk):
    org = getattr(request, "org", None)
    if org is None or request.method != "POST":
        return redirect("fisheries:action_list")

    action = get_object_or_404(ActionArea.objects.for_org(org).not_trashed(), pk=pk)
    move_action_to_trash(action, org, request.user)
    messages.success(request, f"Insatsen «{action.name}» flyttades till papperskorgen.")
    return redirect("fisheries:trash")


@login_required
def restore_observation_view(request, pk):
    org = getattr(request, "org", None)
    if org is None or request.method != "POST":
        return redirect("fisheries:trash")

    observation = get_object_or_404(
        Observation.objects.for_org(org).trashed_only(),
        pk=pk,
    )
    restore_observation(observation, org, request.user)
    messages.success(request, f"Observationen «{observation.title}» återställdes.")
    return redirect("fisheries:observation_detail", pk=observation.pk)


@login_required
def restore_action_view(request, pk):
    org = getattr(request, "org", None)
    if org is None or request.method != "POST":
        return redirect("fisheries:trash")

    action = get_object_or_404(ActionArea.objects.for_org(org).trashed_only(), pk=pk)
    restore_action(action, org, request.user)
    messages.success(request, f"Insatsen «{action.name}» återställdes.")
    return redirect("fisheries:action_detail", pk=action.pk)


@login_required
def purge_observation_view(request, pk):
    org = getattr(request, "org", None)
    if org is None or request.method != "POST":
        return redirect("fisheries:trash")

    observation = get_object_or_404(
        Observation.objects.for_org(org).trashed_only(),
        pk=pk,
    )
    title = observation.title
    purge_observation(observation)
    messages.success(request, f"Observationen «{title}» raderades permanent.")
    return redirect("fisheries:trash")


@login_required
def purge_action_view(request, pk):
    org = getattr(request, "org", None)
    if org is None or request.method != "POST":
        return redirect("fisheries:trash")

    action = get_object_or_404(ActionArea.objects.for_org(org).trashed_only(), pk=pk)
    name = action.name
    purge_action(action)
    messages.success(request, f"Insatsen «{name}» raderades permanent.")
    return redirect("fisheries:trash")
