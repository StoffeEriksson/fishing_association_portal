import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from fisheries.labels import (
    get_observation_category_label,
    get_observation_status_label,
)
from fisheries.models import ActionArea, ActionStatus, Observation

from .models import MapBoundary, WaterBody, WaterBodyType

logger = logging.getLogger(__name__)

FVOF_QUERY_TIMEOUT_SECONDS = 3
VISS_LAKE_QUERY_TIMEOUT_SECONDS = 5
VISS_LAKE_MAPSERVER_URL = (
    "https://ext-geodata-applikationer.lansstyrelsen.se/arcgis/rest/services/"
    "VISS/lst_viss_api/MapServer"
)
VISS_LAKE_LAYER_ID = 56
DESCRIPTION_EXCERPT_MAX_LENGTH = 120


def _parse_geojson_data(geojson_data):
    if not geojson_data:
        return None
    if isinstance(geojson_data, str):
        try:
            geojson_data = json.loads(geojson_data)
        except json.JSONDecodeError:
            return None
    if not isinstance(geojson_data, dict):
        return None
    return geojson_data


def _collect_coordinate_pairs(node, pairs):
    if isinstance(node, (list, tuple)):
        if (
            len(node) >= 2
            and isinstance(node[0], (int, float))
            and isinstance(node[1], (int, float))
        ):
            lng = float(node[0])
            lat = float(node[1])
            if -180.0 <= lng <= 180.0 and -90.0 <= lat <= 90.0:
                pairs.append((lng, lat))
            return
        for item in node:
            _collect_coordinate_pairs(item, pairs)


def _extract_geometry(geojson_data):
    parsed = _parse_geojson_data(geojson_data)
    if not parsed:
        return None

    geo_type = parsed.get("type")
    if geo_type == "Feature":
        return parsed.get("geometry")
    if geo_type == "FeatureCollection":
        for feature in parsed.get("features") or []:
            geometry = (feature or {}).get("geometry")
            if geometry:
                return geometry
        return None
    if geo_type in {
        "Point",
        "LineString",
        "MultiLineString",
        "Polygon",
        "MultiPolygon",
    }:
        return parsed
    return None


def _geometry_bbox_center(geojson_data):
    geometry = _extract_geometry(geojson_data)
    if not geometry or not geometry.get("coordinates"):
        return None

    pairs = []
    _collect_coordinate_pairs(geometry.get("coordinates"), pairs)
    if not pairs:
        return None

    lng_values = [pair[0] for pair in pairs]
    lat_values = [pair[1] for pair in pairs]
    min_lng = min(lng_values)
    max_lng = max(lng_values)
    min_lat = min(lat_values)
    max_lat = max(lat_values)
    return [(min_lng + max_lng) / 2.0, (min_lat + max_lat) / 2.0]


def _observation_description_excerpt(description):
    text = (description or "").strip()
    if not text:
        return ""
    if len(text) <= DESCRIPTION_EXCERPT_MAX_LENGTH:
        return text
    return text[: DESCRIPTION_EXCERPT_MAX_LENGTH - 1].rstrip() + "…"


def _observation_geometry_source(observation):
    if observation.water_body and observation.water_body.geojson:
        return observation.water_body.geojson
    if observation.linked_action and observation.linked_action.geojson:
        return observation.linked_action.geojson
    return None


def _build_observation_map_features(org):
    if org is None:
        return []

    observations = (
        Observation.objects.for_org(org)
        .filter(is_active=True)
        .select_related("water_body", "linked_action")
    )
    features = []

    for observation in observations:
        geometry_source = _observation_geometry_source(observation)
        if not geometry_source:
            continue

        center = _geometry_bbox_center(geometry_source)
        if not center:
            logger.info(
                "Observation %s skipped on map: could not derive point from geometry.",
                observation.pk,
            )
            continue

        water_body_name = ""
        if observation.water_body:
            water_body_name = observation.water_body.name

        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": center,
                },
                "properties": {
                    "type": "observation",
                    "id": observation.pk,
                    "title": observation.title,
                    "category": observation.category,
                    "category_label": get_observation_category_label(
                        observation.category
                    ),
                    "status": observation.status,
                    "status_label": get_observation_status_label(
                        observation.status
                    ),
                    "water_body_name": water_body_name,
                    "detail_url": reverse(
                        "fisheries:observation_detail",
                        args=[observation.pk],
                    ),
                    "created_at": observation.created_at.strftime("%Y-%m-%d"),
                    "description_excerpt": _observation_description_excerpt(
                        observation.description
                    ),
                },
            }
        )

    return features


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


def fetch_viss_lake_geometry_by_ms_cd(ms_cd):
    ms_cd = (ms_cd or "").strip()
    if not ms_cd:
        return None

    safe_ms_cd = _escape_arcgis_string(ms_cd)
    where = f"MS_CD = '{safe_ms_cd}'"
    query_url = f"{VISS_LAKE_MAPSERVER_URL}/{VISS_LAKE_LAYER_ID}/query"
    params = {
        "where": where,
        "outFields": "*",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "geojson",
        "resultRecordCount": "1",
    }
    request_url = f"{query_url}?{urllib.parse.urlencode(params)}"

    try:
        http_request = urllib.request.Request(
            request_url,
            headers={
                "Accept": "application/json",
                "User-Agent": "Windify/1.0",
            },
        )
        with urllib.request.urlopen(
            http_request, timeout=VISS_LAKE_QUERY_TIMEOUT_SECONDS
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        TimeoutError,
        json.JSONDecodeError,
        OSError,
    ) as exc:
        logger.warning("VISS lake geometry query failed for MS_CD %r: %s", ms_cd, exc)
        return None

    features = payload.get("features") or []
    if not features:
        logger.info("No VISS lake geometry match for MS_CD %r.", ms_cd)
        return None

    feature = features[0]
    geometry = feature.get("geometry")
    if not geometry or geometry.get("type") not in {"Polygon", "MultiPolygon"}:
        logger.warning(
            "VISS lake geometry for MS_CD %r has invalid geometry type: %s",
            ms_cd,
            (geometry or {}).get("type"),
        )
        return None

    if not geometry.get("coordinates"):
        logger.warning("VISS lake geometry for MS_CD %r has no coordinates.", ms_cd)
        return None

    properties = feature.get("properties") or {}
    name = (
        (properties.get("SJONAMN") or properties.get("NAMN") or properties.get("NAME") or "")
        .strip()
    )
    eu_cd = (properties.get("EU_CD") or "").strip()

    return {
        "found": True,
        "name": name,
        "ms_cd": (properties.get("MS_CD") or ms_cd).strip(),
        "eu_cd": eu_cd,
        "geometry": geometry,
        "properties": properties,
    }


def _append_viss_source_to_description(description, ms_cd, eu_cd):
    source_line = (
        f"Källa: VISS vattenförekomst / Länsstyrelsen ArcGIS. "
        f"MS_CD: {ms_cd}."
    )
    if eu_cd:
        source_line += f" EU_CD: {eu_cd}."
    text = (description or "").strip()
    if source_line in text:
        return text
    if text:
        return f"{text}\n\n{source_line}"
    return source_line


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

        features.extend(_build_observation_map_features(org))

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

    waterbodies = []
    import_viss_waterbody_id = None
    if org:
        waterbodies = list(
            WaterBody.objects.for_org(org)
            .filter(is_active=True)
            .order_by("name", "id")
        )
        if waterbodies:
            import_viss_waterbody_id = waterbodies[0].pk
            if selected_water_id is not None:
                for water_body in waterbodies:
                    if water_body.pk == selected_water_id:
                        import_viss_waterbody_id = water_body.pk
                        break

    import_viss_ms_cd = (request.GET.get("viss_ms_cd") or "").strip()[:50]

    context = {
        "geojson_data": geojson_data,
        "fvof_focus": fvof_focus,
        "has_org": bool(org),
        "org_name": org.name if org else "",
        "selected_action_id": selected_action_id,
        "selected_water_id": selected_water_id,
        "waterbodies": waterbodies,
        "import_viss_waterbody_id": import_viss_waterbody_id,
        "import_viss_ms_cd": import_viss_ms_cd,
    }
    response = render(request, "maps/map_page.html", context)
    response["Cache-Control"] = "no-store, max-age=0"
    return response


@login_required
@require_POST
def import_fvo_boundary(request):
    org = getattr(request, "org", None)
    if org is None:
        messages.error(request, "Ingen aktiv organisation vald. FVO-gräns kunde inte importeras.")
        return redirect("maps:map_page")

    matched_fvof = fetch_fvof_focus_for_org(org.name)
    if not matched_fvof or not matched_fvof.get("found"):
        messages.error(
            request,
            f"Ingen officiell FVO-gräns hittades för {org.name} i Fiskekartan.",
        )
        return redirect("maps:map_page")

    geometry = _extract_geometry(matched_fvof.get("geojson"))
    if not geometry or geometry.get("type") not in {"Polygon", "MultiPolygon"}:
        messages.error(
            request,
            "FVO-gränsen kunde inte läsas från Fiskekartan. Geometrin var ogiltig.",
        )
        return redirect("maps:map_page")

    if not geometry.get("coordinates"):
        messages.error(
            request,
            "FVO-gränsen kunde inte läsas från Fiskekartan. Geometrin saknade koordinater.",
        )
        return redirect("maps:map_page")

    boundary_name = (matched_fvof.get("name") or org.name).strip() or org.name
    geometry_to_store = json.loads(json.dumps(geometry))

    boundary = (
        MapBoundary.objects.for_org(org)
        .filter(is_active=True)
        .order_by("id")
        .first()
    )

    if boundary:
        boundary.name = boundary_name
        boundary.geojson = geometry_to_store
        boundary.is_active = True
        boundary.save(update_fields=["name", "geojson", "is_active", "updated_at"])
        action_label = "uppdaterats"
        boundary_id = boundary.pk
    else:
        boundary = MapBoundary.objects.create(
            org=org,
            name=boundary_name,
            geojson=geometry_to_store,
            is_active=True,
        )
        action_label = "importerats"
        boundary_id = boundary.pk

    (
        MapBoundary.objects.for_org(org)
        .filter(is_active=True)
        .exclude(pk=boundary_id)
        .update(is_active=False)
    )

    messages.success(
        request,
        f"FVO-gränsen \"{boundary_name}\" har {action_label} från Fiskekartan.",
    )
    return redirect("maps:map_page")


@login_required
@require_POST
def import_waterbody_from_viss(request, waterbody_id):
    org = getattr(request, "org", None)
    if org is None:
        messages.error(
            request,
            "Ingen aktiv organisation vald. Vatten kunde inte importeras från VISS.",
        )
        return redirect("maps:map_page")

    try:
        water_body = WaterBody.objects.for_org(org).get(pk=waterbody_id, is_active=True)
    except WaterBody.DoesNotExist:
        messages.error(request, "Vattnet hittades inte i den aktiva organisationen.")
        return redirect("maps:map_page")

    if water_body.water_type == WaterBodyType.RIVER:
        messages.error(
            request,
            "Vattendrag stöds inte i denna version. Layer 55 för vattendrag kommer i nästa steg.",
        )
        return redirect("maps:map_page")

    ms_cd = (request.POST.get("viss_ms_cd") or "").strip()
    if not ms_cd:
        messages.error(request, "Ange MS_CD för vattenförekomsten i VISS.")
        return redirect("maps:map_page")

    result = fetch_viss_lake_geometry_by_ms_cd(ms_cd)
    if not result:
        messages.error(
            request,
            f"Ingen sjöpolygon hittades i VISS för MS_CD {ms_cd}.",
        )
        return redirect(f"{reverse('maps:map_page')}?viss_ms_cd={urllib.parse.quote(ms_cd)}")

    geometry_to_store = json.loads(json.dumps(result["geometry"]))
    water_body.geojson = geometry_to_store

    viss_name = (result.get("name") or "").strip()
    if viss_name and not (water_body.name or "").strip():
        water_body.name = viss_name

    water_body.description = _append_viss_source_to_description(
        water_body.description,
        result.get("ms_cd") or ms_cd,
        result.get("eu_cd") or "",
    )
    water_body.save(update_fields=["name", "geojson", "description", "updated_at"])

    display_name = water_body.name or viss_name or f"MS_CD {ms_cd}"
    messages.success(
        request,
        f"\"{display_name}\" har uppdaterats med sjöpolygon från VISS.",
    )
    return redirect("maps:map_page")
