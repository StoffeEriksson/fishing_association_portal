import json
import logging
import urllib.error
import urllib.parse
import urllib.request

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


def import_viss_waters_for_org(org):
    """
    Importera/uppdatera WaterBody från VISS för alla vatten som skär org:s FVO-gräns.
    Idempotent via (org, viss_ms_cd).
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
