from django import forms
from .models import BoardMembership, BoardMatter


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
