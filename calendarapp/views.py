import calendar
import json
from urllib.parse import urlencode
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .forms import CalendarEventForm
from .models import CalendarEvent, CalendarEventType


@login_required
def calendar_list(request):
    today = date.today()
    year = request.GET.get("year")
    month = request.GET.get("month")

    try:
        selected_year = int(year) if year else today.year
        selected_month = int(month) if month else today.month
        month_start = date(selected_year, selected_month, 1)
    except (TypeError, ValueError):
        selected_year = today.year
        selected_month = today.month
        month_start = date(selected_year, selected_month, 1)

    month_calendar = calendar.Calendar(firstweekday=0)
    month_dates = month_calendar.monthdatescalendar(selected_year, selected_month)

    range_start = month_dates[0][0]
    range_end = month_dates[-1][-1]

    events_qs = CalendarEvent.objects.none()
    if request.org is not None:
        events_qs = (
            CalendarEvent.objects.filter(
                org=request.org,
                start_at__date__gte=range_start,
                start_at__date__lte=range_end,
            )
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
            week_days.append(
                {
                    "date": day_date,
                    "is_current_month": day_date.month == selected_month,
                    "is_today": day_date == today,
                    "visible_events": day_events[:2],
                    "extra_count": max(0, len(day_events) - 2),
                }
            )
        weeks.append(week_days)

    previous_month = (month_start - timedelta(days=1)).replace(day=1)
    next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
    highlight_date = None
    highlight_date_raw = (request.GET.get("highlight_date") or "").strip()
    try:
        highlight_date = date.fromisoformat(highlight_date_raw)
    except ValueError:
        highlight_date = None

    return render(
        request,
        "calendarapp/calendar_list.html",
        {
            "weeks": weeks,
            "today": today,
            "events_by_day": events_by_day,
            "month_start": month_start,
            "previous_month": previous_month,
            "next_month": next_month,
            "highlight_date": highlight_date,
        },
    )


@login_required
def calendar_create(request):
    if request.org is None:
        messages.error(request, "Ingen aktiv organisation vald.")
        return redirect("calendarapp:list")

    if request.method == "POST":
        form = CalendarEventForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                event = form.save(commit=False)
                event.org = request.org
                event.created_by = request.user
                event.save()
            messages.success(request, "Händelsen skapades.")
            return redirect(
                f"{reverse('calendarapp:list')}?highlight_date={event.start_at.date().isoformat()}"
            )
    else:
        initial = {}
        selected_date = (request.GET.get("date") or "").strip()
        try:
            parsed_date = date.fromisoformat(selected_date)
            initial["start_at"] = f"{parsed_date.isoformat()}T09:00"
        except ValueError:
            pass

        form = CalendarEventForm(initial=initial)

    return render(
        request,
        "calendarapp/calendar_form.html",
        {
            "form": form,
            "page_title": "Skapa händelse",
            "page_subtitle": "Lägg till en kalenderhändelse för aktiv organisation.",
            "submit_label": "Spara",
        },
    )


@login_required
def book_meeting(request):
    if request.org is None:
        messages.error(request, "Ingen aktiv organisation vald.")
        return redirect("calendarapp:list")

    params = {"from_calendar": "1"}
    selected_date = (request.GET.get("date") or "").strip()
    if selected_date:
        params["date"] = selected_date

    target_url = f"{reverse('governance:meeting_create')}?{urlencode(params)}"
    return redirect(target_url)


@login_required
def calendar_detail(request, pk):
    event = get_object_or_404(
        CalendarEvent.objects.filter(org=request.org),
        pk=pk,
    )

    return render(
        request,
        "calendarapp/calendar_detail.html",
        {
            "event": event,
        },
    )


@login_required
def calendar_edit(request, pk):
    if request.org is None:
        messages.error(request, "Ingen aktiv organisation vald.")
        return redirect("calendarapp:list")

    event = get_object_or_404(
        CalendarEvent.objects.filter(org=request.org),
        pk=pk,
    )

    if request.method == "POST":
        form = CalendarEventForm(request.POST, instance=event)
        if form.is_valid():
            with transaction.atomic():
                updated_event = form.save(commit=False)
                updated_event.save()
            messages.success(request, "Händelsen uppdaterades.")
            return redirect("calendarapp:detail", pk=event.pk)
    else:
        form = CalendarEventForm(instance=event)

    return render(
        request,
        "calendarapp/calendar_form.html",
        {
            "form": form,
            "event": event,
            "page_title": "Redigera händelse",
            "page_subtitle": "Uppdatera kalenderhändelsen.",
            "submit_label": "Spara ändringar",
        },
    )


@login_required
def calendar_delete(request, pk):
    event = get_object_or_404(
        CalendarEvent.objects.filter(org=request.org),
        pk=pk,
    )

    if request.method == "POST":
        event.delete()
        messages.success(request, "Händelsen togs bort.")
        return redirect("calendarapp:list")

    return render(
        request,
        "calendarapp/calendar_confirm_delete.html",
        {
            "event": event,
        },
    )


@login_required
def calendar_move_event(request, pk):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Method not allowed"}, status=405)

    event = get_object_or_404(
        CalendarEvent.objects.filter(org=request.org),
        pk=pk,
    )

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "error": "Invalid payload"}, status=400)

    target_date_raw = (payload.get("target_date") or "").strip()
    try:
        target_date = date.fromisoformat(target_date_raw)
    except ValueError:
        return JsonResponse({"ok": False, "error": "Invalid target_date"}, status=400)

    delta_days = (target_date - event.start_at.date()).days
    if delta_days != 0:
        event.start_at = event.start_at + timedelta(days=delta_days)
        if event.end_at is not None:
            event.end_at = event.end_at + timedelta(days=delta_days)
        event.save(update_fields=["start_at", "end_at", "updated_at"])

    return JsonResponse({"ok": True})
