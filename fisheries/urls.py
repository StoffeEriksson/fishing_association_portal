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
    path(
        "observations/<int:pk>/create-action/",
        views.create_action_from_observation,
        name="create_action_from_observation",
    ),
    path("<int:pk>/", views.action_detail, name="action_detail"),
]
