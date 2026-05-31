import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from fisheries.labels import (
    get_action_status_label,
    get_observation_category_label,
    get_observation_status_label,
)
from fisheries.models import ActionArea, ActionStatus, Observation

from .models import MapBoundary, WaterBody, WaterBodyType
from .services.fvo_onboarding import run_fvo_onboarding as execute_fvo_onboarding
from .services.fvo_onboarding import save_fvo_boundary_for_org
from .services.viss import (
    fetch_water_health,
    get_viss_import_preview_for_org,
    import_viss_waters_for_org,
)

logger = logging.getLogger(__name__)

_VALID_MAP_PAGE_MODES = frozenset(
    {
        "create_observation",
        "create_action",
        "pick_observation",
        "pick_action",
    }
)

_MAP_PICK_RETURN_URLS = {
    "pick_observation": "/fisheries/observations/create/",
    "pick_action": "/fisheries/actions/create/",
}

_OBSERVATION_PICK_DETAIL_RE = re.compile(r"^/fisheries/observations/(\d+)/?$")
_ACTION_PICK_DETAIL_RE = re.compile(r"^/fisheries/actions/(\d+)/?$")


def _validate_pick_return_url(mode, return_url, org):
    default = _MAP_PICK_RETURN_URLS.get(mode)
    if not return_url:
        return default

    path = urllib.parse.urlparse(return_url).path
    if not path.startswith("/fisheries/"):
        return default

    if mode == "pick_observation":
        create_path = reverse("fisheries:observation_create")
        if path == create_path or path == f"{create_path}/":
            return path if path.endswith("/") else create_path
        match = _OBSERVATION_PICK_DETAIL_RE.match(path)
        if match and org is not None:
            pk = int(match.group(1))
            if Observation.objects.for_org(org).not_trashed().filter(pk=pk).exists():
                return path
    elif mode == "pick_action":
        create_path = reverse("fisheries:action_create")
        if path == create_path or path == f"{create_path}/":
            return path if path.endswith("/") else create_path
        match = _ACTION_PICK_DETAIL_RE.match(path)
        if match and org is not None:
            pk = int(match.group(1))
            if ActionArea.objects.for_org(org).not_trashed().filter(pk=pk).exists():
                return path

    return default


def _resolve_map_page_mode(request, org=None):
    mode = (request.GET.get("mode") or "").strip()
    if mode not in _VALID_MAP_PAGE_MODES:
        return None, None
    if mode.startswith("pick_"):
        return_url = (request.GET.get("return") or "").strip()
        validated = _validate_pick_return_url(mode, return_url, org)
        return mode, validated
    return mode, None

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


def _observation_map_coordinates(observation):
    if observation.latitude is not None and observation.longitude is not None:
        return [float(observation.longitude), float(observation.latitude)]

    geometry_source = _observation_geometry_source(observation)
    if not geometry_source:
        return None
    return _geometry_bbox_center(geometry_source)


def _action_map_geometry(action):
    if action.latitude is not None and action.longitude is not None:
        return {
            "type": "Point",
            "coordinates": [float(action.longitude), float(action.latitude)],
        }
    return action.geojson


def _build_observation_map_features(org):
    if org is None:
        return []

    observations = (
        Observation.objects.for_org(org)
        .not_trashed()
        .filter(linked_action__isnull=True)
        .select_related("water_body")
    )
    features = []

    for observation in observations:
        center = _observation_map_coordinates(observation)
        if not center:
            logger.info(
                "Observation %s skipped on map: could not derive point from geometry.",
                observation.pk,
            )
            continue

        water_body_name = ""
        if observation.water_body:
            water_body_name = observation.water_body.name

        has_exact_position = (
            observation.latitude is not None and observation.longitude is not None
        )
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": center,
                },
                "properties": {
                    "type": "observation",
                    "exact_position": has_exact_position,
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
    selected_observation_id = None

    observation_id = (request.GET.get("observation_id") or "").strip()
    if org and observation_id.isdigit():
        selected_observation = Observation.objects.for_org(org).not_trashed().filter(
            pk=observation_id,
        ).first()
        if selected_observation:
            if selected_observation.linked_action_id:
                selected_action_id = selected_observation.linked_action_id
            else:
                selected_observation_id = selected_observation.pk

    action_id = (request.GET.get("action_id") or "").strip()
    if org and action_id.isdigit():
        selected_action = ActionArea.objects.for_org(org).not_trashed().filter(pk=action_id).first()
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
                        "detail_url": reverse(
                            "maps:waterbody_detail",
                            args=[water.pk],
                        ),
                    },
                    "geometry": water.geojson,
                }
            )

        action_areas = ActionArea.objects.for_org(org).not_trashed()
        for action in action_areas:
            geometry = _action_map_geometry(action)
            if not geometry:
                continue
            status_label = ActionStatus(action.status).label
            has_exact_position = (
                action.latitude is not None and action.longitude is not None
            )
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
                        "exact_position": has_exact_position,
                    },
                    "geometry": geometry,
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
    if (
        org
        and selected_action_id is None
        and selected_water_id is None
        and selected_observation_id is None
    ):
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

    map_create_mode, map_pick_return_url = _resolve_map_page_mode(request, org)

    has_map_boundary = False
    if org:
        has_map_boundary = MapBoundary.objects.for_org(org).filter(
            is_active=True
        ).exists()

    context = {
        "geojson_data": geojson_data,
        "fvof_focus": fvof_focus,
        "has_org": bool(org),
        "has_map_boundary": has_map_boundary,
        "org_name": org.name if org else "",
        "selected_action_id": selected_action_id,
        "selected_water_id": selected_water_id,
        "selected_observation_id": selected_observation_id,
        "waterbodies": waterbodies,
        "import_viss_waterbody_id": import_viss_waterbody_id,
        "import_viss_ms_cd": import_viss_ms_cd,
        "map_create_mode": map_create_mode,
        "map_pick_return_url": map_pick_return_url,
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

    boundary_result = save_fvo_boundary_for_org(org, matched_fvof)
    if not boundary_result.get("ok"):
        messages.error(request, boundary_result["error"])
        return redirect("maps:map_page")

    action_label = (
        "importerats"
        if boundary_result["action"] == "created"
        else "uppdaterats"
    )
    messages.success(
        request,
        f"FVO-gränsen \"{boundary_result['name']}\" har {action_label} från Fiskekartan.",
    )
    return redirect("maps:map_page")


@login_required
def run_fvo_onboarding(request):
    org = getattr(request, "org", None)
    if org is None:
        messages.error(
            request,
            "Ingen aktiv organisation vald. FVO-onboarding kunde inte köras.",
        )
        return redirect("maps:map_page")

    result = None
    if request.method == "POST":
        result = execute_fvo_onboarding(org)

    context = {
        "org_name": org.name,
        "result": result,
    }
    return render(request, "maps/onboarding_status.html", context)


def _handle_viss_import_result(request, result):
    for error_message in result.get("errors") or []:
        if result["created"] == 0 and result["updated"] == 0:
            messages.error(request, error_message)
            return redirect("maps:map_page")
        messages.warning(request, error_message)

    if result["total"] == 0 and result["created"] == 0 and result["updated"] == 0:
        messages.error(
            request,
            "Inga vattenförekomster kunde importeras från VISS.",
        )
        return redirect("maps:map_page")

    messages.success(
        request,
        (
            f"Import klar: {result['created']} skapade, "
            f"{result['updated']} uppdaterade."
        ),
    )
    return redirect("maps:map_page")


@login_required
def preview_viss_waters_within_fvo(request):
    org = getattr(request, "org", None)
    if org is None:
        messages.error(
            request,
            "Ingen aktiv organisation vald. Förhandsgranskning kunde inte visas.",
        )
        return redirect("maps:map_page")

    preview = get_viss_import_preview_for_org(org)
    if preview.get("error"):
        messages.error(request, preview["error"])
        return redirect("maps:map_page")

    context = {
        "org_name": org.name,
        "preview_items": preview["items"],
        "total": preview["total"],
        "lakes": preview["lakes"],
        "rivers": preview["rivers"],
        "new_count": preview["new_count"],
        "already_imported": preview["already_imported"],
    }
    return render(request, "maps/viss_import_preview.html", context)


@login_required
@require_POST
def import_selected_viss_waters(request):
    org = getattr(request, "org", None)
    if org is None:
        messages.error(
            request,
            "Ingen aktiv organisation vald. Vatten kunde inte importeras från VISS.",
        )
        return redirect("maps:map_page")

    import_all = (request.POST.get("import_action") or "").strip() == "all"
    if import_all:
        result = import_viss_waters_for_org(org)
    else:
        selected_ms_cd = request.POST.getlist("selected_ms_cd")
        if not selected_ms_cd:
            messages.error(request, "Inga vatten valda för import.")
            return redirect("maps:preview_viss_waters_within_fvo")
        result = import_viss_waters_for_org(org, only_ms_cd=selected_ms_cd)

    return _handle_viss_import_result(request, result)


@login_required
@require_POST
def import_viss_waters_within_fvo(request):
    org = getattr(request, "org", None)
    if org is None:
        messages.error(
            request,
            "Ingen aktiv organisation vald. Vatten kunde inte importeras från VISS.",
        )
        return redirect("maps:map_page")

    result = import_viss_waters_for_org(org)
    return _handle_viss_import_result(request, result)


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
    water_body.viss_ms_cd = (result.get("ms_cd") or ms_cd).strip()
    water_body.viss_eu_cd = (result.get("eu_cd") or "").strip()
    water_body.external_source = "viss"
    water_body.geometry_source = "viss_arcgis_layer_56"
    water_body.source_name = viss_name
    water_body.imported_at = timezone.now()
    water_body.save(
        update_fields=[
            "name",
            "geojson",
            "description",
            "viss_ms_cd",
            "viss_eu_cd",
            "external_source",
            "geometry_source",
            "source_name",
            "imported_at",
            "updated_at",
        ]
    )

    display_name = water_body.name or viss_name or f"MS_CD {ms_cd}"
    messages.success(
        request,
        f"\"{display_name}\" har uppdaterats med sjöpolygon från VISS.",
    )
    return redirect("maps:map_page")


def _format_external_source_label(external_source):
    if not external_source:
        return ""
    if external_source.lower() == "viss":
        return "VISS / Länsstyrelsen"
    return external_source


@login_required
def waterbody_list(request):
    org = getattr(request, "org", None)
    if org is None:
        messages.error(
            request,
            "Ingen aktiv organisation vald. Vattenöversikten kunde inte visas.",
        )
        return redirect("maps:map_page")

    water_bodies = (
        WaterBody.objects.for_org(org)
        .filter(is_active=True)
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
        .order_by("name", "id")
    )

    water_rows = [
        {
            "water_body": water_body,
            "water_type_label": water_body.get_water_type_display(),
            "observation_count": water_body.observation_count,
            "action_count": water_body.action_count,
        }
        for water_body in water_bodies
    ]

    context = {
        "water_rows": water_rows,
        "water_count": len(water_rows),
    }
    return render(request, "maps/waterbody_list.html", context)


@login_required
def waterbody_detail(request, waterbody_id):
    org = getattr(request, "org", None)
    if org is None:
        messages.error(
            request,
            "Ingen aktiv organisation vald. Vattnet kunde inte visas.",
        )
        return redirect("maps:map_page")

    try:
        water_body = WaterBody.objects.for_org(org).get(
            pk=waterbody_id,
            is_active=True,
        )
    except WaterBody.DoesNotExist:
        messages.error(request, "Vattnet hittades inte i den aktiva organisationen.")
        return redirect("maps:map_page")

    observations_qs = (
        Observation.objects.for_org(org)
        .not_trashed()
        .filter(water_body=water_body)
        .select_related("linked_action")
        .order_by("-created_at", "-id")
    )
    observation_count = observations_qs.count()
    recent_observations = observations_qs[:5]
    observation_rows = [
        {
            "observation": observation,
            "status_label": get_observation_status_label(observation.status),
            "category_label": get_observation_category_label(observation.category),
        }
        for observation in recent_observations
    ]

    actions_qs = (
        ActionArea.objects.for_org(org)
        .not_trashed()
        .filter(water_body=water_body)
        .select_related("responsible_user")
        .order_by("-created_at", "-id")
    )
    action_count = actions_qs.count()
    recent_actions = actions_qs[:5]
    action_rows = [
        {
            "action": action,
            "status_label": get_action_status_label(action.status),
        }
        for action in recent_actions
    ]

    external_source_label = _format_external_source_label(water_body.external_source)
    if water_body.viss_ms_cd:
        viss_summary = f"VISS {water_body.viss_ms_cd}"
    elif external_source_label:
        viss_summary = external_source_label
    else:
        viss_summary = "Ej importerad från VISS"

    viss_api_configured = bool((getattr(settings, "VISS_API_KEY", None) or "").strip())
    viss_health = fetch_water_health(water_body) if viss_api_configured else None

    context = {
        "water_body": water_body,
        "water_type_label": water_body.get_water_type_display(),
        "external_source_label": external_source_label,
        "viss_summary": viss_summary,
        "viss_api_configured": viss_api_configured,
        "viss_health": viss_health,
        "observation_rows": observation_rows,
        "action_rows": action_rows,
        "observation_count": observation_count,
        "action_count": action_count,
        "has_more_observations": observation_count > len(observation_rows),
        "has_more_actions": action_count > len(action_rows),
    }
    return render(request, "maps/waterbody_detail.html", context)
