from django.urls import path
from . import views

app_name = "portal"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("properties/", views.property_list, name="property_list"),
    path("properties/<int:pk>/", views.property_detail, name="property_detail"),
    path("documents/", views.document_list, name="document_list"),
    path("documents/upload/", views.document_upload, name="document_upload"),
    path("documents/<int:pk>/", views.document_detail, name="document_detail"),
]
