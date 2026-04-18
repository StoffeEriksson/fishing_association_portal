import os
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.urls import reverse
from collections import OrderedDict
from django.utils.translation import gettext_lazy as _
import qrcode
from io import BytesIO
import base64

from calendarapp.calendar_widget import build_dashboard_calendar_widget
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
    DocumentActivity,
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

    calendar_widget = build_dashboard_calendar_widget(org)

    return render(
        request,
        "portal/dashboard.html",
        {
            "recent_documents": recent_documents,
            "recent_activities": recent_activities,
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
    return render_document_collection(request, mode="workspace")


@login_required
def document_archive(request):
    return render_document_collection(request, mode="archive")


@login_required
def document_list(request):
    return redirect("portal:document_overview")


@login_required
def document_upload(request):
    org = request.org

    if request.method == "POST":
        form = DocumentCreateForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded_file = form.cleaned_data["file"]

            document = form.save(commit=False)
            document.org = org
            document.uploaded_by = request.user
            document.source_type = DocumentSourceType.UPLOADED
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
            return redirect("document_overview")
    else:
        form = DocumentCreateForm()

    return render(
        request,
        "portal/document_upload.html",
        {"form": form},
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
