from django import forms
from .models import BoardMembership, BoardMatter, Meeting


class BoardMembershipForm(forms.ModelForm):
    class Meta:
        model = BoardMembership
        fields = [
            "user",
            "role",
            "is_active",
            "can_manage_members",
            "can_manage_matters",
            "can_manage_documents",
        ]
        widgets = {
            "user": forms.Select(attrs={"class": "form-select"}),
            "role": forms.Select(attrs={"class": "form-select"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "can_manage_members": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "can_manage_matters": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "can_manage_documents": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class BoardMatterForm(forms.ModelForm):
    class Meta:
        model = BoardMatter
        fields = [
            "title",
            "description",
            "type",
            "status",
            "assigned_to",
            "board_comment",
            "prepared_statement",
            "ready_for_meeting",
        ]
        widgets = {
            "title": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Ange titel",
            }),
            "description": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "Beskriv ärendet",
            }),
            "type": forms.Select(attrs={"class": "form-select"}),
            "status": forms.Select(attrs={"class": "form-select"}),
            "assigned_to": forms.Select(attrs={"class": "form-select"}),
            "board_comment": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "Intern kommentar från styrelsen",
            }),
            "prepared_statement": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 5,
                "placeholder": "Beredning / styrelsens yttrande",
            }),
            "ready_for_meeting": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class MeetingForm(forms.ModelForm):
    matters = forms.ModelMultipleChoiceField(
        queryset=BoardMatter.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Ärenden till stämman",
        help_text="Välj vilka ärenden som ska kopplas till denna stämma.",
    )

    previous_matters = forms.ModelMultipleChoiceField(
        queryset=BoardMatter.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Tidigare upptagna ärenden",
        help_text="Valfritt: välj tidigare upptagna ärenden som ska användas igen.",
    )

    class Meta:
        model = Meeting
        fields = ["title", "location", "meeting_type", "meeting_date"]
        widgets = {
            "title": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Ange titel för stämman",
            }),
            "location": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Ange plats för stämman",
            }),
            "meeting_type": forms.Select(attrs={"class": "form-select"}),
            "meeting_date": forms.DateTimeInput(attrs={
                "class": "form-control",
                "type": "datetime-local",
            }),
        }

    def __init__(self, *args, **kwargs):
        org = kwargs.pop("org", None)
        super().__init__(*args, **kwargs)

        if org is not None:
            self.fields["matters"].queryset = BoardMatter.objects.filter(
                org=org,
                ready_for_meeting=True,
            ).exclude(
                meeting_links__isnull=False,
            ).distinct().order_by("created_at")

            self.fields["previous_matters"].queryset = BoardMatter.objects.filter(
                org=org,
                ready_for_meeting=True,
                meeting_links__isnull=False,
            ).distinct().order_by("created_at")