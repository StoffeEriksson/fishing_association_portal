from django import forms
from governance.models import Meeting

from .models import CalendarEvent


class CalendarMeetingBookingForm(forms.Form):
    title = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    location = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    meeting_type = forms.ChoiceField(
        choices=Meeting.MEETING_TYPE_CHOICES,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    meeting_date = forms.DateTimeField(
        widget=forms.DateTimeInput(
            attrs={"class": "form-control", "type": "datetime-local"}
        )
    )


class CalendarEventForm(forms.ModelForm):
    class Meta:
        model = CalendarEvent
        fields = [
            "title",
            "description",
            "event_type",
            "start_at",
            "end_at",
            "location",
            "is_all_day",
        ]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
            "event_type": forms.Select(attrs={"class": "form-select"}),
            "start_at": forms.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"}
            ),
            "end_at": forms.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"}
            ),
            "location": forms.TextInput(attrs={"class": "form-control"}),
            "is_all_day": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
