import json
import logging

from django.conf import settings

from maps.models import MapBoundary, WaterBody
from maps.services.viss import import_viss_waters_for_org, update_waterbody_health_snapshot

logger = logging.getLogger(__name__)


def _onboarding_result(
    *,
    success=False,
    boundary_imported=False,
    boundary_name="",
    boundary_action=None,
    waters_imported=0,
    waters_created=0,
    waters_updated=0,
    waters_total=0,
    waters_skipped=0,
    lakes=0,
    rivers=0,
    health_updated=0,
    health_failed=0,
    health_skipped=0,
    errors=None,
):
    return {
        "success": success,
        "boundary_imported": boundary_imported,
        "boundary_name": boundary_name,
        "boundary_action": boundary_action,
        "waters_imported": waters_imported,
        "waters_created": waters_created,
        "waters_updated": waters_updated,
        "waters_total": waters_total,
        "waters_skipped": waters_skipped,
        "lakes": lakes,
        "rivers": rivers,
        "health_updated": health_updated,
        "health_failed": health_failed,
        "health_skipped": health_skipped,
        "errors": list(errors or []),
    }


def save_fvo_boundary_for_org(org, matched_fvof):
    """
    Spara eller uppdatera aktiv MapBoundary från Fiskekartan-träff.

    Returnerar dict med nycklarna ok, name, action (created|updated) eller error.
    """
    if org is None:
        return {"ok": False, "error": "Ingen organisation angiven."}

    if not matched_fvof or not matched_fvof.get("found"):
        return {"ok": False, "error": "Ingen FVO-träff att spara."}

    from maps.views import _extract_geometry

    geometry = _extract_geometry(matched_fvof.get("geojson"))
    if not geometry or geometry.get("type") not in {"Polygon", "MultiPolygon"}:
        return {
            "ok": False,
            "error": "FVO-gränsen kunde inte läsas från Fiskekartan. Geometrin var ogiltig.",
        }

    if not geometry.get("coordinates"):
        return {
            "ok": False,
            "error": (
                "FVO-gränsen kunde inte läsas från Fiskekartan. "
                "Geometrin saknade koordinater."
            ),
        }

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
        action = "updated"
        boundary_id = boundary.pk
    else:
        boundary = MapBoundary.objects.create(
            org=org,
            name=boundary_name,
            geojson=geometry_to_store,
            is_active=True,
        )
        action = "created"
        boundary_id = boundary.pk

    (
        MapBoundary.objects.for_org(org)
        .filter(is_active=True)
        .exclude(pk=boundary_id)
        .update(is_active=False)
    )

    return {
        "ok": True,
        "name": boundary_name,
        "action": action,
        "boundary_id": boundary_id,
    }


def _prefetch_health_snapshots_for_org(org):
    """
    Best-effort: uppdatera VISS-hälsa för alla aktiva vatten i org.

    Returnerar health_updated, health_failed, health_skipped och extra errors.
    """
    water_bodies = list(
        WaterBody.objects.for_org(org).filter(is_active=True).order_by("name", "id")
    )
    total_waters = len(water_bodies)

    api_key = (getattr(settings, "VISS_API_KEY", None) or "").strip()
    if not api_key:
        logger.info(
            "FVO onboarding health prefetch skipped for org %r: VISS_API_KEY missing.",
            org.pk,
        )
        return {
            "health_updated": 0,
            "health_failed": 0,
            "health_skipped": total_waters,
            "errors": [],
        }

    health_updated = 0
    health_failed = 0
    errors = []

    for water_body in water_bodies:
        label = (water_body.name or "").strip() or f"Vatten {water_body.pk}"
        try:
            snapshot, error_message = update_waterbody_health_snapshot(water_body)
        except Exception as exc:
            logger.warning(
                "FVO onboarding health prefetch failed for water %r in org %r: %s",
                water_body.pk,
                org.pk,
                exc,
            )
            health_failed += 1
            errors.append(f"{label}: kunde inte spara hälsoprofil.")
            continue

        if error_message:
            health_failed += 1
            errors.append(f"{label}: {error_message}")
            continue

        if snapshot is None:
            health_failed += 1
            errors.append(f"{label}: hälsoprofil kunde inte skapas.")
            continue

        if (snapshot.fetch_error or "").strip():
            health_failed += 1
            errors.append(f"{label}: {snapshot.fetch_error}")
            continue

        health_updated += 1

    return {
        "health_updated": health_updated,
        "health_failed": health_failed,
        "health_skipped": 0,
        "errors": errors,
    }


def run_fvo_onboarding(org):
    """
    Kör FVO-onboarding för en organisation:

    1. Hitta FVO-gräns i Fiskekartan
    2. Spara MapBoundary
    3. Importera alla VISS-vatten inom gränsen
    4. Hämta och spara VISS-hälsa (best effort)
    """
    if org is None:
        return _onboarding_result(errors=["Ingen organisation angiven."])

    from maps.views import fetch_fvof_focus_for_org

    matched_fvof = fetch_fvof_focus_for_org(org.name)
    if not matched_fvof or not matched_fvof.get("found"):
        return _onboarding_result(
            errors=[
                f"Ingen officiell FVO-gräns hittades för {org.name} i Fiskekartan.",
            ]
        )

    boundary_result = save_fvo_boundary_for_org(org, matched_fvof)
    if not boundary_result.get("ok"):
        return _onboarding_result(errors=[boundary_result["error"]])

    import_result = import_viss_waters_for_org(org)
    waters_created = import_result.get("created", 0)
    waters_updated = import_result.get("updated", 0)
    waters_imported = waters_created + waters_updated
    errors = list(import_result.get("errors") or [])

    base = _onboarding_result(
        boundary_imported=True,
        boundary_name=boundary_result["name"],
        boundary_action=boundary_result["action"],
        waters_imported=waters_imported,
        waters_created=waters_created,
        waters_updated=waters_updated,
        waters_total=import_result.get("total", 0),
        waters_skipped=import_result.get("skipped", 0),
        lakes=import_result.get("lakes", 0),
        rivers=import_result.get("rivers", 0),
        errors=errors,
    )

    if import_result.get("total", 0) == 0 and waters_imported == 0:
        if not errors:
            errors.append("Inga vattenförekomster hittades inom FVO-gränsen i VISS.")
        base["errors"] = errors
        base["success"] = False
        return base

    if waters_imported == 0 and errors:
        base["success"] = False
        return base

    health_result = _prefetch_health_snapshots_for_org(org)
    base["health_updated"] = health_result["health_updated"]
    base["health_failed"] = health_result["health_failed"]
    base["health_skipped"] = health_result["health_skipped"]
    if health_result["errors"]:
        base["errors"].extend(health_result["errors"])

    base["success"] = True
    return base
