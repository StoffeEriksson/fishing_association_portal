import os
import re
from datetime import date, timedelta
from html import unescape
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Sum, Count
from django.db import IntegrityError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST
from django.utils import timezone
from django.utils.html import strip_tags
from django.http import Http404, HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.urls import reverse
from collections import OrderedDict
from django.utils.translation import gettext_lazy as _
import qrcode
from io import BytesIO
import base64

from accounts.forms import UserAccountForm, UserProfileForm
from accounts.models import UserProfile
from calendarapp.calendar_widget import build_dashboard_calendar_widget
from calendarapp.models import CalendarEvent
from core.models import Membership
from fisheries.models import ActionArea, ActionPriority, ActionStatus, Observation, ObservationStatus
from fishingrights.models import FishingRightShare, Property, RightHolder
from governance.models import BoardMembership, BoardMatter, Meeting
from documents.forms import (
    DocumentCreateForm,
    DocumentUpdateForm,
    DocumentVersionForm,
    TemplateDocumentCreateForm,
    NoticeTemplateForm,
    DecisionTemplateForm,
    MotionTemplateForm,
    MeetingProtocolForm,
)
from documents.models import (
    Document,
    DocumentApproval,
    DocumentApprovalStatus,
    DocumentActivity,
    DocumentFolder,
    DocumentFolderType,
    DocumentSignature,
    DocumentSignatureStatus,
    DocumentSourceType,
    DocumentTemplate,
    DocumentVersion,
    DocumentWorkflowStatus,
)
from documents.utils import log_document_activity


def text_to_paragraphs(text):
    if not text:
        return ""

    paragraphs = [
        f"<p>{p.strip()}</p>"
        for p in text.split("\n")
        if p.strip()
    ]

    return "".join(paragraphs)


def render_protocol(template_content, cleaned_data):
    attendees_raw = cleaned_data.get("attendees", "").strip()

    if attendees_raw:
        attendees_list = [
            line.strip() for line in attendees_raw.splitlines() if line.strip()
        ]
        attendees_html = "<ul>" + "".join(f"<li>{name}</li>" for name in attendees_list) + "</ul>"
    else:
        attendees_html = "<ul><li></li></ul>"

    replacements = {
        "{{ date }}": cleaned_data.get("date").strftime("%Y-%m-%d") if cleaned_data.get("date") else "",
        "{{ time }}": cleaned_data.get("time").strftime("%H:%M") if cleaned_data.get("time") else "",
        "{{ location }}": cleaned_data.get("location", ""),
        "{{ attendees_html }}": attendees_html,
    }

    content = template_content
    for placeholder, value in replacements.items():
        content = content.replace(placeholder, value)

    return content


def render_notice(template_content, cleaned_data):
    agenda_raw = cleaned_data.get("agenda", "").strip()

    if agenda_raw:
        agenda_list = [
            line.strip() for line in agenda_raw.splitlines() if line.strip()
        ]
        agenda_html = "<ol>" + "".join(f"<li>{item}</li>" for item in agenda_list) + "</ol>"
    else:
        agenda_html = "<ol><li></li></ol>"

    replacements = {
        "{{ date }}": cleaned_data.get("date").strftime("%Y-%m-%d") if cleaned_data.get("date") else "",
        "{{ time }}": cleaned_data.get("time").strftime("%H:%M") if cleaned_data.get("time") else "",
        "{{ location }}": cleaned_data.get("location", ""),
        "{{ agenda_html }}": agenda_html,
    }

    content = template_content
    for placeholder, value in replacements.items():
        content = content.replace(placeholder, value)

    return content


def render_decision(template_content, cleaned_data):
    replacements = {
        "{{ subject }}": text_to_paragraphs(cleaned_data.get("subject", "")),
        "{{ background }}": text_to_paragraphs(cleaned_data.get("background", "")),
        "{{ decision }}": text_to_paragraphs(cleaned_data.get("decision", "")),
    }

    content = template_content
    for placeholder, value in replacements.items():
        content = content.replace(placeholder, value)

    return content


def render_motion(template_content, cleaned_data):
    replacements = {
        "{{ proposal }}": text_to_paragraphs(cleaned_data.get("proposal", "")),
        "{{ motivation }}": text_to_paragraphs(cleaned_data.get("motivation", "")),
    }

    content = template_content
    for placeholder, value in replacements.items():
        content = content.replace(placeholder, value)

    return content


def render_meeting_protocol(template_content, cleaned_data):
    def list_to_html(text):
        if not text:
            return "<ul><li></li></ul>"

        items = [line.strip() for line in text.splitlines() if line.strip()]
        return "<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>"

    replacements = {
        "{{ date }}": cleaned_data.get("date").strftime("%Y-%m-%d") if cleaned_data.get("date") else "",
        "{{ time }}": cleaned_data.get("time").strftime("%H:%M") if cleaned_data.get("time") else "",
        "{{ location }}": cleaned_data.get("location", ""),

        "{{ chairman }}": cleaned_data.get("chairman", ""),
        "{{ secretary }}": cleaned_data.get("secretary", ""),

        "{{ attendees_html }}": list_to_html(cleaned_data.get("attendees", "")),
        "{{ adjusters_html }}": list_to_html(cleaned_data.get("adjusters", "")),
    }

    content = template_content
    for k, v in replacements.items():
        content = content.replace(k, v)

    return content


def generate_document_content(template, cleaned_data):
    if template.category == "protocol":
        return render_protocol(template.content, cleaned_data)
    elif template.category == "notice":
        return render_notice(template.content, cleaned_data)
    elif template.category == "decision":
        return render_decision(template.content, cleaned_data)
    elif template.category == "motion":
        return render_motion(template.content, cleaned_data)
    elif template.category == "meeting":
        return render_meeting_protocol(template.content, cleaned_data)

    return template.content


@login_required
def dashboard(request):
    org = request.org

    if org is None:
        messages.warning(request, "You need to join or create an organization.")
        return redirect("account_login")

    recent_documents = Document.objects.filter(
        org=org,
        is_deleted=False,
    ).order_by("-updated_at")[:3]

    recent_activities = DocumentActivity.objects.filter(
        document__org=org
    ).select_related("document", "user").order_by("-created_at")[:5]

    pending_approvals = (
        DocumentApproval.objects.filter(
            document__org=org,
            document__is_deleted=False,
            reviewer=request.user,
            status=DocumentApprovalStatus.PENDING,
        )
        .select_related("document")
        .order_by("-created_at")
    )

    pending_signatures = (
        DocumentSignature.objects.filter(
            document__org=org,
            document__is_deleted=False,
            user=request.user,
            status=DocumentSignatureStatus.PENDING,
        )
        .select_related("document")
        .order_by("-created_at")
    )

    important_actions = []

    for approval in pending_approvals:
        important_actions.append(
            {
                "label": "Väntar på din justering",
                "title": approval.document.title,
                "url": reverse("portal:document_detail", args=[approval.document.pk]),
                "source": "documents",
                "due_at": None,
                "priority": "normal",
                "created_at": approval.created_at,
                "kind": "document",
            }
        )

    for signature in pending_signatures:
        important_actions.append(
            {
                "label": "Väntar på din signering",
                "title": signature.document.title,
                "url": reverse("portal:document_detail", args=[signature.document.pk]),
                "source": "documents",
                "due_at": None,
                "priority": "normal",
                "created_at": signature.created_at,
                "kind": "document",
            }
        )

    attention_observations = (
        Observation.objects.for_org(org)
        .not_trashed()
        .filter(status__in=[ObservationStatus.NEW, ObservationStatus.UNDER_REVIEW])
        .select_related("water_body")
    )
    for observation in attention_observations:
        is_new = observation.status == ObservationStatus.NEW
        important_actions.append(
            {
                "label": "Observation",
                "title": observation.title,
                "url": reverse("fisheries:observation_detail", args=[observation.pk]),
                "source": "fisheries",
                "source_detail": "Observation",
                "due_at": None,
                "priority": "high" if is_new else "normal",
                "created_at": observation.created_at,
                "kind": "observation",
                "observation_status": observation.status,
                "summary": (
                    "Ny observation behöver granskas"
                    if is_new
                    else "Observation under granskning"
                ),
                "water_name": observation.water_body.name if observation.water_body else None,
            }
        )

    today = timezone.localdate()
    fisheries_relevant = (
        Q(deadline__isnull=False)
        | Q(priority__in=[ActionPriority.HIGH, ActionPriority.CRITICAL])
        | Q(status__in=[ActionStatus.URGENT, ActionStatus.NEEDS_ACTION])
        | Q(responsible_user__isnull=True)
    )
    fisheries_actions = (
        ActionArea.objects.for_org(org).not_trashed()
        .filter(fisheries_relevant)
        .exclude(status=ActionStatus.COMPLETED)
        .order_by("created_at")
    )

    for action in fisheries_actions:
        dl = action.deadline
        if dl and dl < today:
            label = "Förfallen fiskevårdsåtgärd"
        elif dl and dl <= today + timedelta(days=14):
            label = "Fiskevårdsåtgärd med deadline"
        elif action.responsible_user_id is None:
            label = "Fiskevårdsåtgärd saknar ansvarig"
        else:
            label = "Viktig fiskevårdsåtgärd"

        important_actions.append(
            {
                "label": label,
                "title": action.name,
                "url": reverse("fisheries:action_detail", args=[action.pk]),
                "source": "fisheries",
                "due_at": dl,
                "priority": action.priority,
                "created_at": action.created_at,
                "kind": "fisheries_action",
            }
        )

    priority_rank = {
        "critical": 0,
        "high": 1,
        "medium": 2,
        "low": 3,
        "normal": 4,
    }

    def important_actions_sort_key(item):
        created = item["created_at"]
        created_ts = created.timestamp() if hasattr(created, "timestamp") else 0

        if item.get("kind") == "observation":
            status_rank = (
                0 if item.get("observation_status") == ObservationStatus.NEW else 1
            )
            return (0, status_rank, -created_ts)

        due = item.get("due_at")
        pr = item.get("priority") or "normal"
        pr_i = priority_rank.get(pr, 4)

        if due:
            due_ord = due.toordinal()
            if due < today:
                return (1, 0, due_ord, pr_i, created_ts)
            return (1, 1, due_ord, pr_i, created_ts)
        return (2, 0, pr_i, created_ts)

    important_actions = sorted(important_actions, key=important_actions_sort_key)[:6]

    document_count = Document.objects.filter(
        org=org,
        is_deleted=False,
    ).count()

    now = timezone.now()
    upcoming_events = (
        CalendarEvent.objects.filter(
            org=org,
            start_at__gte=now,
            start_at__lte=now + timedelta(days=14),
        )
        .order_by("start_at", "title")[:5]
    )

    upcoming_meetings_count = CalendarEvent.objects.filter(
        org=org,
        start_at__gte=now,
        start_at__lte=now + timedelta(days=30),
        event_type="meeting",
    ).count()

    next_meeting = (
        Meeting.objects.filter(org=org, meeting_date__gte=now)
        .order_by("meeting_date")
        .first()
    )
    open_matters_count = BoardMatter.objects.filter(org=org).exclude(
        status__in=["closed", "decided"]
    ).count()
    next_meeting_open_matters_count = 0
    if next_meeting:
        next_meeting_open_matters_count = BoardMatter.objects.filter(
            org=org,
            meeting=next_meeting,
        ).exclude(status__in=["closed", "decided"]).count()

    pending_protocol_count = pending_approvals.count() + pending_signatures.count()
    overdue_actions_count = sum(
        1
        for item in important_actions
        if item.get("due_at") and item["due_at"] < today
    )
    week_end = today + timedelta(days=7)
    weekly_deadlines = [
        item
        for item in important_actions
        if item.get("due_at") and item["due_at"] <= week_end
    ][:5]
    this_week_events = [
        event
        for event in upcoming_events
        if timezone.localtime(event.start_at).date() <= week_end
    ][:5]

    news_feed = (
        DocumentActivity.objects.filter(
            document__org=org,
            document__is_deleted=False,
        )
        .select_related("document", "user")
        .order_by("-created_at")[:5]
    )

    calendar_widget = build_dashboard_calendar_widget(org)

    return render(
        request,
        "portal/dashboard.html",
        {
            "recent_documents": recent_documents,
            "recent_activities": recent_activities,
            "important_actions": important_actions,
            "document_count": document_count,
            "upcoming_events": upcoming_events,
            "this_week_events": this_week_events,
            "weekly_deadlines": weekly_deadlines,
            "upcoming_meetings_count": upcoming_meetings_count,
            "next_meeting": next_meeting,
            "open_matters_count": open_matters_count,
            "next_meeting_open_matters_count": next_meeting_open_matters_count,
            "pending_protocol_count": pending_protocol_count,
            "overdue_actions_count": overdue_actions_count,
            "news_feed": news_feed,
            "calendar_widget": calendar_widget,
        },
    )


def _account_user_initials(user):
    parts = []
    if user.first_name:
        parts.append(user.first_name[0])
    if user.last_name:
        parts.append(user.last_name[0])
    if parts:
        return "".join(parts).upper()[:2]
    label = (user.email or user.username or "?").strip()
    return label[0].upper() if label else "?"


def _profile_has_avatar(profile):
    return bool(profile and profile.avatar and profile.avatar.name)


def _account_user_display_name(user):
    first_name = (user.first_name or "").strip()
    last_name = (user.last_name or "").strip()

    if first_name and last_name:
        return f"{first_name} {last_name}"
    if first_name:
        return first_name
    if last_name:
        return last_name
    if user.email:
        return user.email
    return user.get_username()


def portal_account_topbar(request):
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}
    profile = UserProfile.objects.filter(user_id=request.user.pk).only("avatar").first()
    return {
        "portal_account_profile": profile,
        "portal_account_has_avatar": _profile_has_avatar(profile),
        "portal_account_initials": _account_user_initials(request.user),
        "portal_account_display_name": _account_user_display_name(request.user),
    }


@login_required
def my_account(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)

    if request.method == "POST":
        user_form = UserAccountForm(request.POST, instance=request.user)
        profile_form = UserProfileForm(request.POST, request.FILES, instance=profile)
        if user_form.is_valid() and profile_form.is_valid():
            user_form.save()
            profile_form.save()
            messages.success(request, "Konto uppdaterat")
            return redirect("portal:my_account")
        messages.error(
            request,
            "Kunde inte spara alla uppgifter. Kontrollera formuläret.",
        )
    else:
        user_form = UserAccountForm(instance=request.user)
        profile_form = UserProfileForm(instance=profile)

    active_org = request.org
    portal_role_label = "Ingen portalroll"
    board_role_label = "Ingen styrelseroll"
    portal_membership = None
    board_membership = None

    if active_org:
        portal_membership = Membership.objects.filter(
            user=request.user,
            organization=active_org,
            is_active=True,
        ).first()
        if portal_membership:
            portal_role_label = portal_membership.get_role_display()

        board_membership = BoardMembership.objects.filter(
            org=active_org,
            user=request.user,
            is_active=True,
        ).first()
        if board_membership:
            board_role_label = board_membership.get_role_display()

    profile = (
        UserProfile.objects.filter(user_id=request.user.pk).first() or profile
    )
    profile.refresh_from_db()

    return render(
        request,
        "portal/my_account.html",
        {
            "user_form": user_form,
            "profile_form": profile_form,
            "profile": profile,
            "profile_has_avatar": _profile_has_avatar(profile),
            "account_initials": _account_user_initials(request.user),
            "account_display_name": _account_user_display_name(request.user),
            "active_org": active_org,
            "portal_role_label": portal_role_label,
            "board_role_label": board_role_label,
            "portal_membership": portal_membership,
            "board_membership": board_membership,
        },
    )


def _safe_reverse(url_name, *args, fallback=None):
    try:
        return reverse(url_name, args=args)
    except Exception:
        if fallback:
            try:
                return reverse(fallback)
            except Exception:
                return "/"
        return "/"


_SEARCH_CANDIDATE_LIMIT = 15
_SEARCH_DISPLAY_LIMIT = 3
_SEARCH_RANK_EXACT = 40
_SEARCH_RANK_STARTS = 30
_SEARCH_RANK_CONTAINS = 20


def _search_field_rank(query, value):
    text = (value or "").strip()
    if not text:
        return 0
    text_lower = text.lower()
    query_lower = query.lower()
    if text_lower == query_lower:
        return _SEARCH_RANK_EXACT
    if text_lower.startswith(query_lower):
        return _SEARCH_RANK_STARTS
    if query_lower in text_lower:
        return _SEARCH_RANK_CONTAINS
    return 0


def _search_pick_best_match(query, field_specs):
    best_rank = 0
    best_match = None
    best_field = None
    for spec in field_specs:
        value = spec.get("value") or ""
        if spec.get("strip_html"):
            value = _search_plain_text(value)
        rank = _search_field_rank(query, value)
        if rank == 0:
            continue
        labels = spec["labels"]
        if rank == _SEARCH_RANK_EXACT:
            match_label = labels["exact"]
        elif rank == _SEARCH_RANK_STARTS:
            match_label = labels.get("starts", labels["contains"])
        else:
            match_label = labels["contains"]
        if rank > best_rank:
            best_rank = rank
            best_match = match_label
            best_field = spec.get("field")
    return best_rank, best_match, best_field


def _search_plain_text(value):
    text = unescape(strip_tags(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def _search_snippet_source_text(content):
    """Plain text for snippets only; strips template filler lines/underscores."""
    text = unescape(strip_tags(content or ""))
    text = re.sub(r"_{3,}", " ", text)
    text = re.sub(r"-{3,}", " ", text)
    text = re.sub(r"[–—─]{3,}", " ", text)
    text = re.sub(r"[=·•]{3,}", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _search_snippet_trim_edges(text):
    return text.strip(" _-–—─.=·•\t\n\r")


def _search_snippet_word_start(text, pos):
    if pos <= 0:
        return 0
    if text[pos - 1] == " ":
        return pos
    space = text.rfind(" ", 0, pos)
    return space + 1 if space >= 0 else 0


def _search_snippet_word_end(text, pos):
    if pos >= len(text):
        return len(text)
    if pos < len(text) and text[pos] == " ":
        return pos
    space = text.find(" ", pos)
    return space if space >= 0 else len(text)


def _search_content_snippet(
    query,
    content,
    before_chars=90,
    after_chars=120,
    max_len=200,
    match_lead_chars=42,
):
    """Plain-text snippet centered on the first case-insensitive query match."""
    text = _search_snippet_source_text(content)
    if not text:
        return None
    text_lower = text.lower()
    query_lower = query.lower()
    idx = text_lower.find(query_lower)
    if idx < 0:
        return None

    match_end = idx + len(query)
    raw_start = max(0, idx - before_chars)
    raw_end = min(len(text), match_end + after_chars)

    start = min(_search_snippet_word_start(text, raw_start), idx)
    end = max(_search_snippet_word_end(text, raw_end), match_end)

    if end <= start:
        start = raw_start
        end = min(len(text), match_end + after_chars)

    if end - start > max_len:
        before_take = min(before_chars, idx - start, max(0, max_len - len(query) - 20))
        after_take = min(after_chars, len(text) - match_end, max_len - before_take - len(query))
        start = max(0, idx - before_take)
        end = min(len(text), match_end + after_take)
        start = min(_search_snippet_word_start(text, start), idx)
        end = max(end, match_end)
        if end - start > max_len:
            start = max(0, end - max_len)
            if idx < start:
                start = max(0, idx - 20)
            end = min(len(text), max(start + max_len, match_end))

    snippet = _search_snippet_trim_edges(text[start:end])
    if query_lower not in snippet.lower():
        start = max(0, idx - 40)
        end = min(len(text), match_end + 80)
        snippet = _search_snippet_trim_edges(text[start:end])

    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""
    inner = snippet
    match_pos = inner.lower().find(query_lower)
    if match_pos > match_lead_chars:
        trim_at = match_pos - match_lead_chars
        inner = inner[trim_at:].lstrip()
        prefix = "..."
    snippet = f"{prefix}{inner}{suffix}"
    return snippet


def _search_top_rows(query, rows, field_specs_builder, tie_breaker=None, limit=_SEARCH_DISPLAY_LIMIT):
    scored = []
    for row in rows:
        rank, match, field = _search_pick_best_match(query, field_specs_builder(row))
        if rank == 0:
            continue
        scored.append((rank, tie_breaker(row) if tie_breaker else 0, row, match, field))

    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return scored[:limit]


def _search_candidate_limit(limit_per_group):
    return min(max(limit_per_group * 2, _SEARCH_CANDIDATE_LIMIT), 50)


_SEARCH_RESULTS_PAGE_LIMIT = 25


def _build_global_search_groups(org, q, limit_per_group=_SEARCH_DISPLAY_LIMIT):
    groups = OrderedDict()
    total = 0
    candidate_limit = _search_candidate_limit(limit_per_group)

    def add_item(group_label, item):
        nonlocal total
        groups.setdefault(group_label, []).append(item)
        total += 1

    folder_in_archive = _workspace_folder_scope(org)["folder_in_archive"]
    title_labels = {
        "exact": "Titel matchar",
        "starts": "Titel matchar",
        "contains": "Titel matchar",
    }
    name_labels = {
        "exact": "Namn matchar",
        "starts": "Namn matchar",
        "contains": "Namn matchar",
    }
    designation_labels = {
        "exact": "Beteckning matchar",
        "starts": "Beteckning matchar",
        "contains": "Beteckning matchar",
    }

    document_candidates = list(
        Document.objects.filter(org=org, is_deleted=False)
        .filter(
            Q(title__icontains=q)
            | Q(description__icontains=q)
            | Q(content__icontains=q)
        )
        .select_related("meeting")
        .order_by("-updated_at")[:candidate_limit]
    )
    for rank, _, document, match, field in _search_top_rows(
        q,
        document_candidates,
        lambda doc: [
            {"value": doc.title, "labels": title_labels, "field": "title"},
            {
                "value": doc.description,
                "labels": {
                    "exact": "Beskrivning matchar",
                    "contains": "Beskrivning matchar",
                },
                "field": "description",
            },
            {
                "value": doc.content,
                "labels": {
                    "exact": "Innehåll matchar",
                    "contains": "Innehåll matchar",
                },
                "field": "content",
                "strip_html": True,
            },
        ],
        tie_breaker=lambda doc: doc.updated_at.timestamp() if doc.updated_at else 0,
        limit=limit_per_group,
    ):
        subtitle_parts = []
        if (
            document.is_archived
            and document.workflow_status == DocumentWorkflowStatus.FINALIZED
        ):
            subtitle_parts.append("Arkiv")
        else:
            subtitle_parts.append("Arbetsdokument")
        if document.meeting_id:
            subtitle_parts.append("Möteskopplat")
        else:
            subtitle_parts.append("Ej möteskopplat")

        item = {
            "type": "document",
            "title": document.title,
            "subtitle": " - ".join(subtitle_parts),
            "match": match,
            "url": _safe_reverse(
                "portal:document_detail",
                document.pk,
                fallback="portal:document_overview",
            ),
            "icon": "fa-file-lines",
        }
        if field == "content":
            snippet = _search_content_snippet(q, document.content)
            if snippet:
                item["snippet"] = snippet
        add_item("Dokument", item)

    folder_candidates = list(
        DocumentFolder.objects.filter(org=org, name__icontains=q)
        .select_related("parent")
        .order_by("name")[:candidate_limit]
    )
    for rank, _, folder, match, field in _search_top_rows(
        q,
        folder_candidates,
        lambda f: [{"value": f.name, "labels": name_labels, "field": "name"}],
        tie_breaker=lambda f: f.name.lower(),
        limit=limit_per_group,
    ):
        is_archive_folder = folder_in_archive.get(folder.pk, False) or _is_archive_system_key(
            folder.system_key
        )
        if is_archive_folder:
            folder_url = f"{reverse('portal:document_archive')}?folder={folder.pk}"
            folder_subtitle = "Arkivmapp"
        else:
            folder_url = f"{reverse('portal:document_workspace')}?folder={folder.pk}"
            folder_subtitle = "Arbetsmapp"
        add_item(
            "Mappar",
            {
                "type": "folder",
                "title": folder.name,
                "subtitle": folder_subtitle,
                "match": match,
                "url": folder_url,
                "icon": "fa-folder",
            },
        )

    meeting_candidates = list(
        Meeting.objects.filter(org=org)
        .filter(Q(title__icontains=q) | Q(location__icontains=q))
        .order_by("-meeting_date")[:candidate_limit]
    )
    for rank, _, meeting, match, field in _search_top_rows(
        q,
        meeting_candidates,
        lambda m: [
            {"value": m.title, "labels": title_labels, "field": "title"},
            {
                "value": m.location,
                "labels": {
                    "exact": "Ort matchar",
                    "contains": "Ort matchar",
                },
                "field": "location",
            },
        ],
        tie_breaker=lambda m: m.meeting_date.timestamp() if m.meeting_date else 0,
        limit=limit_per_group,
    ):
        meeting_dt = timezone.localtime(meeting.meeting_date)
        subtitle = meeting_dt.strftime("%Y-%m-%d")
        if meeting.location:
            subtitle = f"{subtitle} - {meeting.location}"
        add_item(
            "Möten",
            {
                "type": "meeting",
                "title": meeting.title,
                "subtitle": subtitle,
                "match": match,
                "url": _safe_reverse(
                    "governance:meeting_detail",
                    meeting.pk,
                    fallback="governance:upcoming_meetings",
                ),
                "icon": "fa-calendar-check",
            },
        )

    matter_candidates = list(
        BoardMatter.objects.filter(org=org)
        .filter(
            Q(title__icontains=q)
            | Q(description__icontains=q)
            | Q(prepared_statement__icontains=q)
            | Q(meeting_decision__icontains=q)
        )
        .order_by("-updated_at")[:candidate_limit]
    )
    for rank, _, matter, match, field in _search_top_rows(
        q,
        matter_candidates,
        lambda m: [
            {"value": m.title, "labels": title_labels, "field": "title"},
            {
                "value": m.description,
                "labels": {
                    "exact": "Beskrivning matchar",
                    "contains": "Beskrivning matchar",
                },
                "field": "description",
            },
            {
                "value": m.prepared_statement,
                "labels": {
                    "exact": "Innehåll matchar",
                    "contains": "Innehåll matchar",
                },
                "field": "prepared_statement",
            },
            {
                "value": m.meeting_decision,
                "labels": {
                    "exact": "Beslut matchar",
                    "contains": "Beslut matchar",
                },
                "field": "meeting_decision",
            },
        ],
        tie_breaker=lambda m: m.updated_at.timestamp() if m.updated_at else 0,
        limit=limit_per_group,
    ):
        add_item(
            "Ärenden",
            {
                "type": "matter",
                "title": matter.title,
                "subtitle": matter.get_status_display(),
                "match": match,
                "url": _safe_reverse(
                    "governance:matter_detail",
                    matter.pk,
                    fallback="governance:matter_list",
                ),
                "icon": "fa-clipboard-list",
            },
        )

    property_candidates = list(
        Property.objects.filter(org=org)
        .filter(Q(designation__icontains=q) | Q(external_id__icontains=q))
        .order_by("designation")[:candidate_limit]
    )
    for rank, _, property_obj, match, field in _search_top_rows(
        q,
        property_candidates,
        lambda p: [
            {
                "value": p.designation,
                "labels": designation_labels,
                "field": "designation",
            },
            {
                "value": p.external_id,
                "labels": {
                    "exact": "Externt ID matchar",
                    "contains": "Externt ID matchar",
                },
                "field": "external_id",
            },
        ],
        tie_breaker=lambda p: p.designation.lower(),
        limit=limit_per_group,
    ):
        add_item(
            "Fastigheter",
            {
                "type": "property",
                "title": property_obj.designation,
                "subtitle": property_obj.external_id or "Fastighet",
                "match": match,
                "url": _safe_reverse(
                    "portal:property_detail",
                    property_obj.pk,
                    fallback="portal:property_list",
                ),
                "icon": "fa-building",
            },
        )

    holder_candidates = list(
        RightHolder.objects.filter(org=org)
        .filter(Q(name__icontains=q) | Q(email__icontains=q))
        .order_by("name")[:candidate_limit]
    )
    for rank, _, holder, match, field in _search_top_rows(
        q,
        holder_candidates,
        lambda h: [
            {"value": h.name, "labels": name_labels, "field": "name"},
            {
                "value": h.email,
                "labels": {
                    "exact": "E-post matchar",
                    "contains": "E-post matchar",
                },
                "field": "email",
            },
        ],
        tie_breaker=lambda h: h.name.lower(),
        limit=limit_per_group,
    ):
        add_item(
            "Rättighetshavare",
            {
                "type": "right_holder",
                "title": holder.name,
                "subtitle": holder.email or "Rättighetshavare",
                "match": match,
                "url": f"{reverse('portal:property_list')}?{urlencode({'q': holder.name})}",
                "icon": "fa-user",
            },
        )

    event_candidates = list(
        CalendarEvent.objects.filter(org=org)
        .filter(
            Q(title__icontains=q)
            | Q(description__icontains=q)
            | Q(location__icontains=q)
        )
        .order_by("start_at")[:candidate_limit]
    )
    for rank, _, event, match, field in _search_top_rows(
        q,
        event_candidates,
        lambda e: [
            {"value": e.title, "labels": title_labels, "field": "title"},
            {
                "value": e.description,
                "labels": {
                    "exact": "Beskrivning matchar",
                    "contains": "Beskrivning matchar",
                },
                "field": "description",
            },
            {
                "value": e.location,
                "labels": {
                    "exact": "Ort matchar",
                    "contains": "Ort matchar",
                },
                "field": "location",
            },
        ],
        tie_breaker=lambda e: e.start_at.timestamp() if e.start_at else 0,
        limit=limit_per_group,
    ):
        event_dt = timezone.localtime(event.start_at)
        subtitle = event_dt.strftime("%Y-%m-%d %H:%M")
        if event.location:
            subtitle = f"{subtitle} - {event.location}"
        add_item(
            "Kalender",
            {
                "type": "calendar_event",
                "title": event.title,
                "subtitle": subtitle,
                "match": match,
                "url": _safe_reverse(
                    "calendarapp:detail",
                    event.pk,
                    fallback="calendarapp:list",
                ),
                "icon": "fa-calendar-days",
            },
        )

    action_candidates = list(
        ActionArea.objects.for_org(org).not_trashed()
        .filter(Q(name__icontains=q) | Q(description__icontains=q))
        .order_by("-updated_at")[:candidate_limit]
    )
    for rank, _, action, match, field in _search_top_rows(
        q,
        action_candidates,
        lambda a: [
            {"value": a.name, "labels": name_labels, "field": "name"},
            {
                "value": a.description,
                "labels": {
                    "exact": "Beskrivning matchar",
                    "contains": "Beskrivning matchar",
                },
                "field": "description",
            },
        ],
        tie_breaker=lambda a: a.updated_at.timestamp() if a.updated_at else 0,
        limit=limit_per_group,
    ):
        subtitle = action.get_status_display()
        if action.deadline:
            subtitle = f"{subtitle} - Deadline {action.deadline:%Y-%m-%d}"
        add_item(
            "Fiskevård",
            {
                "type": "fisheries_action",
                "title": action.name,
                "subtitle": subtitle,
                "match": match,
                "url": _safe_reverse(
                    "fisheries:action_detail",
                    action.pk,
                    fallback="fisheries:overview",
                ),
                "icon": "fa-fish",
            },
        )

    return {
        "groups": [
            {"label": label, "items": items}
            for label, items in groups.items()
            if items
        ],
        "total": total,
    }


@login_required
@require_GET
def global_search(request):
    q = (request.GET.get("q") or "").strip()

    empty_payload = {
        "query": q,
        "groups": [],
        "total": 0,
    }
    if request.org is None or len(q) < 2:
        return JsonResponse(empty_payload)

    result = _build_global_search_groups(
        request.org,
        q,
        limit_per_group=_SEARCH_DISPLAY_LIMIT,
    )
    payload = {
        "query": q,
        "groups": result["groups"],
        "total": result["total"],
        "results_url": (
            f"{reverse('portal:global_search_results')}?{urlencode({'q': q})}"
        ),
    }
    return JsonResponse(payload)


@login_required
def global_search_results(request):
    org = request.org
    q = (request.GET.get("q") or "").strip()

    if org is None:
        messages.warning(request, "Ingen aktiv organisation vald.")
        return redirect("portal:dashboard")

    query_too_short = len(q) < 2
    groups = []
    total = 0

    if not query_too_short:
        result = _build_global_search_groups(
            org,
            q,
            limit_per_group=_SEARCH_RESULTS_PAGE_LIMIT,
        )
        groups = result["groups"]
        total = result["total"]

    return render(
        request,
        "portal/global_search_results.html",
        {
            "q": q,
            "groups": groups,
            "total": total,
            "query_too_short": query_too_short,
        },
    )


@login_required
def activity_list(request):
    q = (request.GET.get("q") or "").strip()
    action = (request.GET.get("action") or "").strip()
    from_date = (request.GET.get("from_date") or "").strip()
    to_date = (request.GET.get("to_date") or "").strip()

    activities_qs = (
        DocumentActivity.objects.filter(document__org=request.org)
        .select_related("document", "user")
        .order_by("-created_at")
    )

    if q:
        activities_qs = activities_qs.filter(
            Q(document__title__icontains=q)
            | Q(message__icontains=q)
            | Q(user__email__icontains=q)
        )

    valid_actions = {choice[0] for choice in DocumentActivity.ACTION_CHOICES}
    if action in valid_actions:
        activities_qs = activities_qs.filter(action=action)

    if from_date:
        try:
            parsed_from_date = date.fromisoformat(from_date)
            activities_qs = activities_qs.filter(created_at__date__gte=parsed_from_date)
        except ValueError:
            pass

    if to_date:
        try:
            parsed_to_date = date.fromisoformat(to_date)
            activities_qs = activities_qs.filter(created_at__date__lte=parsed_to_date)
        except ValueError:
            pass

    paginator = Paginator(activities_qs, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    query_params = request.GET.copy()
    query_params.pop("page", None)
    query_string = query_params.urlencode()
    action_label = dict(DocumentActivity.ACTION_CHOICES).get(action, "")

    return render(
        request,
        "portal/activity_list.html",
        {
            "page_obj": page_obj,
            "q": q,
            "action": action,
            "from_date": from_date,
            "to_date": to_date,
            "action_choices": DocumentActivity.ACTION_CHOICES,
            "query_string": query_string,
            "action_label": action_label,
        },
    )


@login_required
def property_list(request):
    org = request.org

    qs = Property.objects.filter(org=org).order_by("designation")

    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(
            Q(designation__icontains=q) |
            Q(external_id__icontains=q)
        )

    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "portal/property_list.html",
        {"page_obj": page_obj, "q": q},
    )


@login_required
def property_detail(request, pk):
    org = request.org

    property_obj = get_object_or_404(
        Property.objects.filter(org=org),
        pk=pk
    )

    shares = (
        FishingRightShare.objects
        .filter(property=property_obj)
        .select_related("holder")
        .order_by("-share")
    )

    total_share = shares.aggregate(total=Sum("share"))["total"] or 0

    return render(
        request,
        "portal/property_detail.html",
        {
            "property": property_obj,
            "shares": shares,
            "total_share": total_share,
        },
    )


@login_required
def document_overview(request):
    org = request.org

    workspace_count = Document.objects.filter(
        org=org,
        is_deleted=False,
    ).exclude(
        is_archived=True,
        workflow_status=DocumentWorkflowStatus.FINALIZED,
    ).count()

    archive_count = Document.objects.filter(
        org=org,
        is_deleted=False,
        is_archived=True,
        workflow_status=DocumentWorkflowStatus.FINALIZED,
    ).count()

    trash_count = Document.objects.filter(
        org=org,
        is_deleted=True,
    ).count()

    return render(
        request,
        "portal/document_overview.html",
        {
            "workspace_count": workspace_count,
            "archive_count": archive_count,
            "trash_count": trash_count,
        },
    )


def render_document_collection(request, mode):
    org = request.org
    category = request.GET.get("category")
    q = (request.GET.get("q") or "").strip()
    from_date = (request.GET.get("from_date") or "").strip()
    to_date = (request.GET.get("to_date") or "").strip()

    qs = Document.objects.filter(
        org=org,
        is_deleted=False,
    ).select_related("meeting", "template", "uploaded_by")

    if mode == "archive":
        qs = qs.filter(
            is_archived=True,
            workflow_status=DocumentWorkflowStatus.FINALIZED,
        )
        date_attr = "updated_at"
        page_title = "Arkiv"
        page_subtitle = "Finaliserade, signerade och arkiverade dokument."
    else:
        qs = qs.exclude(
            is_archived=True,
            workflow_status=DocumentWorkflowStatus.FINALIZED,
        )
        date_attr = "created_at"
        page_title = "Arbetsdokument"
        page_subtitle = "Utkast, dokument under justering och dokument redo för signering."

    if category:
        qs = qs.filter(category=category)

    if from_date:
        try:
            parsed_from_date = date.fromisoformat(from_date)
            qs = qs.filter(**{f"{date_attr}__date__gte": parsed_from_date})
        except ValueError:
            pass

    if to_date:
        try:
            parsed_to_date = date.fromisoformat(to_date)
            qs = qs.filter(**{f"{date_attr}__date__lte": parsed_to_date})
        except ValueError:
            pass

    if q:
        date_query = Q()

        if len(q) == 10:
            try:
                parsed_exact_date = date.fromisoformat(q)
                date_query = Q(**{f"{date_attr}__date": parsed_exact_date})
            except ValueError:
                pass
        elif len(q) == 7:
            try:
                parsed_year_month = date.fromisoformat(f"{q}-01")
                date_query = Q(
                    **{
                        f"{date_attr}__year": parsed_year_month.year,
                        f"{date_attr}__month": parsed_year_month.month,
                    }
                )
            except ValueError:
                pass
        elif len(q) == 4 and q.isdigit():
            parsed_year = int(q)
            date_query = Q(**{f"{date_attr}__year": parsed_year})

        if date_query:
            qs = qs.filter(Q(title__icontains=q) | date_query)
        else:
            qs = qs.filter(title__icontains=q)

    qs = qs.order_by(f"-{date_attr}", "-created_at")

    grouped_documents = group_documents_by_year_month(qs, date_attr=date_attr)

    return render(
        request,
        "portal/document_collection.html",
        {
            "grouped_documents": grouped_documents,
            "mode": mode,
            "q": q,
            "category": category,
            "from_date": from_date,
            "to_date": to_date,
            "page_title": page_title,
            "page_subtitle": page_subtitle,
        },
    )


@login_required
def document_workspace(request):
    if request.org is None:
        messages.error(request, "Ingen aktiv organisation vald.")
        return redirect("portal:document_overview")

    org = request.org
    workspace_root = _ensure_workspace_root(org)
    folder_id = (request.GET.get("folder") or "").strip()
    scope = _workspace_folder_scope(org)
    workspace_folders = scope["workspace_folders"]
    workspace_ids = scope["workspace_ids"]
    folder_in_archive = scope["folder_in_archive"]

    if folder_id:
        current_folder = get_object_or_404(
            DocumentFolder.objects.select_related("parent"),
            pk=folder_id,
            org=org,
        )
        if folder_in_archive.get(current_folder.pk, False):
            raise Http404("Mappen finns inte i arbetsdokument.")
    else:
        current_folder = workspace_root

    child_folders = [
        f for f in workspace_folders
        if current_folder is not None and f.parent_id == current_folder.pk
    ]
    workspace_system_folders, workspace_custom_folders = _split_workspace_child_folders(
        child_folders
    )
    folders = workspace_system_folders + workspace_custom_folders

    docs_qs = (
        Document.objects.filter(
            org=org,
            is_deleted=False,
        )
        .exclude(
            is_archived=True,
            workflow_status=DocumentWorkflowStatus.FINALIZED,
        )
        .select_related("meeting", "folder")
        .prefetch_related("signatures")
    )

    if current_folder is not None:
        if current_folder.pk == workspace_root.pk:
            docs_qs = docs_qs.filter(
                Q(folder=current_folder) | Q(folder__isnull=True)
            )
        else:
            docs_qs = docs_qs.filter(folder=current_folder)
    else:
        docs_qs = docs_qs.filter(folder__isnull=True)

    documents = []
    for d in docs_qs.order_by("-created_at"):
        if d.folder_id and folder_in_archive.get(d.folder_id, False):
            continue
        d.has_pending_signatures = (
            d.workflow_status == DocumentWorkflowStatus.APPROVED
            and any(
                s.status == DocumentSignatureStatus.PENDING
                for s in d.signatures.all()
            )
        )
        documents.append(d)

    breadcrumbs = _build_workspace_breadcrumbs(current_folder) if current_folder else []
    expanded_folder_ids = _collect_expanded_folder_ids(current_folder)
    folder_document_counts = _workspace_folder_document_counts(org, workspace_ids)

    for f in child_folders:
        f.workspace_doc_count = folder_document_counts.get(f.pk, 0)
    for crumb in breadcrumbs:
        crumb["folder"].workspace_doc_count = folder_document_counts.get(
            crumb["folder"].pk, 0
        )

    tree_children_by_parent = {}
    for f in workspace_folders:
        pid = f.parent_id
        if pid is None:
            continue
        tree_children_by_parent.setdefault(pid, []).append(f)
    for pid in tree_children_by_parent:
        tree_children_by_parent[pid].sort(key=_workspace_tree_sort_key)

    tree_nodes = []

    def append_tree(folder, depth):
        tree_nodes.append({
            "folder": folder,
            "depth": depth,
            "doc_count": folder_document_counts.get(folder.pk, 0),
        })
        for child in tree_children_by_parent.get(folder.pk, []):
            append_tree(child, depth + 1)

    for child in tree_children_by_parent.get(workspace_root.pk, []):
        append_tree(child, 1)

    all_workspace_folders_for_move = _all_workspace_folders_for_move(org)

    return render(
        request,
        "portal/document_workspace_browser.html",
        {
            "workspace_root": workspace_root,
            "current_folder": current_folder,
            "folders": folders,
            "documents": documents,
            "breadcrumbs": breadcrumbs,
            "expanded_folder_ids": expanded_folder_ids,
            "folder_document_counts": folder_document_counts,
            "tree_nodes": tree_nodes,
            "workspace_root_missing": False,
            "all_workspace_folders_for_move": all_workspace_folders_for_move,
        },
    )


def _collect_expanded_folder_ids(current_folder):
    """Folder PKs from current_folder up through parents (for tree expand state)."""
    ids = []
    folder = current_folder
    while folder is not None:
        ids.append(folder.pk)
        folder = folder.parent
    return ids


def _folder_document_counts(org):
    """Archived finalized document counts per folder (tenant-scoped)."""
    rows = (
        Document.objects.filter(
            org=org,
            is_deleted=False,
            is_archived=True,
            workflow_status=DocumentWorkflowStatus.FINALIZED,
            folder_id__isnull=False,
        )
        .values("folder_id")
        .annotate(c=Count("id"))
    )
    return {row["folder_id"]: row["c"] for row in rows}


def _folder_path_label(folder, by_id):
    """Build 'Arkiv / 2026 / …' from parent chain (tenant-safe, in-memory)."""
    parts = []
    node = folder
    seen = set()
    while node is not None and node.pk not in seen:
        seen.add(node.pk)
        parts.append(node.name)
        pid = node.parent_id
        node = by_id.get(pid) if pid else None
    parts.reverse()
    return " / ".join(parts) if parts else folder.name


def _resolve_upload_target_folder(org, folder_id_raw):
    """
    Resolve DocumentFolder for upload from a raw id string (GET/POST).
    Tenant-scoped; wrong org or unknown pk → 404. Empty → (None, None).
    """
    raw = (folder_id_raw or "").strip()
    if not raw:
        return None, None
    if not raw.isdigit():
        raise Http404("Ogiltig mapp.")
    folder = get_object_or_404(DocumentFolder, pk=int(raw), org=org)
    by_id = {f.pk: f for f in DocumentFolder.objects.filter(org=org)}
    return folder, _folder_path_label(folder, by_id)


def _resolve_workspace_upload_target_folder(org, folder_id_raw):
    """
    Resolve workspace upload target: workspace-root or a folder under it.
    Never archive. Wrong org / invalid folder → 404.
    """
    workspace_root = _ensure_workspace_root(org)
    scope = _workspace_folder_scope(org)
    folder_in_archive = scope["folder_in_archive"]
    by_id = {
        f.pk: f
        for f in DocumentFolder.objects.filter(org=org).select_related("parent")
    }

    raw = (folder_id_raw or "").strip()
    if not raw:
        target = workspace_root
    else:
        if not raw.isdigit():
            raise Http404("Ogiltig mapp.")
        target = get_object_or_404(DocumentFolder, pk=int(raw), org=org)

    if folder_in_archive.get(target.pk, False):
        raise Http404("Mappen finns inte i arbetsdokument.")

    if not _folder_is_valid_workspace_parent(
        target, workspace_root, by_id, folder_in_archive
    ):
        raise Http404("Mappen finns inte i arbetsdokument.")

    return target, _folder_path_label(target, by_id)


def _all_folders_for_move(org):
    """All folders for move-to select, sorted by path label."""
    folders = list(
        DocumentFolder.objects.filter(org=org).select_related("parent")
    )
    by_id = {f.pk: f for f in folders}
    out = []
    for f in folders:
        out.append({
            "id": f.pk,
            "path_label": _folder_path_label(f, by_id),
        })
    out.sort(key=lambda x: (x["path_label"].lower(), x["id"]))
    return out


def _workspace_folder_path_label(folder, workspace_root, by_id):
    """Path from workspace-root down to folder, e.g. Arbetsdokument / Fiskevård."""
    parts = []
    node = folder
    seen = set()
    while node is not None and node.pk not in seen:
        seen.add(node.pk)
        parts.append(node.name)
        if node.pk == workspace_root.pk:
            break
        pid = node.parent_id
        node = by_id.get(pid) if pid else None
    parts.reverse()
    return " / ".join(parts)


def _all_workspace_folders_for_move(org):
    """Workspace-root and descendants for move-to select (never archive)."""
    workspace_root = _ensure_workspace_root(org)
    scope = _workspace_folder_scope(org)
    folder_in_archive = scope["folder_in_archive"]
    by_id = {
        f.pk: f
        for f in DocumentFolder.objects.filter(org=org).select_related("parent")
    }
    out = []
    for folder in scope["workspace_folders"]:
        if folder_in_archive.get(folder.pk, False):
            continue
        if not _folder_is_valid_workspace_parent(
            folder, workspace_root, by_id, folder_in_archive
        ):
            continue
        out.append({
            "id": folder.pk,
            "path_label": _workspace_folder_path_label(
                folder, workspace_root, by_id
            ),
        })
    out.sort(key=lambda x: (x["path_label"].lower(), x["id"]))
    return out


def _build_archive_breadcrumbs(current_folder):
    """Build breadcrumb trail from archive root to current_folder."""
    crumbs = []
    folder = current_folder
    while folder is not None:
        crumbs.append({
            "folder": folder,
            "name": folder.name,
            "url": f"{reverse('portal:document_archive')}?folder={folder.pk}",
        })
        folder = folder.parent
    crumbs.reverse()
    return crumbs


def _is_archive_system_key(system_key):
    key = (system_key or "").strip().lower()
    return key == "archive" or key.startswith("archive/")


WORKSPACE_CATEGORY_SYSTEM_KEYS = (
    "workspace/meeting-documents",
    "workspace/protocol-drafts",
    "workspace/bylaws",
    "workspace/notices",
    "workspace/motions",
    "workspace/decisions",
    "workspace/other",
)
WORKSPACE_CATEGORY_SYSTEM_KEY_ORDER = {
    key: index for index, key in enumerate(WORKSPACE_CATEGORY_SYSTEM_KEYS)
}


def _is_workspace_category_system_folder(folder):
    if not folder.is_system_folder:
        return False
    key = (folder.system_key or "").strip().lower()
    return key.startswith("workspace/")


def _split_workspace_child_folders(child_folders):
    """Split direct children into backfill system folders vs user custom folders."""
    system_folders = []
    custom_folders = []
    for folder in child_folders:
        if _is_workspace_category_system_folder(folder):
            system_folders.append(folder)
        elif not folder.is_system_folder:
            custom_folders.append(folder)
    system_folders.sort(
        key=lambda f: (
            WORKSPACE_CATEGORY_SYSTEM_KEY_ORDER.get(
                (f.system_key or "").strip().lower(),
                len(WORKSPACE_CATEGORY_SYSTEM_KEYS),
            ),
            f.name.lower(),
            f.pk,
        )
    )
    custom_folders.sort(key=lambda f: (f.name.lower(), f.pk))
    return system_folders, custom_folders


def _workspace_tree_sort_key(folder):
    if _is_workspace_category_system_folder(folder):
        key = (folder.system_key or "").strip().lower()
        return (
            0,
            WORKSPACE_CATEGORY_SYSTEM_KEY_ORDER.get(
                key, len(WORKSPACE_CATEGORY_SYSTEM_KEYS)
            ),
            folder.name.lower(),
            folder.pk,
        )
    return (1, 0, folder.name.lower(), folder.pk)


def _workspace_folder_scope(org):
    """
    Return all org folders outside the archive subtree.
    Also returns maps for fast lookups and archive-subtree checks.
    """
    folders = list(
        DocumentFolder.objects.filter(org=org).select_related("parent")
    )
    by_id = {f.pk: f for f in folders}
    archive_memo = {}

    def is_archive_folder(folder):
        if folder is None:
            return False
        cached = archive_memo.get(folder.pk)
        if cached is not None:
            return cached
        if _is_archive_system_key(folder.system_key):
            archive_memo[folder.pk] = True
            return True
        if folder.parent_id is None:
            archive_memo[folder.pk] = False
            return False
        parent = by_id.get(folder.parent_id)
        in_archive = is_archive_folder(parent)
        archive_memo[folder.pk] = in_archive
        return in_archive

    folder_in_archive = {}
    workspace_folders = []
    for f in folders:
        in_archive = is_archive_folder(f)
        folder_in_archive[f.pk] = in_archive
        if not in_archive:
            workspace_folders.append(f)

    workspace_ids = {f.pk for f in workspace_folders}
    return {
        "workspace_folders": workspace_folders,
        "workspace_ids": workspace_ids,
        "folder_in_archive": folder_in_archive,
    }


def _build_workspace_breadcrumbs(current_folder):
    crumbs = []
    folder = current_folder
    while folder is not None:
        crumbs.append({
            "folder": folder,
            "name": folder.name,
            "url": f"{reverse('portal:document_workspace')}?folder={folder.pk}",
        })
        folder = folder.parent
    crumbs.reverse()
    return crumbs


def _workspace_folder_document_counts(org, workspace_folder_ids):
    rows = (
        Document.objects.filter(
            org=org,
            is_deleted=False,
            folder_id__in=workspace_folder_ids,
        )
        .exclude(
            is_archived=True,
            workflow_status=DocumentWorkflowStatus.FINALIZED,
        )
        .values("folder_id")
        .annotate(c=Count("id"))
    )
    return {row["folder_id"]: row["c"] for row in rows}


def _ensure_workspace_root(org):
    """Create workspace system root on demand (tenant-scoped, no migration)."""
    folder, _created = DocumentFolder.objects.get_or_create(
        org=org,
        system_key="workspace",
        is_system_folder=True,
        defaults={
            "name": "Arbetsdokument",
            "parent": None,
            "folder_type": DocumentFolderType.STATIC,
        },
    )

    orphans = DocumentFolder.objects.filter(
        org=org,
        parent__isnull=True,
        is_system_folder=False,
    ).exclude(pk=folder.pk)

    for orphan in orphans:
        if _is_archive_system_key(orphan.system_key):
            continue
        orphan.parent = folder
        orphan.save(update_fields=["parent"])

    return folder


def _folder_is_valid_workspace_parent(parent, workspace_root, by_id, folder_in_archive):
    """Parent must be workspace-root or a descendant under it, never under archive."""
    if parent is None or workspace_root is None:
        return False
    if folder_in_archive.get(parent.pk, False):
        return False
    if parent.pk == workspace_root.pk:
        return True
    node = parent
    seen = set()
    while node is not None and node.pk not in seen:
        seen.add(node.pk)
        if node.pk == workspace_root.pk:
            return True
        if folder_in_archive.get(node.pk, False):
            return False
        pid = node.parent_id
        node = by_id.get(pid) if pid else None
    return False


def _workspace_redirect_url(parent):
    url = reverse("portal:document_workspace")
    if parent is not None:
        return f"{url}?folder={parent.pk}"
    return url


def _workspace_redirect_url_for_post(org, parent_id):
    """Redirect target when validation fails before parent is resolved."""
    if parent_id:
        parent = DocumentFolder.objects.filter(pk=parent_id, org=org).first()
        if parent:
            return _workspace_redirect_url(parent)
    workspace_root = DocumentFolder.objects.filter(
        org=org,
        system_key="workspace",
        is_system_folder=True,
    ).first()
    return _workspace_redirect_url(workspace_root)


@login_required
@require_POST
def document_workspace_folder_create(request):
    if request.org is None:
        messages.error(request, "Ingen aktiv organisation vald.")
        return redirect("portal:document_overview")

    org = request.org
    name = (request.POST.get("name") or "").strip()
    parent_id = (request.POST.get("parent_id") or "").strip()

    if not name:
        messages.error(request, "Ange ett mappnamn.")
        return redirect(_workspace_redirect_url_for_post(org, parent_id))

    if len(name) > 255:
        messages.error(request, "Mappnamnet får vara högst 255 tecken.")
        return redirect(_workspace_redirect_url_for_post(org, parent_id))

    scope = _workspace_folder_scope(org)
    by_id = {
        f.pk: f
        for f in DocumentFolder.objects.filter(org=org).select_related("parent")
    }
    folder_in_archive = scope["folder_in_archive"]
    workspace_root = _ensure_workspace_root(org)

    if parent_id:
        parent = get_object_or_404(DocumentFolder, pk=parent_id, org=org)
        if not _folder_is_valid_workspace_parent(
            parent, workspace_root, by_id, folder_in_archive
        ):
            raise Http404("Mappen finns inte i arbetsdokument.")
    else:
        parent = workspace_root

    duplicate_exists = DocumentFolder.objects.filter(
        org=org,
        parent=parent,
        name=name,
        is_system_folder=False,
    ).exists()
    if duplicate_exists:
        messages.error(request, "Det finns redan en mapp med det namnet på den här platsen.")
        return redirect(_workspace_redirect_url(parent))

    try:
        DocumentFolder.objects.create(
            org=org,
            name=name,
            parent=parent,
            created_by=request.user,
            is_system_folder=False,
            folder_type=DocumentFolderType.CUSTOM,
            system_key="",
        )
    except IntegrityError:
        messages.error(request, "Det finns redan en mapp med det namnet på den här platsen.")
        return redirect(_workspace_redirect_url(parent))

    messages.success(request, "Mappen skapades.")
    return redirect(_workspace_redirect_url(parent))


@login_required
def document_archive(request):
    org = request.org
    folder_id = (request.GET.get("folder") or "").strip()

    if folder_id:
        current_folder = get_object_or_404(
            DocumentFolder.objects.select_related("parent"),
            pk=folder_id,
            org=org,
        )
    else:
        current_folder = (
            DocumentFolder.objects.filter(
                org=org,
                system_key="archive",
                is_system_folder=True,
            )
            .select_related("parent")
            .first()
        )

    if current_folder is not None:
        folders = list(
            DocumentFolder.objects.filter(org=org, parent=current_folder)
            .order_by("folder_type", "name")
        )
        documents = (
            Document.objects.filter(
                org=org,
                folder=current_folder,
                is_deleted=False,
                is_archived=True,
                workflow_status=DocumentWorkflowStatus.FINALIZED,
            )
            .order_by("-updated_at")
        )
        breadcrumbs = _build_archive_breadcrumbs(current_folder)
    else:
        folders = list(
            DocumentFolder.objects.filter(org=org, parent__isnull=True)
            .order_by("folder_type", "name")
        )
        documents = (
            Document.objects.filter(
                org=org,
                folder__isnull=True,
                is_deleted=False,
                is_archived=True,
                workflow_status=DocumentWorkflowStatus.FINALIZED,
            )
            .order_by("-updated_at")
        )
        breadcrumbs = []

    expanded_folder_ids = _collect_expanded_folder_ids(current_folder)
    folder_document_counts = _folder_document_counts(org)
    all_folders_for_move = _all_folders_for_move(org)

    for f in folders:
        f.archive_doc_count = folder_document_counts.get(f.pk, 0)
    for crumb in breadcrumbs:
        crumb["folder"].archive_doc_count = folder_document_counts.get(
            crumb["folder"].pk, 0
        )

    return render(
        request,
        "portal/document_archive_browser.html",
        {
            "current_folder": current_folder,
            "folders": folders,
            "documents": documents,
            "breadcrumbs": breadcrumbs,
            "expanded_folder_ids": expanded_folder_ids,
            "folder_document_counts": folder_document_counts,
            "all_folders_for_move": all_folders_for_move,
        },
    )


def _archive_redirect_url(parent):
    url = reverse("portal:document_archive")
    if parent is not None:
        return f"{url}?folder={parent.pk}"
    return url


@login_required
@require_POST
def document_move_to_folder(request, pk):
    if request.org is None:
        messages.error(request, "Ingen aktiv organisation vald.")
        return redirect("portal:document_overview")

    org = request.org

    def _redirect_after_move():
        rf = (request.POST.get("return_folder") or "").strip()
        if rf.isdigit() and DocumentFolder.objects.filter(
            pk=int(rf), org=org
        ).exists():
            return redirect(
                f"{reverse('portal:document_archive')}?folder={rf}"
            )
        return redirect("portal:document_archive")

    document = get_object_or_404(
        Document.objects.filter(
            org=org,
            is_deleted=False,
            is_archived=True,
            workflow_status=DocumentWorkflowStatus.FINALIZED,
        ),
        pk=pk,
    )

    raw_folder_id = (request.POST.get("folder_id") or "").strip()
    if not raw_folder_id.isdigit():
        messages.error(request, "Välj en målmapp.")
        return _redirect_after_move()

    target_folder = get_object_or_404(
        DocumentFolder,
        pk=int(raw_folder_id),
        org=org,
    )

    document.folder = target_folder
    document.folder_auto_assigned = False
    document.save(
        update_fields=["folder", "folder_auto_assigned", "updated_at"]
    )
    messages.success(request, "Dokumentet har flyttats.")
    return redirect(
        f"{reverse('portal:document_archive')}?folder={target_folder.pk}"
    )


@login_required
@require_POST
def document_workspace_move_to_folder(request, pk):
    if request.org is None:
        messages.error(request, "Ingen aktiv organisation vald.")
        return redirect("portal:document_overview")

    org = request.org
    workspace_root = _ensure_workspace_root(org)

    def _redirect_after_move(target=None):
        if target is not None:
            return redirect(
                f"{reverse('portal:document_workspace')}?folder={target.pk}"
            )
        rf = (request.POST.get("return_folder") or "").strip()
        if rf.isdigit():
            folder = DocumentFolder.objects.filter(pk=int(rf), org=org).first()
            if folder:
                return redirect(
                    f"{reverse('portal:document_workspace')}?folder={folder.pk}"
                )
        return redirect(_workspace_redirect_url(workspace_root))

    document = get_object_or_404(
        Document.objects.filter(
            org=org,
            is_deleted=False,
        ).exclude(
            is_archived=True,
            workflow_status=DocumentWorkflowStatus.FINALIZED,
        ),
        pk=pk,
    )

    raw_folder_id = (request.POST.get("folder_id") or "").strip()
    if not raw_folder_id.isdigit():
        messages.error(request, "Välj en målmapp.")
        return _redirect_after_move()

    target_folder = get_object_or_404(
        DocumentFolder,
        pk=int(raw_folder_id),
        org=org,
    )

    scope = _workspace_folder_scope(org)
    folder_in_archive = scope["folder_in_archive"]
    by_id = {
        f.pk: f
        for f in DocumentFolder.objects.filter(org=org).select_related("parent")
    }

    if folder_in_archive.get(target_folder.pk, False):
        raise Http404("Mappen finns inte i arbetsdokument.")

    if not _folder_is_valid_workspace_parent(
        target_folder, workspace_root, by_id, folder_in_archive
    ):
        raise Http404("Mappen finns inte i arbetsdokument.")

    if document.folder_id and folder_in_archive.get(document.folder_id, False):
        raise Http404("Dokumentet finns inte i arbetsdokument.")

    document.folder = target_folder
    document.folder_auto_assigned = False
    document.save(
        update_fields=["folder", "folder_auto_assigned", "updated_at"]
    )
    messages.success(request, "Dokumentet har flyttats.")
    return _redirect_after_move(target_folder)


@login_required
@require_POST
def document_workspace_document_rename(request, pk):
    if request.org is None:
        messages.error(request, "Ingen aktiv organisation vald.")
        return redirect("portal:document_overview")

    org = request.org
    document = get_object_or_404(
        Document.objects.filter(
            org=org,
            is_deleted=False,
            meeting__isnull=True,
        ).exclude(
            is_archived=True,
            workflow_status=DocumentWorkflowStatus.FINALIZED,
        ),
        pk=pk,
    )

    title = (request.POST.get("title") or "").strip()
    if not title:
        messages.error(request, "Dokumenttitel kan inte vara tom.")
        return (
            redirect(f"{reverse('portal:document_workspace')}?folder={document.folder_id}")
            if document.folder_id
            else redirect("portal:document_workspace")
        )
    if len(title) > 255:
        messages.error(request, "Dokumenttitel får vara högst 255 tecken.")
        return (
            redirect(f"{reverse('portal:document_workspace')}?folder={document.folder_id}")
            if document.folder_id
            else redirect("portal:document_workspace")
        )

    folder_id = document.folder_id
    document.title = title
    document.save(update_fields=["title", "updated_at"])
    messages.success(request, "Dokumentet bytte namn.")
    return (
        redirect(f"{reverse('portal:document_workspace')}?folder={folder_id}")
        if folder_id
        else redirect("portal:document_workspace")
    )


@login_required
@require_POST
def document_workspace_document_delete(request, pk):
    if request.org is None:
        messages.error(request, "Ingen aktiv organisation vald.")
        return redirect("portal:document_overview")

    org = request.org
    document = get_object_or_404(
        Document.objects.filter(
            org=org,
            is_deleted=False,
            meeting__isnull=True,
        ).exclude(
            is_archived=True,
            workflow_status=DocumentWorkflowStatus.FINALIZED,
        ),
        pk=pk,
    )

    folder_id = document.folder_id
    document.is_deleted = True
    document.save(update_fields=["is_deleted", "updated_at"])
    messages.success(request, "Dokumentet flyttades till papperskorgen.")
    return (
        redirect(f"{reverse('portal:document_workspace')}?folder={folder_id}")
        if folder_id
        else redirect("portal:document_workspace")
    )


@login_required
@require_POST
def document_folder_delete(request, pk):
    if request.org is None:
        messages.error(request, "Ingen aktiv organisation vald.")
        return redirect("portal:document_overview")

    org = request.org
    folder = get_object_or_404(DocumentFolder, pk=pk, org=org)

    def _redirect_back():
        context = (request.POST.get("context") or "").strip().lower()
        parent = folder.parent
        if context == "workspace":
            return (
                redirect(f"{reverse('portal:document_workspace')}?folder={parent.pk}")
                if parent is not None
                else redirect("portal:document_workspace")
            )
        if context == "archive":
            return (
                redirect(f"{reverse('portal:document_archive')}?folder={parent.pk}")
                if parent is not None
                else redirect("portal:document_archive")
            )
        return redirect("portal:document_overview")

    if folder.is_system_folder:
        messages.error(request, "Systemmappar kan inte tas bort.")
        return _redirect_back()

    if folder.children.exists():
        messages.error(
            request,
            "Mappen kan inte tas bort eftersom den innehåller undermappar.",
        )
        return _redirect_back()

    if folder.documents.filter(is_deleted=False).exists():
        messages.error(
            request,
            "Mappen kan inte tas bort eftersom den innehåller dokument.",
        )
        return _redirect_back()

    parent = folder.parent
    folder.delete()
    messages.success(request, "Mappen togs bort.")

    context = (request.POST.get("context") or "").strip().lower()
    if context == "workspace":
        return (
            redirect(f"{reverse('portal:document_workspace')}?folder={parent.pk}")
            if parent is not None
            else redirect("portal:document_workspace")
        )
    if context == "archive":
        return (
            redirect(f"{reverse('portal:document_archive')}?folder={parent.pk}")
            if parent is not None
            else redirect("portal:document_archive")
        )

    return redirect("portal:document_overview")


@login_required
@require_POST
def document_folder_rename(request, pk):
    if request.org is None:
        messages.error(request, "Ingen aktiv organisation vald.")
        return redirect("portal:document_overview")

    org = request.org
    folder = get_object_or_404(DocumentFolder, pk=pk, org=org)
    context_param = (request.POST.get("context") or "").strip().lower()
    return_folder_raw = (request.POST.get("return_folder") or "").strip()

    def redirect_after():
        if context_param == "workspace":
            scope = _workspace_folder_scope(org)
            folder_in_archive = scope["folder_in_archive"]
            browse_pk = folder.pk
            if return_folder_raw.isdigit():
                cand_pk = int(return_folder_raw)
                if DocumentFolder.objects.filter(pk=cand_pk, org=org).exists():
                    if not folder_in_archive.get(cand_pk, False):
                        browse_pk = cand_pk
            return redirect(f"{reverse('portal:document_workspace')}?folder={browse_pk}")
        if context_param == "archive":
            browse_pk = folder.pk
            if return_folder_raw.isdigit():
                cand_pk = int(return_folder_raw)
                if DocumentFolder.objects.filter(pk=cand_pk, org=org).exists():
                    browse_pk = cand_pk
            return redirect(f"{reverse('portal:document_archive')}?folder={browse_pk}")
        return redirect("portal:document_overview")

    if folder.is_system_folder:
        messages.error(request, "Systemmappar kan inte byta namn.")
        return redirect_after()

    name = (request.POST.get("name") or "").strip()
    if not name:
        messages.error(request, "Mappnamn kan inte vara tomt.")
        return redirect_after()
    if len(name) > 255:
        messages.error(request, "Mappnamnet är för långt.")
        return redirect_after()

    duplicate_exists = DocumentFolder.objects.filter(
        org=org,
        parent=folder.parent,
        name=name,
        is_system_folder=False,
    ).exclude(pk=folder.pk).exists()
    if duplicate_exists:
        messages.error(
            request,
            "Det finns redan en mapp med det namnet här.",
        )
        return redirect_after()

    try:
        folder.name = name
        folder.save(update_fields=["name"])
    except IntegrityError:
        messages.error(
            request,
            "Det finns redan en mapp med det namnet här.",
        )
        return redirect_after()

    messages.success(request, "Mappen bytte namn.")
    return redirect_after()


@login_required
@require_POST
def document_folder_create(request):
    if request.org is None:
        messages.error(request, "Ingen aktiv organisation vald.")
        return redirect("portal:document_overview")

    org = request.org
    name = (request.POST.get("name") or "").strip()
    parent_id = (request.POST.get("parent_id") or "").strip()

    if not name:
        messages.error(request, "Ange ett mappnamn.")
        return redirect(_archive_redirect_url_for_post(request, org, parent_id))

    if len(name) > 255:
        messages.error(request, "Mappnamnet får vara högst 255 tecken.")
        return redirect(_archive_redirect_url_for_post(request, org, parent_id))

    parent = None
    if parent_id:
        parent = get_object_or_404(DocumentFolder, pk=parent_id, org=org)
    else:
        parent = (
            DocumentFolder.objects.filter(
                org=org,
                system_key="archive",
                is_system_folder=True,
            )
            .first()
        )

    duplicate_exists = DocumentFolder.objects.filter(
        org=org,
        parent=parent,
        name=name,
        is_system_folder=False,
    ).exists()
    if duplicate_exists:
        messages.error(request, "Det finns redan en mapp med det namnet på den här platsen.")
        return redirect(_archive_redirect_url(parent))

    try:
        DocumentFolder.objects.create(
            org=org,
            name=name,
            parent=parent,
            created_by=request.user,
            is_system_folder=False,
            folder_type=DocumentFolderType.CUSTOM,
            system_key="",
        )
    except IntegrityError:
        messages.error(request, "Det finns redan en mapp med det namnet på den här platsen.")
        return redirect(_archive_redirect_url(parent))

    messages.success(request, "Mappen skapades.")
    return redirect(_archive_redirect_url(parent))


def _archive_redirect_url_for_post(request, org, parent_id):
    """Redirect target when validation fails before parent is resolved."""
    if parent_id:
        parent = DocumentFolder.objects.filter(pk=parent_id, org=org).first()
        if parent:
            return _archive_redirect_url(parent)
    archive_root = DocumentFolder.objects.filter(
        org=org,
        system_key="archive",
        is_system_folder=True,
    ).first()
    return _archive_redirect_url(archive_root)


@login_required
def document_list(request):
    return redirect("portal:document_overview")


@login_required
def document_upload(request):
    if request.org is None:
        messages.error(request, "Ingen aktiv organisation vald.")
        return redirect("portal:document_overview")

    org = request.org

    target_folder = None
    target_folder_path_label = None
    workspace_mode = False
    target_context = None

    if request.method == "POST":
        workspace_mode = request.POST.get("workspace") == "1"
        post_folder_raw = request.POST.get("folder")

        if workspace_mode:
            target_folder, target_folder_path_label = (
                _resolve_workspace_upload_target_folder(org, post_folder_raw)
            )
        elif post_folder_raw:
            target_folder, target_folder_path_label = _resolve_upload_target_folder(
                org, post_folder_raw
            )

        form = DocumentCreateForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded_file = form.cleaned_data["file"]

            document = form.save(commit=False)
            document.org = org
            document.uploaded_by = request.user
            document.source_type = DocumentSourceType.UPLOADED
            if workspace_mode:
                document.folder = target_folder
                document.folder_auto_assigned = False
            elif target_folder:
                document.folder = target_folder
                document.folder_auto_assigned = False
            document.save()

            DocumentVersion.objects.create(
                document=document,
                version_number=1,
                file=uploaded_file,
                uploaded_by=request.user,
            )

            log_document_activity(
                document=document,
                user=request.user,
                action="created",
                message="Dokument skapades",
            )

            messages.success(request, "Dokumentet har laddats upp.")
            if workspace_mode:
                return redirect(
                    f"{reverse('portal:document_workspace')}?folder={target_folder.pk}"
                )
            if target_folder:
                return redirect(
                    f"{reverse('portal:document_archive')}?folder={target_folder.pk}"
                )
            return redirect("portal:document_overview")
    else:
        workspace_mode = request.GET.get("workspace") == "1"
        get_folder_raw = request.GET.get("folder")

        if workspace_mode:
            target_folder, target_folder_path_label = (
                _resolve_workspace_upload_target_folder(org, get_folder_raw)
            )
            target_context = "workspace"
        elif get_folder_raw:
            target_folder, target_folder_path_label = _resolve_upload_target_folder(
                org, get_folder_raw
            )
            target_context = "archive"
        form = DocumentCreateForm()

    return render(
        request,
        "portal/document_upload.html",
        {
            "form": form,
            "target_folder": target_folder,
            "target_folder_path_label": target_folder_path_label,
            "workspace_mode": workspace_mode,
            "target_context": target_context,
        },
    )


@login_required
def document_upload_version(request, pk):
    org = request.org

    document = get_object_or_404(
        Document.objects.filter(org=org, is_deleted=False),
        pk=pk,
    )

    current_version = document.current_version
    next_version_number = 1 if current_version is None else current_version.version_number + 1

    if request.method == "POST":
        form = DocumentVersionForm(request.POST, request.FILES)
        if form.is_valid():
            version = form.save(commit=False)
            version.document = document
            version.version_number = next_version_number
            version.uploaded_by = request.user
            version.save()

            log_document_activity(
                document=document,
                user=request.user,
                action="version_created",
                message=f"Ny version (v{next_version_number}) laddades upp",
            )

            messages.success(request, f"Ny version (v{next_version_number}) har laddats upp.")
            return redirect("portal:document_detail", pk=document.pk)
    else:
        form = DocumentVersionForm()

    return render(
        request,
        "portal/document_upload_version.html",
        {
            "document": document,
            "form": form,
            "next_version_number": next_version_number,
        },
    )


@login_required
def document_detail(request, pk):
    org = request.org

    doc = get_object_or_404(
        Document.objects.filter(org=org, is_deleted=False).prefetch_related("versions"),
        pk=pk,
    )

    activities = doc.activities.select_related("user").order_by("-created_at")
    current_version = doc.current_version

    if not current_version:
        preview_type = "other"
    else:
        ext = os.path.splitext(current_version.file.name)[1].lower()

        if ext == ".pdf":
            preview_type = "pdf"
        elif ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"]:
            preview_type = "image"
        else:
            preview_type = "other"

    return render(
        request,
        "portal/document_detail.html",
        {
            "doc": doc,
            "current_version": current_version,
            "preview_type": preview_type,
            "versions": doc.versions.all(),
            "activities": activities,
        },
    )


@login_required
def document_edit(request, pk):
    org = request.org

    document = get_object_or_404(
        Document.objects.filter(org=org, is_deleted=False),
        pk=pk,
    )

    if document.workflow_status != DocumentWorkflowStatus.DRAFT:
        messages.error(request, "Dokumentet kan inte redigeras eftersom det inte längre är i utkastläge.")
        return redirect("portal:document_detail", pk=document.pk)

    if request.method == "POST":
        form = DocumentUpdateForm(request.POST, instance=document)
        if form.is_valid():
            form.save()

            log_document_activity(
                document=document,
                user=request.user,
                action="updated",
                message="Dokument uppdaterades",
            )

            messages.success(request, "Dokumentet har uppdaterats.")
            return redirect("portal:document_detail", pk=document.pk)
    else:
        form = DocumentUpdateForm(instance=document)

    return render(
        request,
        "portal/document_edit.html",
        {
            "document": document,
            "form": form,
        },
    )


@login_required
def document_delete(request, pk):
    org = request.org

    document = get_object_or_404(
        Document.objects.filter(org=org, is_deleted=False),
        pk=pk,
    )

    if request.method == "POST":
        document.is_deleted = True
        document.deleted_at = timezone.now()
        document.deleted_by = request.user
        document.save(update_fields=["is_deleted", "deleted_at", "deleted_by", "updated_at"])

        log_document_activity(
            document=document,
            user=request.user,
            action="deleted",
            message=f"Dokumentet '{document.title}' markerades som borttaget",
        )

        messages.success(request, f"Dokumentet '{document.title}' har tagits bort.")
        return redirect("portal:document_overview")

    return render(
        request,
        "portal/document_confirm_delete.html",
        {
            "document": document,
        },
    )


@login_required
def document_trash(request):
    org = request.org

    qs = Document.objects.filter(org=org, is_deleted=True).order_by("-deleted_at")

    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(title__icontains=q)

    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "portal/document_trash.html",
        {
            "page_obj": page_obj,
            "q": q,
        },
    )


@login_required
def document_restore(request, pk):
    org = request.org

    document = get_object_or_404(
        Document.objects.filter(org=org, is_deleted=True),
        pk=pk,
    )

    if request.method == "POST":
        document.is_deleted = False
        document.deleted_at = None
        document.deleted_by = None
        document.save(update_fields=["is_deleted", "deleted_at", "deleted_by", "updated_at"])

        log_document_activity(
            document=document,
            user=request.user,
            action="restored",
            message=f"Dokumentet '{document.title}' återställdes",
        )

        messages.success(request, f"Dokumentet '{document.title}' har återställts.")
        return redirect("portal:document_trash")

    return render(
        request,
        "portal/document_confirm_restore.html",
        {
            "document": document,
        },
    )


DOCUMENT_CATEGORIES = [
    {"key": "protocol", "label": "Protokoll", "icon": "bi-folder"},
    {"key": "bylaws", "label": "Stadgar", "icon": "bi-folder"},
    {"key": "notice", "label": "Kallelser", "icon": "bi-folder"},
    {"key": "motion", "label": "Motioner", "icon": "bi-folder"},
    {"key": "decision", "label": "Beslut", "icon": "bi-folder"},
    {"key": "other", "label": "Övrigt", "icon": "bi-folder"},
]


@login_required
def document_folder_list(request):
    org = request.org

    folder_data = []
    for category in DOCUMENT_CATEGORIES:
        count = Document.objects.filter(
            org=org,
            category=category["key"],
            is_deleted=False,
        ).count()

        folder_data.append({
            "key": category["key"],
            "label": category["label"],
            "icon": category["icon"],
            "count": count,
        })

    return render(
        request,
        "portal/documents/folder_list.html",
        {"folders": folder_data},
    )


@login_required
def template_list(request):
    templates = DocumentTemplate.objects.all()

    return render(
        request,
        "portal/documents/template_list.html",
        {"templates": templates},
    )


@login_required
def create_from_template(request, template_id):
    template = get_object_or_404(DocumentTemplate, id=template_id)

    # 🔥 Välj rätt form baserat på kategori
    FormClass = get_template_form(template)

    if request.method == "POST":
        form = FormClass(request.POST)
        if form.is_valid():

            # 🔥 Tillfällig: använd gamla rendern (funkar för protocol)
            content = generate_document_content(template, form.cleaned_data)

            document = Document.objects.create(
                org=request.org,
                title=form.cleaned_data["title"],
                category=template.category,
                description="Skapat från mall",
                content=content,
                template=template,
                source_type=DocumentSourceType.TEMPLATE,
                uploaded_by=request.user,
            )

            log_document_activity(
                document=document,
                user=request.user,
                action="created",
                message=f"Dokument skapades från mallen '{template.name}'",
            )

            messages.success(request, f"Dokumentet '{document.title}' skapades från mall.")
            return redirect("portal:document_detail", pk=document.pk)
    else:
        form = FormClass(
            initial={
                "title": template.name,
            }
        )

    return render(
        request,
        "portal/documents/create_from_template.html",
        {
            "template": template,
            "form": form,
        },
    )


@login_required
def document_print_view(request, pk):
    doc = get_object_or_404(
        Document.objects.filter(org=request.org, is_deleted=False)
        .prefetch_related("signatures__user"),
        pk=pk,
    )

    chair_signatures = doc.signatures.filter(role="chair", status="signed")
    secretary_signatures = doc.signatures.filter(role="secretary", status="signed")
    adjuster_signatures = doc.signatures.filter(role="adjuster", status="signed")

    verification_url = ""
    if doc.document_hash:
        verification_url = request.build_absolute_uri(
            reverse("portal:verify_document", args=[doc.document_hash])
        )

    qr_code = None

    if verification_url:
        qr = qrcode.make(verification_url)
        buffer = BytesIO()
        qr.save(buffer, format="PNG")
        qr_code = base64.b64encode(buffer.getvalue()).decode()

    return render(
        request,
        "portal/documents/document_print.html",
        {
            "doc": doc,
            "org": request.org,
            "chair_signatures": chair_signatures,
            "secretary_signatures": secretary_signatures,
            "adjuster_signatures": adjuster_signatures,
            "verification_url": verification_url,
            "qr_code": qr_code,
        },
    )


def verify_document(request, document_hash):
    document = (
        Document.objects.filter(
            document_hash=document_hash,
            is_deleted=False,
            is_archived=True,
            workflow_status=DocumentWorkflowStatus.FINALIZED,
        )
        .select_related("org")
        .prefetch_related("signatures__user")
        .first()
    )

    return render(
        request,
        "portal/documents/document_verify.html",
        {
            "document": document,
            "document_hash": document_hash,
        },
    )


def get_template_form(template):
    if template.category == "protocol":
        return TemplateDocumentCreateForm
    elif template.category == "notice":
        return NoticeTemplateForm
    elif template.category == "decision":
        return DecisionTemplateForm
    elif template.category == "motion":
        return MotionTemplateForm
    elif template.category == "meeting":
        return MeetingProtocolForm
    return TemplateDocumentCreateForm


@login_required
def create_blank_document(request):
    if request.org is None:
        messages.error(request, "Ingen aktiv organisation vald.")
        return redirect("portal:document_overview")

    org = request.org
    target_folder = None
    target_folder_path_label = None
    workspace_mode = False

    if request.method == "POST":
        workspace_mode = request.POST.get("workspace") == "1"
        post_folder_raw = request.POST.get("folder")

        if workspace_mode:
            target_folder, target_folder_path_label = (
                _resolve_workspace_upload_target_folder(org, post_folder_raw)
            )

        form = DocumentUpdateForm(request.POST)
        if form.is_valid():
            document = form.save(commit=False)
            document.org = org
            document.source_type = DocumentSourceType.TEMPLATE
            document.uploaded_by = request.user
            if workspace_mode:
                document.folder = target_folder
                document.folder_auto_assigned = False
            document.save()

            log_document_activity(
                document=document,
                user=request.user,
                action="created",
                message="Tomt dokument skapades",
            )

            messages.success(request, f"Dokumentet '{document.title}' skapades.")
            return redirect("portal:document_edit", pk=document.pk)
    else:
        workspace_mode = request.GET.get("workspace") == "1"
        get_folder_raw = request.GET.get("folder")

        if workspace_mode:
            target_folder, target_folder_path_label = (
                _resolve_workspace_upload_target_folder(org, get_folder_raw)
            )

        form = DocumentUpdateForm(initial={
            "title": "Nytt dokument",
            "content": "<h1>Rubrik</h1><p>Börja skriva här...</p>",
        })

    return render(
        request,
        "portal/documents/create_blank_document.html",
        {
            "form": form,
            "workspace_mode": workspace_mode,
            "target_folder": target_folder,
            "target_folder_path_label": target_folder_path_label,
        },
    )


def group_documents_by_year_month(documents, date_attr="created_at"):
    grouped = OrderedDict()

    month_names = {
        1: "Januari",
        2: "Februari",
        3: "Mars",
        4: "April",
        5: "Maj",
        6: "Juni",
        7: "Juli",
        8: "Augusti",
        9: "September",
        10: "Oktober",
        11: "November",
        12: "December",
    }

    for doc in documents:
        dt = getattr(doc, date_attr, None)
        if not dt:
            continue

        year = dt.year
        month_number = dt.month
        month_label = month_names.get(month_number, str(month_number))

        if year not in grouped:
            grouped[year] = OrderedDict()

        if month_number not in grouped[year]:
            grouped[year][month_number] = {
                "label": month_label,
                "documents": [],
            }

        grouped[year][month_number]["documents"].append(doc)

    return grouped
