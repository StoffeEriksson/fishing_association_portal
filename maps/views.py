import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from fisheries.models import ActionArea, ActionStatus

from .models import MapBoundary, WaterBody

logger = logging.getLogger(__name__)

FVOF_QUERY_TIMEOUT_SECONDS = 3


def _normalize_fvof_search_term(org_name):
    if not org_name:
        return ""
    term = org_name.strip().lower()
    term = re.sub(r"\s+", " ", term)
    term = re.sub(r"\s+(fvof|fvo)\s*$", "", term).strip()
    return term


def _escape_arcgis_string(value):
    return value.replace("'", "''")


def fetch_fvof_focus_for_org(org_name):
    if not org_name:
        return None
    if not settings.FISKEKARTAN_FVOF_ENABLED:
        return None
    if not settings.FISKEKARTAN_FVOF_QUERY_ENABLED:
        return None

    mapserver_url = (settings.FISKEKARTAN_FVOF_MAPSERVER_URL or "").rstrip("/")
    layer_id = settings.FISKEKARTAN_FVOF_LAYER_ID
    if not mapserver_url:
        return None

    search_term = _normalize_fvof_search_term(org_name)
    if not search_term:
        return None

    safe_term = _escape_arcgis_string(search_term)
    where = f"UPPER(FOR_NAMN) LIKE UPPER('%{safe_term}%')"
    query_url = f"{mapserver_url}/{layer_id}/query"
    params = {
        "where": where,
        "outFields": "FOR_NAMN,ORIGINALID",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "geojson",
        "resultRecordCount": "5",
    }
    request_url = f"{query_url}?{urllib.parse.urlencode(params)}"

    try:
        request = urllib.request.Request(
            request_url,
            headers={
                "Accept": "application/json",
                "User-Agent": "Windify/1.0",
            },
        )
        with urllib.request.urlopen(
            request, timeout=FVOF_QUERY_TIMEOUT_SECONDS
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        TimeoutError,
        json.JSONDecodeError,
        OSError,
    ) as exc:
        logger.warning(
            "FVOF auto-zoom query failed for org %r: %s", org_name, exc
        )
        return None

    features = payload.get("features") or []
    if not features:
        logger.info(
            "No FVOF match for org name %r (search term %r).",
            org_name,
            search_term,
        )
        return None

    feature = features[0]
    for candidate in features:
        for_namn = (candidate.get("properties") or {}).get("FOR_NAMN") or ""
        if search_term in for_namn.lower():
            feature = candidate
            break

    for_namn = (feature.get("properties") or {}).get("FOR_NAMN") or ""
    return {
        "found": True,
        "name": for_namn,
        "geojson": {
            "type": "FeatureCollection",
            "features": [feature],
        },
    }


@login_required
def map_page(request):
    org = getattr(request, "org", None)
    selected_action_id = None
    selected_water_id = None

    action_id = (request.GET.get("action_id") or "").strip()
    if org and action_id.isdigit():
        selected_action = ActionArea.objects.for_org(org).filter(pk=action_id, is_active=True).first()
        if selected_action:
            selected_action_id = selected_action.pk

    water_id = (request.GET.get("water_id") or "").strip()
    if org and selected_action_id is None and water_id.isdigit():
        selected_water = WaterBody.objects.for_org(org).filter(pk=water_id, is_active=True).first()
        if selected_water:
            selected_water_id = selected_water.pk

    if org:
        features = []

        boundaries = (
            MapBoundary.objects.for_org(org)
            .filter(is_active=True)
            .order_by("id")
        )
        for boundary in boundaries:
            if not boundary.geojson:
                continue
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "name": boundary.name,
                        "type": "area",
                        "fish": [],
                    },
                    "geometry": boundary.geojson,
                }
            )

        water_bodies = (
            WaterBody.objects.for_org(org)
            .filter(is_active=True)
            .prefetch_related("species")
        )
        for water in water_bodies:
            if not water.geojson:
                continue
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "id": water.pk,
                        "name": water.name,
                        "type": "water",
                        "fish": [species.name for species in water.species.all()],
                    },
                    "geometry": water.geojson,
                }
            )

        action_areas = ActionArea.objects.for_org(org).filter(is_active=True)
        for action in action_areas:
            if not action.geojson:
                continue
            status_label = ActionStatus(action.status).label
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "id": action.pk,
                        "name": action.name,
                        "type": "action",
                        "fish": [],
                        "status": action.status,
                        "status_label": status_label,
                    },
                    "geometry": action.geojson,
                }
            )

        geojson_data = {
            "type": "FeatureCollection",
            "features": features,
        }
    else:
        geojson_data = {
            "type": "FeatureCollection",
            "features": [],
        }

    fvof_focus = {
        "found": False,
        "name": "",
        "geojson": None,
    }
    if org and selected_action_id is None and selected_water_id is None:
        matched_fvof = fetch_fvof_focus_for_org(org.name)
        if matched_fvof:
            fvof_focus = matched_fvof

    context = {
        "geojson_data": geojson_data,
        "fvof_focus": fvof_focus,
        "has_org": bool(org),
        "org_name": org.name if org else "",
        "selected_action_id": selected_action_id,
        "selected_water_id": selected_water_id,
    }
    return render(request, "maps/map_page.html", context)
