from django.urls import path

from . import views

app_name = "fisheries"

urlpatterns = [
    path("", views.action_list, name="action_list"),
    path("actions/board/", views.action_board, name="action_board"),
    path("actions/create/", views.action_create, name="action_create"),
    path("overview/", views.overview, name="overview"),
    path("observations/", views.observation_list, name="observation_list"),
    path("observations/create/", views.observation_create, name="observation_create"),
    path("observations/<int:pk>/", views.observation_detail, name="observation_detail"),
    path("observations/<int:pk>/trash/", views.trash_observation, name="trash_observation"),
    path("trash/", views.fisheries_trash, name="trash"),
    path(
        "trash/observations/<int:pk>/restore/",
        views.restore_observation_view,
        name="restore_observation",
    ),
    path(
        "trash/observations/<int:pk>/purge/",
        views.purge_observation_view,
        name="purge_observation",
    ),
    path("trash/actions/<int:pk>/restore/", views.restore_action_view, name="restore_action"),
    path("trash/actions/<int:pk>/purge/", views.purge_action_view, name="purge_action"),
    path(
        "observations/<int:pk>/create-action/",
        views.create_action_from_observation,
        name="create_action_from_observation",
    ),
    path("<int:pk>/trash/", views.trash_action, name="trash_action"),
    path("<int:pk>/", views.action_detail, name="action_detail"),
]
