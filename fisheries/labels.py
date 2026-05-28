from .models import ActionPriority, ActionStatus, ObservationCategory, ObservationStatus

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

OBSERVATION_CATEGORY_LABELS = {
    ObservationCategory.FISH_STOCK: "Fiskbestånd",
    ObservationCategory.HABITAT: "Biotop & habitat",
    ObservationCategory.WATER_QUALITY: "Vattenkvalitet",
    ObservationCategory.ILLEGAL_FISHING: "Misstänkt tjuvfiske",
    ObservationCategory.INFRASTRUCTURE: "Anläggning & infrastruktur",
    ObservationCategory.FISH_DEATH: "Fiskdöd",
    ObservationCategory.ENVIRONMENT: "Miljö & nedskräpning",
    ObservationCategory.WATER_LEVEL: "Vattennivå / erosion",
    ObservationCategory.MEMBER_SUGGESTION: "Förslag från medlem",
    ObservationCategory.NEEDS_ACTION: "Behöver beslut",
    ObservationCategory.OTHER: "Övrigt",
}


def get_action_status_label(value):
    return ACTION_STATUS_LABELS.get(value, value)


def get_action_priority_label(value):
    return ACTION_PRIORITY_LABELS.get(value, value)


def get_observation_status_label(value):
    return OBSERVATION_STATUS_LABELS.get(value, value)


def get_observation_category_label(value):
    return OBSERVATION_CATEGORY_LABELS.get(value, value)
