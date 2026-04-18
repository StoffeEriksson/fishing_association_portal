from django.contrib import admin

from .models import CalendarEvent


@admin.register(CalendarEvent)
class CalendarEventAdmin(admin.ModelAdmin):
    list_display = ("title", "event_type", "start_at", "end_at", "is_all_day", "org")
    list_filter = ("event_type", "is_all_day", "org")
    search_fields = ("title", "description", "location")
