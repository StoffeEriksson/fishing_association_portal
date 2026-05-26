import os
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Sum, Count
from django.db import IntegrityError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.http import Http404, HttpResponse
from django.template.loader import render_to_string
from django.urls import reverse
from collections import OrderedDict
from django.utils.translation import gettext_lazy as _
import qrcode
from io import BytesIO
import base64

from calendarapp.calendar_widget import build_dashboard_calendar_widget
from calendarapp.models import CalendarEvent
from fisheries.models import ActionArea, ActionPriority, ActionStatus
from fishingrights.models import FishingRightShare, Property
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
        ActionArea.objects.filter(org=org, is_active=True)
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
        due = item.get("due_at")
        pr = item.get("priority") or "normal"
        pr_i = priority_rank.get(pr, 4)
        created = item["created_at"]
        created_ts = created.timestamp() if hasattr(created, "timestamp") else 0

        if due:
            due_ord = due.toordinal()
            if due < today:
                return (0, due_ord, pr_i, created_ts)
            return (1, due_ord, pr_i, created_ts)
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
            "upcoming_meetings_count": upcoming_meetings_count,
            "news_feed": news_feed,
            "calendar_widget": calendar_widget,
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

    folders = [
        f for f in workspace_folders
        if current_folder is not None and f.parent_id == current_folder.pk
    ]
    folders.sort(key=lambda f: (f.folder_type, f.name.lower(), f.pk))

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

    for f in folders:
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
        tree_children_by_parent[pid].sort(
            key=lambda f: (f.folder_type, f.name.lower(), f.pk)
        )

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

    if request.method == "POST":
        post_folder_raw = request.POST.get("folder")
        if post_folder_raw:
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
            if target_folder:
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
            if target_folder:
                return redirect(
                    f"{reverse('portal:document_archive')}?folder={target_folder.pk}"
                )
            return redirect("portal:document_overview")
    else:
        get_folder_raw = request.GET.get("folder")
        if get_folder_raw:
            target_folder, target_folder_path_label = _resolve_upload_target_folder(
                org, get_folder_raw
            )
        form = DocumentCreateForm()

    return render(
        request,
        "portal/document_upload.html",
        {
            "form": form,
            "target_folder": target_folder,
            "target_folder_path_label": target_folder_path_label,
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
    if request.method == "POST":
        form = DocumentUpdateForm(request.POST)
        if form.is_valid():
            document = form.save(commit=False)
            document.org = request.org
            document.source_type = DocumentSourceType.TEMPLATE
            document.uploaded_by = request.user
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
        form = DocumentUpdateForm(initial={
            "title": "Nytt dokument",
            "content": "<h1>Rubrik</h1><p>Börja skriva här...</p>",
        })

    return render(
        request,
        "portal/documents/create_blank_document.html",
        {"form": form},
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
