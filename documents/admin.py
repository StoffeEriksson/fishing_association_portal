from django.contrib import admin
from core.admin import OrgAdminMixin
from .models import (
    Document,
    DocumentFolder,
    DocumentVersion,
    DocumentTemplate,
    DocumentApproval,
    DocumentSignature,
)


@admin.register(DocumentFolder)
class DocumentFolderAdmin(OrgAdminMixin, admin.ModelAdmin):
    list_display = (
        "name",
        "org",
        "parent",
        "folder_type",
        "is_system_folder",
        "year",
        "month",
        "created_at",
    )
    list_filter = ("org", "folder_type", "is_system_folder", "year", "month")
    search_fields = ("name", "system_key")
    ordering = ("name",)


@admin.register(DocumentTemplate)
class DocumentTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "created_at")
    search_fields = ("name",)
    list_filter = ("category",)
    ordering = ("name",)


class DocumentVersionInline(admin.TabularInline):
    model = DocumentVersion
    extra = 0
    readonly_fields = ("version_number", "uploaded_by", "uploaded_at")
    ordering = ("-version_number",)


class DocumentApprovalInline(admin.TabularInline):
    model = DocumentApproval
    extra = 0
    readonly_fields = ("created_at", "responded_at")
    ordering = ("created_at",)


class DocumentSignatureInline(admin.TabularInline):
    model = DocumentSignature
    extra = 0
    readonly_fields = ("created_at", "signed_at")
    ordering = ("created_at",)


@admin.register(Document)
class DocumentAdmin(OrgAdminMixin, admin.ModelAdmin):
    list_display = (
        "title",
        "category",
        "workflow_status",
        "org",
        "folder",
        "folder_auto_assigned",
        "uploaded_by",
        "updated_at",
    )
    list_filter = ("category", "workflow_status", "updated_at")
    search_fields = ("title", "description")
    ordering = ("-updated_at",)
    inlines = [DocumentVersionInline, DocumentApprovalInline, DocumentSignatureInline]


@admin.register(DocumentVersion)
class DocumentVersionAdmin(admin.ModelAdmin):
    list_display = ("document", "version_number", "uploaded_by", "uploaded_at")
    ordering = ("-uploaded_at",)


@admin.register(DocumentApproval)
class DocumentApprovalAdmin(admin.ModelAdmin):
    list_display = ("document", "reviewer", "status", "responded_at", "created_at")
    list_filter = ("status", "created_at", "responded_at")
    search_fields = ("document__title", "reviewer__email", "reviewer__username")
    ordering = ("-created_at",)


@admin.register(DocumentSignature)
class DocumentSignatureAdmin(admin.ModelAdmin):
    list_display = ("document", "user", "role", "status", "signed_at", "created_at")
    list_filter = ("role", "status", "created_at", "signed_at")
    search_fields = ("document__title", "user__email", "user__username")
    ordering = ("-created_at",)
