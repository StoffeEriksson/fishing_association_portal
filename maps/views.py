from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from fisheries.models import ActionArea, ActionStatus

from .models import MapBoundary, WaterBody


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

    context = {
        "geojson_data": geojson_data,
        "has_org": bool(org),
        "org_name": org.name if org else "",
        "selected_action_id": selected_action_id,
        "selected_water_id": selected_water_id,
    }
    return render(request, "maps/map_page.html", context)