from django import forms
from .models import Document, DocumentVersion


class DocumentCreateForm(forms.ModelForm):
    file = forms.FileField(
        widget=forms.ClearableFileInput(attrs={"class": "form-control"})
    )

    class Meta:
        model = Document
        fields = ["title", "category", "description"]
        widgets = {
            "title": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Ange dokumenttitel",
            }),
            "category": forms.Select(attrs={
                "class": "form-select",
            }),
            "description": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "Kort beskrivning av dokumentet",
            }),
        }


class DocumentVersionForm(forms.ModelForm):
    class Meta:
        model = DocumentVersion
        fields = ["file", "notes"]
        widgets = {
            "file": forms.ClearableFileInput(attrs={
                "class": "form-control",
            }),
            "notes": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Beskriv vad som ändrats i denna version",
            }),
        }


class DocumentUpdateForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = ["title", "category", "description", "content"]
        widgets = {
            "title": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Ange dokumenttitel",
            }),
            "category": forms.Select(attrs={
                "class": "form-select",
            }),
            "description": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "Kort beskrivning av dokumentet",
            }),
            "content": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 20,
                "placeholder": "Skriv dokumentinnehåll här...",
                "id": "id_content",
            }),
        }


class TemplateDocumentCreateForm(forms.Form):
    title = forms.CharField(
        label="Dokumenttitel",
        max_length=255,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Ange dokumenttitel",
        }),
    )
    date = forms.DateField(
        label="Datum",
        widget=forms.DateInput(attrs={
            "class": "form-control",
            "type": "date",
        }),
    )
    time = forms.TimeField(
        label="Tid",
        widget=forms.TimeInput(attrs={
            "class": "form-control",
            "type": "time",
        }),
    )
    location = forms.CharField(
        label="Plats",
        max_length=255,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Ange plats",
        }),
    )
    attendees = forms.CharField(
        label="Närvarande",
        required=False,
        widget=forms.Textarea(attrs={
            "class": "form-control",
            "rows": 5,
            "placeholder": "En person per rad",
        }),
        help_text="Skriv en person per rad.",
    )


class NoticeTemplateForm(forms.Form):
    title = forms.CharField(max_length=255, widget=forms.TextInput(attrs={"class": "form-control"}))

    date = forms.DateField(widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}))
    time = forms.TimeField(widget=forms.TimeInput(attrs={"class": "form-control", "type": "time"}))
    location = forms.CharField(max_length=255, widget=forms.TextInput(attrs={"class": "form-control"}))

    agenda = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            "class": "form-control",
            "rows": 6,
            "placeholder": "En punkt per rad",
        })
    )


class DecisionTemplateForm(forms.Form):
    title = forms.CharField(max_length=255, widget=forms.TextInput(attrs={"class": "form-control"}))

    subject = forms.CharField(
        label="Ärende",
        widget=forms.TextInput(attrs={"class": "form-control"})
    )

    background = forms.CharField(
        label="Bakgrund",
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 4})
    )

    decision = forms.CharField(
        label="Beslut",
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 4})
    )


class MotionTemplateForm(forms.Form):
    title = forms.CharField(max_length=255, widget=forms.TextInput(attrs={"class": "form-control"}))

    proposal = forms.CharField(
        label="Förslag",
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 4})
    )

    motivation = forms.CharField(
        label="Motivering",
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 4})
    )