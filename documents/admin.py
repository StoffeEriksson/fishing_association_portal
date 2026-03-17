from django.contrib import admin
from core.admin import OrgAdminMixin
from .models import Document


@admin.register(Document)
class DocumentAdmin(OrgAdminMixin, admin.ModelAdmin):
    list_display = ("title", "category", "org", "uploaded_by", "uploaded_at")
    list_filter = ("category", "uploaded_at")
    search_fields = ("title", "description")
    ordering = ("-uploaded_at",)
