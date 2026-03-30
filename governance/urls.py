from django.urls import path
from . import views

app_name = "governance"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    
    path("members/", views.board_member_list, name="board_member_list"),
    path("members/create/", views.board_member_create, name="board_member_create"),
    path("members/<int:pk>/edit/", views.board_member_update, name="board_member_update"),
    path("members/<int:pk>/deactivate/", views.board_member_deactivate, name="board_member_deactivate"),
    
    path("activity-log/", views.activity_log_list, name="activity_log_list"),
    
    path("matters/", views.matter_list, name="matter_list"),
    path("matters/create/", views.matter_create, name="matter_create"),
    path("matters/<int:pk>/", views.matter_detail, name="matter_detail"),
    path("matters/<int:pk>/edit/", views.matter_update, name="matter_update"),
    path("matters/<int:pk>/status/<str:new_status>/", views.matter_change_status, name="matter_change_status"),

    path("meetings/create/", views.meeting_create, name="meeting_create"),
    path("meetings/<int:pk>/", views.meeting_detail, name="meeting_detail"),
    path(
    "meetings/<int:pk>/documents/<str:doc_type>/create/",
    views.create_document_from_meeting,
    name="create_document_from_meeting",
    ),
    path("meetings/<int:pk>/close/", views.close_meeting, name="close_meeting"),
    path("protocols/review/", views.protocol_review_list, name="protocol_review_list"),
]
