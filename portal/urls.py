from django.urls import path
from . import views
from documents import views as document_views

app_name = "portal"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),

    path("properties/", views.property_list, name="property_list"),
    path("properties/<int:pk>/", views.property_detail, name="property_detail"),

    path("documents/", views.document_overview, name="document_overview"),
    path("documents/activity/", views.activity_list, name="activity_list"),
    path("documents/workspace/", views.document_workspace, name="document_workspace"),
    path("documents/archive/", views.document_archive, name="document_archive"),
    path("documents/list/", views.document_list, name="document_list"),

    path("documents/upload/", views.document_upload, name="document_upload"),
    path("documents/create/blank/", views.create_blank_document, name="create_blank_document"),

    path("documents/trash/", views.document_trash, name="document_trash"),
    path("documents/<int:pk>/restore/", views.document_restore, name="document_restore"),

    path("documents/templates/", views.template_list, name="template_list"),
    path(
        "documents/create-from-template/<int:template_id>/",
        views.create_from_template,
        name="create_from_template"
    ),

    path("documents/<int:pk>/", views.document_detail, name="document_detail"),
    path("documents/<int:pk>/new-version/", views.document_upload_version, name="document_upload_version"),
    path("documents/<int:pk>/edit/", views.document_edit, name="document_edit"),
    path("documents/<int:pk>/delete/", views.document_delete, name="document_delete"),
    path("documents/<int:pk>/print/", views.document_print_view, name="document_print"),

    path("documents/<int:pk>/lock/", document_views.lock_document_for_review, name="lock_document"),
    path("document-approvals/<int:pk>/approve/", document_views.approve_document, name="approve_document"),
    path("document-approvals/<int:pk>/changes/", document_views.request_document_changes, name="request_document_changes"),
    path("document-approvals/<int:pk>/remove/", document_views.remove_document_reviewer, name="remove_document_reviewer"),
    path("document-signatures/<int:pk>/sign/", document_views.sign_document, name="sign_document"),

    path("verify/<str:document_hash>/", views.verify_document, name="verify_document"),
]
