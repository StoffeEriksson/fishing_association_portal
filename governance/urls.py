from django.urls import path
from . import views

app_name = "governance"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("members/", views.board_member_list, name="board_member_list"),
    path("members/create/", views.board_member_create, name="board_member_create"),
    path("activity-log/", views.activity_log_list, name="activity_log_list"),
    
]
