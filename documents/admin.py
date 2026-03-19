from django.contrib import admin
from core.admin import OrgAdminMixin
from .models import Document, DocumentVersion


class DocumentVersionInline(admin.TabularInline):
    model = DocumentVersion
    extra = 0
    readonly_fields = ("version_number", "uploaded_by", "uploaded_at")
    ordering = ("-version_number",)


@admin.register(Document)
class DocumentAdmin(OrgAdminMixin, admin.ModelAdmin):
    list_display = ("title", "category", "org", "uploaded_by", "updated_at")
    list_filter = ("category", "updated_at")
    search_fields = ("title", "description")
    ordering = ("-updated_at",)
    inlines = [DocumentVersionInline]


@admin.register(DocumentVersion)
class DocumentVersionAdmin(admin.ModelAdmin):
    list_display = ("document", "version_number", "uploaded_by", "uploaded_at")
    ordering = ("-uploaded_at",)
