from django.urls import path
from . import views

app_name = "documents"

urlpatterns = [
    path("", views.document_folder_list, name="folder_list"),
    path("category/<slug:category>/", views.document_category_list, name="category_list"),
]
