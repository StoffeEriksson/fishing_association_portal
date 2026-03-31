import os

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.http import HttpResponse
from django.template.loader import render_to_string

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

    recent_documents = Document.objects.filter(
        org=org,
        is_deleted=False,
    ).order_by("-updated_at")[:5]

    recent_activities = DocumentActivity.objects.filter(
        document__org=org
    ).select_related("document", "user").order_by("-created_at")[:5]

    return render(
        request,
        "portal/dashboard.html",
        {
            "recent_documents": recent_documents,
            "recent_activities": recent_activities,
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
def document_list(request):
    org = request.org

    qs = Document.objects.filter(org=org, is_deleted=False, is_archived=True)

    category = request.GET.get("category")
    if category:
        qs = qs.filter(category=category)

    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(title__icontains=q)

    qs = qs.order_by("-updated_at")

    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "portal/document_list.html",
        {
            "page_obj": page_obj,
            "q": q,
            "category": category,
        },
    )


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
            return redirect("portal:document_list")
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
        return redirect("portal:document_list")

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

    return render(
        request,
        "portal/documents/document_print.html",
        {
            "doc": doc,
            "org": request.org,
            "chair_signatures": chair_signatures,
            "secretary_signatures": secretary_signatures,
            "adjuster_signatures": adjuster_signatures,
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
