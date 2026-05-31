from django.urls import path

from . import views

app_name = "maps"

urlpatterns = [
    path("", views.map_page, name="map_page"),
    path(
        "import-fvo-boundary/",
        views.import_fvo_boundary,
        name="import_fvo_boundary",
    ),
    path(
        "waterbodies/<int:waterbody_id>/import-viss/",
        views.import_waterbody_from_viss,
        name="import_waterbody_from_viss",
    ),
]

