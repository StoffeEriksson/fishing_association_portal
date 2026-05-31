import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.db import IntegrityError
from django.utils import timezone

from maps.models import MapBoundary, WaterBody, WaterBodyType

logger = logging.getLogger(__name__)

VISS_MAPSERVER_URL = (
    "https://ext-geodata-applikationer.lansstyrelsen.se/arcgis/rest/services/"
    "VISS/lst_viss_api/MapServer"
)
VISS_LAKE_LAYER_ID = 56
VISS_RIVER_LAYER_ID = 55
VISS_SPATIAL_QUERY_TIMEOUT_SECONDS = 25
VISS_SPATIAL_RESULT_RECORD_COUNT = 2000

VISS_GEOMETRY_SOURCE_LAKE = "viss_arcgis_layer_56"
VISS_GEOMETRY_SOURCE_RIVER = "viss_arcgis_layer_55"

LAKE_GEOMETRY_TYPES = frozenset({"Polygon", "MultiPolygon"})
RIVER_GEOMETRY_TYPES = frozenset({"LineString", "MultiLineString"})

LAKE_NAME_KEYS = ("SJONAMN", "NAME_VISS", "NAMN", "NAME")
RIVER_NAME_KEYS = ("VNAMN", "Namn_VISS", "NAMN", "NAME")


def fetch_viss_waters_within_geometry(boundary_geojson):
    """
    Hämta VISS vattenförekomster (sjöar + vattendrag) som skär FVO-gränsen.

    Tar GeoJSON-geometri (Polygon/MultiPolygon) och returnerar
    normaliserad lista. Sparar inget i databasen.
    """
    esri_polygon = _boundary_geojson_to_esri_polygon(boundary_geojson)
    if esri_polygon is None:
        return []

    by_ms_cd = {}

    for layer_id, water_type, geometry_source, valid_types, name_keys in (
        (
            VISS_LAKE_LAYER_ID,
            WaterBodyType.LAKE,
            VISS_GEOMETRY_SOURCE_LAKE,
            LAKE_GEOMETRY_TYPES,
            LAKE_NAME_KEYS,
        ),
        (
            VISS_RIVER_LAYER_ID,
            WaterBodyType.RIVER,
            VISS_GEOMETRY_SOURCE_RIVER,
            RIVER_GEOMETRY_TYPES,
            RIVER_NAME_KEYS,
        ),
    ):
        features = _query_layer_features(layer_id, esri_polygon)
        for feature in features:
            normalized = _normalize_feature(
                feature,
                water_type=water_type,
                geometry_source=geometry_source,
                valid_geometry_types=valid_types,
                name_keys=name_keys,
            )
            if normalized is None:
                continue
            ms_cd = normalized["viss_ms_cd"]
            if ms_cd in by_ms_cd:
                logger.info(
                    "Skipping duplicate VISS feature MS_CD %r (layer %s).",
                    ms_cd,
                    layer_id,
                )
                continue
            by_ms_cd[ms_cd] = normalized

    results = list(by_ms_cd.values())
    results.sort(
        key=lambda item: (
            0 if item["water_type"] == WaterBodyType.LAKE else 1,
            (item["name"] or "").lower(),
            item["viss_ms_cd"],
        )
    )
    return results


def _boundary_geojson_to_esri_polygon(boundary_geojson):
    geo = _parse_geojson(boundary_geojson)
    if geo is None:
        return None

    geom_type = geo.get("type")
    if geom_type == "Polygon":
        rings = geo.get("coordinates") or []
        if not rings or not rings[0]:
            logger.warning("VISS spatial query: empty Polygon boundary.")
            return None
        return {"rings": rings, "spatialReference": {"wkid": 4326}}

    if geom_type == "MultiPolygon":
        rings = []
        for polygon in geo.get("coordinates") or []:
            if polygon and polygon[0]:
                rings.append(polygon[0])
        if not rings:
            logger.warning("VISS spatial query: empty MultiPolygon boundary.")
            return None
        return {"rings": rings, "spatialReference": {"wkid": 4326}}

    logger.warning(
        "VISS spatial query: unsupported boundary geometry type %r.",
        geom_type,
    )
    return None


def _parse_geojson(geojson_data):
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


def _query_layer_features(layer_id, esri_polygon):
    params = {
        "where": "1=1",
        "geometry": json.dumps(esri_polygon),
        "geometryType": "esriGeometryPolygon",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "geojson",
        "resultRecordCount": str(VISS_SPATIAL_RESULT_RECORD_COUNT),
    }
    query_url = f"{VISS_MAPSERVER_URL}/{layer_id}/query"
    body = urllib.parse.urlencode(params).encode("utf-8")

    try:
        request = urllib.request.Request(
            query_url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "User-Agent": "Windify/1.0",
            },
        )
        with urllib.request.urlopen(
            request, timeout=VISS_SPATIAL_QUERY_TIMEOUT_SECONDS
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
            "VISS spatial query failed for layer %s: %s",
            layer_id,
            exc,
        )
        return []

    if payload.get("error"):
        logger.warning(
            "VISS spatial query error for layer %s: %s",
            layer_id,
            payload.get("error"),
        )
        return []

    features = payload.get("features") or []
    if payload.get("exceededTransferLimit"):
        logger.warning(
            "VISS spatial query layer %s exceeded transfer limit "
            "(%s features returned).",
            layer_id,
            len(features),
        )
    return features


def _normalize_feature(
    feature,
    *,
    water_type,
    geometry_source,
    valid_geometry_types,
    name_keys,
):
    properties = feature.get("properties") or {}
    ms_cd = (
        properties.get("MS_CD") or properties.get("VISS_MS_CD") or ""
    ).strip()
    if not ms_cd:
        logger.info(
            "Skipping VISS feature without MS_CD on layer %s.",
            geometry_source,
        )
        return None

    geometry = feature.get("geometry")
    if not geometry or geometry.get("type") not in valid_geometry_types:
        logger.warning(
            "Skipping VISS feature %r with invalid geometry type %s.",
            ms_cd,
            (geometry or {}).get("type"),
        )
        return None

    if not geometry.get("coordinates"):
        logger.warning("Skipping VISS feature %r with no coordinates.", ms_cd)
        return None

    eu_cd = (
        properties.get("EU_CD") or properties.get("VISS_EU_CD") or ""
    ).strip()
    name = _extract_name(properties, name_keys, ms_cd, water_type)

    return {
        "name": name,
        "source_name": name,
        "viss_ms_cd": ms_cd,
        "viss_eu_cd": eu_cd,
        "water_type": water_type,
        "geometry": geometry,
        "geometry_source": geometry_source,
        "properties": properties,
    }


def _extract_name(properties, name_keys, ms_cd, water_type):
    for key in name_keys:
        value = (properties.get(key) or "").strip()
        if value:
            return value
    if water_type == WaterBodyType.RIVER:
        return f"Vattendrag {ms_cd}"
    return ""


def _empty_import_result(errors=None):
    return {
        "created": 0,
        "updated": 0,
        "skipped": 0,
        "total": 0,
        "lakes": 0,
        "rivers": 0,
        "errors": list(errors or []),
    }


def _append_viss_import_source_description(description, ms_cd, eu_cd):
    source_line = (
        f"Källa: VISS/Länsstyrelsen vattenförekomst. MS_CD: {ms_cd}."
    )
    if eu_cd:
        source_line += f" EU_CD: {eu_cd}."
    text = (description or "").strip()
    if source_line in text:
        return text
    if text:
        return f"{text}\n\n{source_line}"
    return source_line


def get_viss_import_preview_for_org(org):
    """
    Hämta VISS-vatten inom org:s FVO-gräns och jämför mot befintliga WaterBody.
  """
    if org is None:
        return {"error": "Ingen organisation angiven.", "items": []}

    boundary = (
        MapBoundary.objects.for_org(org)
        .filter(is_active=True)
        .order_by("id")
        .first()
    )
    if boundary is None or not boundary.geojson:
        return {
            "error": "Ingen aktiv FVO-gräns hittades. Importera FVO-gräns först.",
            "items": [],
        }

    fetched = fetch_viss_waters_within_geometry(boundary.geojson)
    if not fetched:
        return {
            "error": "Inga vattenförekomster hittades inom FVO-gränsen i VISS.",
            "items": [],
        }

    existing_ms_cd = set(
        WaterBody.objects.for_org(org)
        .exclude(viss_ms_cd="")
        .values_list("viss_ms_cd", flat=True)
    )

    preview_items = []
    for item in fetched:
        ms_cd = (item.get("viss_ms_cd") or "").strip()
        if not ms_cd:
            continue
        display_name = (
            (item.get("name") or "").strip()
            or (item.get("source_name") or "").strip()
            or f"Vatten {ms_cd}"
        )
        water_type = item.get("water_type")
        already_imported = ms_cd in existing_ms_cd
        preview_items.append(
            {
                "name": display_name,
                "water_type": water_type,
                "water_type_label": (
                    WaterBodyType(water_type).label
                    if water_type in WaterBodyType.values
                    else water_type
                ),
                "viss_ms_cd": ms_cd,
                "viss_eu_cd": (item.get("viss_eu_cd") or "").strip(),
                "geometry_source": item.get("geometry_source") or "",
                "already_imported": already_imported,
            }
        )

    lakes = sum(
        1 for row in preview_items if row["water_type"] == WaterBodyType.LAKE
    )
    rivers = sum(
        1 for row in preview_items if row["water_type"] == WaterBodyType.RIVER
    )
    already_count = sum(1 for row in preview_items if row["already_imported"])

    return {
        "error": None,
        "items": preview_items,
        "total": len(preview_items),
        "lakes": lakes,
        "rivers": rivers,
        "new_count": len(preview_items) - already_count,
        "already_imported": already_count,
    }


def import_viss_waters_for_org(org, only_ms_cd=None):
    """
    Importera/uppdatera WaterBody från VISS för alla vatten som skär org:s FVO-gräns.
    Idempotent via (org, viss_ms_cd).

    only_ms_cd: valfri lista med MS_CD att importera (övriga hoppas över).
    """
    if org is None:
        return _empty_import_result(["Ingen organisation angiven."])

    boundary = (
        MapBoundary.objects.for_org(org)
        .filter(is_active=True)
        .order_by("id")
        .first()
    )
    if boundary is None or not boundary.geojson:
        return _empty_import_result(
            ["Ingen aktiv FVO-gräns hittades. Importera FVO-gräns först."]
        )

    items = fetch_viss_waters_within_geometry(boundary.geojson)
    if not items:
        return _empty_import_result(
            ["Inga vattenförekomster hittades inom FVO-gränsen i VISS."]
        )

    if only_ms_cd is not None:
        allowed_ms_cd = {
            (value or "").strip()
            for value in only_ms_cd
            if (value or "").strip()
        }
        items = [
            item
            for item in items
            if (item.get("viss_ms_cd") or "").strip() in allowed_ms_cd
        ]
        if not items:
            return _empty_import_result(["Inga valda vatten att importera."])

    created_count = 0
    updated_count = 0
    skipped_count = 0
    lake_count = 0
    river_count = 0
    errors = []
    now = timezone.now()

    for item in items:
        ms_cd = (item.get("viss_ms_cd") or "").strip()
        if not ms_cd:
            skipped_count += 1
            continue

        if item.get("water_type") == WaterBodyType.LAKE:
            lake_count += 1
        elif item.get("water_type") == WaterBodyType.RIVER:
            river_count += 1

        display_name = (
            (item.get("name") or "").strip()
            or (item.get("source_name") or "").strip()
            or f"Vatten {ms_cd}"
        )
        eu_cd = (item.get("viss_eu_cd") or "").strip()
        geometry = item.get("geometry")
        if not geometry:
            skipped_count += 1
            errors.append(f"MS_CD {ms_cd}: saknar geometri.")
            continue

        geometry_to_store = json.loads(json.dumps(geometry))
        source_name = (item.get("source_name") or "").strip() or display_name

        defaults = {
            "name": display_name,
            "water_type": item["water_type"],
            "geojson": geometry_to_store,
            "viss_eu_cd": eu_cd,
            "external_source": "viss",
            "geometry_source": item.get("geometry_source") or "",
            "source_name": source_name,
            "imported_at": now,
            "is_active": True,
        }

        created = False
        needs_full_save = False
        try:
            water_body, created = WaterBody.objects.update_or_create(
                org=org,
                viss_ms_cd=ms_cd,
                defaults=defaults,
            )
        except IntegrityError:
            logger.warning(
                "VISS import race on MS_CD %r for org %r; retrying update.",
                ms_cd,
                org.pk,
            )
            try:
                water_body = WaterBody.objects.for_org(org).get(viss_ms_cd=ms_cd)
            except WaterBody.DoesNotExist:
                skipped_count += 1
                errors.append(f"MS_CD {ms_cd}: kunde inte sparas (konflikt).")
                continue
            created = False
            needs_full_save = True
            for field, value in defaults.items():
                setattr(water_body, field, value)

        prior_description = "" if created else (water_body.description or "")
        water_body.description = _append_viss_import_source_description(
            prior_description,
            ms_cd,
            eu_cd,
        )
        if needs_full_save:
            water_body.save(
                update_fields=list(defaults.keys()) + ["description", "updated_at"]
            )
        else:
            water_body.save(update_fields=["description", "updated_at"])

        if created:
            created_count += 1
            manual_match = (
                WaterBody.objects.for_org(org)
                .filter(viss_ms_cd="", name__iexact=display_name)
                .exists()
            )
            if manual_match:
                logger.info(
                    "VISS import created MS_CD %r; manual WaterBody with "
                    "same name %r exists (merge later).",
                    ms_cd,
                    display_name,
                )
        else:
            updated_count += 1

    return {
        "created": created_count,
        "updated": updated_count,
        "skipped": skipped_count,
        "total": len(items),
        "lakes": lake_count,
        "rivers": river_count,
        "errors": errors,
    }


VISS_REST_API_URL = "https://viss.lansstyrelsen.se/api"
VISS_REST_TIMEOUT_SECONDS = 20


def _health_result(
    *,
    eco_status=None,
    chem_status=None,
    risk=None,
    mkn=None,
    fish=None,
    available=False,
    message="",
):
    return {
        "eco_status": eco_status,
        "chem_status": chem_status,
        "risk": risk,
        "mkn": mkn,
        "fish": fish,
        "source": "VISS",
        "available": available,
        "message": message,
    }


def _water_public_id(water_body):
    ms_cd = (getattr(water_body, "viss_ms_cd", None) or "").strip()
    if ms_cd:
        return ms_cd
    return (getattr(water_body, "viss_eu_cd", None) or "").strip()


def _unwrap_viss_records(payload, *keys):
    if payload is None:
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []

    for key in keys:
        if key not in payload:
            continue
        value = payload[key]
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            return [value]

    if any(key in payload for key in ("MS_CD", "Ms_CD", "EU_CD", "Eu_CD", "UUID")):
        return [payload]
    return []


def _nested_dict_items(parent, container_key, item_key=None):
    if not isinstance(parent, dict):
        return []

    container = parent.get(container_key)
    if container is None:
        return []
    if isinstance(container, list):
        return [item for item in container if isinstance(item, dict)]
    if not isinstance(container, dict):
        return []

    if item_key:
        items = container.get(item_key)
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
        if isinstance(items, dict):
            return [items]
    return [container]


def _classification_motivations(water_record):
    items = _nested_dict_items(
        water_record,
        "WaterClassificationMotivations",
        "WaterClassificationMotivation",
    )
    if items:
        return items
    return _nested_dict_items(
        water_record,
        "waterClassificationMotivations",
        "waterClassificationMotivation",
    )


def _format_status_value(code, label=None):
    code_text = (code or "").strip()
    label_text = (label or "").strip()
    if label_text and code_text and label_text.lower() != code_text.lower():
        return f"{label_text} ({code_text})"
    return label_text or code_text or None


def _pick_classification(motivations, include_terms, exclude_terms=()):
    include_terms = tuple(term.lower() for term in include_terms)
    exclude_terms = tuple(term.lower() for term in exclude_terms)

    best = None
    best_score = -1
    for motivation in motivations:
        parameter = (
            motivation.get("Parameter")
            or motivation.get("parameter")
            or motivation.get("SwedishName")
            or motivation.get("swedishName")
            or ""
        ).strip()
        parameter_lower = parameter.lower()
        if not parameter_lower:
            continue
        if exclude_terms and any(term in parameter_lower for term in exclude_terms):
            continue
        if not any(term in parameter_lower for term in include_terms):
            continue

        score = max(len(term) for term in include_terms if term in parameter_lower)
        if "status" in parameter_lower:
            score += 10
        if score > best_score:
            classification = motivation.get("Classification") or motivation.get(
                "classification"
            )
            value = motivation.get("Value") or motivation.get("value")
            best = _format_status_value(classification or value, parameter)
            best_score = score
    return best


def _extract_classifications_from_motivations(motivations):
    eco_status = _pick_classification(
        motivations,
        include_terms=("ekologisk status", "ekologisk potential"),
        exclude_terms=("kvalitetsfaktor", "biologisk"),
    )
    chem_status = _pick_classification(
        motivations,
        include_terms=("kemisk status",),
        exclude_terms=("prioriterade", "kvalitetsfaktor"),
    )
    fish = _pick_classification(
        motivations,
        include_terms=("fisk",),
        exclude_terms=("fiske", "fiskvatten", "fisket"),
    )
    return eco_status, chem_status, fish


def _extract_mkn_summary(mkn_records):
    parts = []
    for water in mkn_records:
        sections = _nested_dict_items(water, "MKNSections", "MKNSection")
        if not sections:
            sections = _nested_dict_items(water, "mknSections", "mknSection")
        for section in sections:
            name = (
                section.get("SwedishName")
                or section.get("swedishName")
                or section.get("Name")
                or section.get("name")
                or ""
            ).strip()
            current = (
                section.get("CurrentStatusSwedishName")
                or section.get("currentStatusSwedishName")
                or section.get("CurrentStatus")
                or section.get("currentStatus")
                or ""
            ).strip()
            target = (
                section.get("TargetStatusSwedishName")
                or section.get("targetStatusSwedishName")
                or section.get("TargetStatus")
                or section.get("targetStatus")
                or ""
            ).strip()
            if not name and not current and not target:
                continue
            section_parts = []
            if name:
                section_parts.append(name)
            if current:
                section_parts.append(f"nu {current}")
            if target:
                section_parts.append(f"mål {target}")
            parts.append(" · ".join(section_parts))
    if not parts:
        return None
    return "; ".join(parts)


def _extract_risk_summary(risk_records):
    flagged = []
    for water in risk_records:
        sections = _nested_dict_items(water, "WaterRiskSections", "WaterRiskSection")
        if not sections:
            sections = _nested_dict_items(water, "waterRiskSections", "waterRiskSection")
        for section in sections:
            impacts = _nested_dict_items(section, "WaterRiskImpacts", "WaterRiskImpact")
            if not impacts:
                impacts = _nested_dict_items(
                    section, "waterRiskImpacts", "waterRiskImpact"
                )
            for impact in impacts:
                risk_value = (impact.get("Risk") or impact.get("risk") or "").strip()
                impact_name = (impact.get("Impact") or impact.get("impact") or "").strip()
                if not risk_value:
                    continue
                if "ingen risk" in risk_value.lower():
                    continue
                if impact_name:
                    flagged.append(f"{impact_name}: {risk_value}")
                else:
                    flagged.append(risk_value)
    if not flagged:
        return None
    return "; ".join(flagged[:4])


def _viss_rest_request(method, api_key, **params):
    query = {
        "method": method,
        "format": "json",
        "apikey": api_key,
    }
    for key, value in params.items():
        if value is None:
            continue
        query[key] = value

    url = f"{VISS_REST_API_URL}?{urllib.parse.urlencode(query)}"
    try:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "Windify/1.0",
            },
        )
        with urllib.request.urlopen(
            request, timeout=VISS_REST_TIMEOUT_SECONDS
        ) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        logger.warning("VISS REST %s failed with HTTP %s.", method, exc.code)
        if exc.code in {401, 403}:
            return None, "VISS API kunde inte autentiseras. Kontrollera API-nyckeln."
        return None, f"VISS API svarade med HTTP {exc.code}."
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.warning("VISS REST %s request failed: %s", method, exc)
        return None, "VISS API är inte tillgängligt just nu."
    except UnicodeDecodeError:
        logger.warning("VISS REST %s returned undecodable response.", method)
        return None, "VISS API returnerade ogiltigt svar."

    stripped = raw.lstrip()
    if stripped.startswith("<"):
        return None, "VISS API kunde inte autentiseras. Kontrollera API-nyckeln."

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("VISS REST %s returned non-JSON payload.", method)
        return None, "VISS API returnerade ogiltigt svar."

    if isinstance(payload, dict):
        error = payload.get("error") or payload.get("Error")
        if error:
            error_text = str(error).strip()
            if error_text:
                return None, error_text

    return payload, None


def fetch_water_health(water_body):
    """
    Hämta sammanfattad vattenhälsa från VISS REST API för ett WaterBody.

    Returnerar None om VISS_API_KEY saknas i settings.
    """
    api_key = (getattr(settings, "VISS_API_KEY", None) or "").strip()
    if not api_key:
        return None

    water_public_id = _water_public_id(water_body)
    if not water_public_id:
        return _health_result(message="Ingen VISS-status tillgänglig")

    request_params = {"waterpublicid": water_public_id}
    eco_status = None
    chem_status = None
    fish = None
    mkn = None
    risk = None
    auth_error = None
    had_successful_response = False

    classifications_payload, error = _viss_rest_request(
        "latestwaterclassificationmotivations",
        api_key,
        **request_params,
    )
    if error and "autentiseras" in error.lower():
        auth_error = error
    elif error:
        logger.info(
            "VISS latestwaterclassificationmotivations for %r: %s",
            water_public_id,
            error,
        )
    elif classifications_payload is not None:
        had_successful_response = True
        motivations = []
        for water in _unwrap_viss_records(
            classifications_payload,
            "Water",
            "ArrayOfWater",
        ):
            motivations.extend(_classification_motivations(water))
        eco_status, chem_status, fish = _extract_classifications_from_motivations(
            motivations
        )

    if auth_error is None:
        mkn_payload, error = _viss_rest_request("mkn", api_key, **request_params)
        if error and "autentiseras" in error.lower():
            auth_error = error
        elif error:
            logger.info("VISS mkn for %r: %s", water_public_id, error)
        elif mkn_payload is not None:
            had_successful_response = True
            mkn = _extract_mkn_summary(
                _unwrap_viss_records(mkn_payload, "WaterMKN", "ArrayOfWaterMKN", "Water")
            )

    if auth_error is None:
        risk_payload, error = _viss_rest_request(
            "waterriskclassifications",
            api_key,
            **request_params,
        )
        if error and "autentiseras" in error.lower():
            auth_error = error
        elif error:
            logger.info("VISS waterriskclassifications for %r: %s", water_public_id, error)
        elif risk_payload is not None:
            had_successful_response = True
            risk = _extract_risk_summary(
                _unwrap_viss_records(risk_payload, "Water", "ArrayOfWater")
            )

    if auth_error is None:
        waters_payload, error = _viss_rest_request("waters", api_key, **request_params)
        if error and "autentiseras" in error.lower():
            auth_error = error
        elif error:
            logger.info("VISS waters for %r: %s", water_public_id, error)
        elif waters_payload is not None:
            had_successful_response = True

    if auth_error:
        return _health_result(message=auth_error)

    if not had_successful_response:
        return _health_result(message="VISS API är inte tillgängligt just nu.")

    if any(value for value in (eco_status, chem_status, risk, mkn, fish)):
        return _health_result(
            eco_status=eco_status,
            chem_status=chem_status,
            risk=risk,
            mkn=mkn,
            fish=fish,
            available=True,
        )

    return _health_result(message="Ingen VISS-status tillgänglig")
