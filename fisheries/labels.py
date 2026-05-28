from .models import ActionPriority, ActionStatus, ObservationStatus

ACTION_STATUS_LABELS = {
    ActionStatus.URGENT: "Akut",
    ActionStatus.NEEDS_ACTION: "Behöver beslut",
    ActionStatus.PLANNED: "Planerad",
    ActionStatus.IN_PROGRESS: "Pågår",
    ActionStatus.COMPLETED: "Klar",
}

ACTION_PRIORITY_LABELS = {
    ActionPriority.LOW: "Låg",
    ActionPriority.MEDIUM: "Normal",
    ActionPriority.HIGH: "Hög",
    ActionPriority.CRITICAL: "Kritisk",
}

OBSERVATION_STATUS_LABELS = {
    ObservationStatus.NEW: "Ny",
    ObservationStatus.UNDER_REVIEW: "Under granskning",
    ObservationStatus.LINKED_TO_ACTION: "Kopplad till åtgärd",
    ObservationStatus.CLOSED: "Avslutad",
}


def get_action_status_label(value):
    return ACTION_STATUS_LABELS.get(value, value)


def get_action_priority_label(value):
    return ACTION_PRIORITY_LABELS.get(value, value)


def get_observation_status_label(value):
    return OBSERVATION_STATUS_LABELS.get(value, value)
