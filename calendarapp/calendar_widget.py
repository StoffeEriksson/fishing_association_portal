import calendar
from datetime import date

from django.utils import timezone

from .models import CalendarEvent


def _event_dot_categories_for_day(events):
    """Return up to two dot categories for a day: 'annual', 'meeting', 'other' (priority order)."""
    has_annual = False
    has_meeting = False
    has_other = False
    for event in events:
        et = event.event_type
        if et == "annual_meeting":
            has_annual = True
        elif et == "meeting":
            has_meeting = True
        else:
            has_other = True
    categories = []
    if has_annual:
        categories.append("annual")
    if has_meeting:
        categories.append("meeting")
    if has_other:
        categories.append("other")
    return categories[:2]


def _dot_class(category):
    if category == "annual":
        return "dot-annual"
    if category == "meeting":
        return "dot-meeting"
    return "dot-other"


def _agenda_dot_class(event_type):
    if event_type == "annual_meeting":
        return "dot-annual"
    if event_type == "meeting":
        return "dot-meeting"
    return "dot-other"


def build_dashboard_calendar_widget(org, ref_date=None):
    """
    Compact month grid + per-day dot hints for dashboard preview.
    Mirrors calendar_list date range and org filter; no full calendar logic.
    """
    if org is None:
        return None

    today = date.today()
    ref = ref_date or today
    selected_year = ref.year
    selected_month = ref.month
    month_start = date(selected_year, selected_month, 1)

    month_calendar = calendar.Calendar(firstweekday=0)
    month_dates = month_calendar.monthdatescalendar(selected_year, selected_month)
    range_start = month_dates[0][0]
    range_end = month_dates[-1][-1]

    events_qs = (
        CalendarEvent.objects.filter(
            org=org,
            start_at__date__gte=range_start,
            start_at__date__lte=range_end,
        )
        .only("start_at", "event_type")
        .order_by("start_at", "title")
    )

    events_by_day = {}
    for event in events_qs:
        event_date = event.start_at.date()
        events_by_day.setdefault(event_date, []).append(event)

    weeks = []
    for week in month_dates:
        week_days = []
        for day_date in week:
            day_events = events_by_day.get(day_date, [])
            dot_categories = _event_dot_categories_for_day(day_events)
            dots = [{"class": _dot_class(c)} for c in dot_categories]
            week_days.append(
                {
                    "date": day_date,
                    "is_current_month": day_date.month == selected_month,
                    "is_today": day_date == today,
                    "dots": dots,
                }
            )
        weeks.append(week_days)

    now = timezone.now()
    upcoming = []
    for event in (
        CalendarEvent.objects.filter(org=org, start_at__gte=now)
        .only("start_at", "title", "event_type")
        .order_by("start_at", "title")[:3]
    ):
        upcoming.append(
            {
                "start_at": event.start_at,
                "title": event.title,
                "dot_class": _agenda_dot_class(event.event_type),
            }
        )

    return {
        "weeks": weeks,
        "month_start": month_start,
        "upcoming": upcoming,
    }
