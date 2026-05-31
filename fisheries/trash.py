from django.utils import timezone

from .models import (
    ActionArea,
    ActionLog,
    Observation,
    ObservationLog,
)


def move_observation_to_trash(observation, org, user):
    if observation.deleted_at is not None:
        return False

    now = timezone.now()
    observation.deleted_at = now
    observation.deleted_by = user
    observation.is_active = False
    observation.updated_by = user
    observation.save(
        update_fields=[
            "deleted_at",
            "deleted_by",
            "is_active",
            "updated_by",
            "updated_at",
        ]
    )
    ObservationLog.objects.create(
        org=org,
        observation=observation,
        user=user,
        event_type="trashed",
        message="Flyttad till papperskorg",
    )
    return True


def restore_observation(observation, org, user):
    if observation.deleted_at is None:
        return False

    observation.deleted_at = None
    observation.deleted_by = None
    observation.is_active = True
    observation.updated_by = user
    observation.save(
        update_fields=[
            "deleted_at",
            "deleted_by",
            "is_active",
            "updated_by",
            "updated_at",
        ]
    )
    ObservationLog.objects.create(
        org=org,
        observation=observation,
        user=user,
        event_type="restored",
        message="Återställd från papperskorg",
    )
    return True


def purge_observation(observation):
    observation.delete()


def move_action_to_trash(action, org, user):
    if action.deleted_at is not None:
        return False

    now = timezone.now()
    action.deleted_at = now
    action.deleted_by = user
    action.is_active = False
    action.updated_by = user
    action.save(
        update_fields=[
            "deleted_at",
            "deleted_by",
            "is_active",
            "updated_by",
            "updated_at",
        ]
    )
    ActionLog.objects.create(
        org=org,
        action_area=action,
        user=user,
        event_type="trashed",
        message="Flyttad till papperskorg",
    )
    return True


def restore_action(action, org, user):
    if action.deleted_at is None:
        return False

    action.deleted_at = None
    action.deleted_by = None
    action.is_active = True
    action.updated_by = user
    action.save(
        update_fields=[
            "deleted_at",
            "deleted_by",
            "is_active",
            "updated_by",
            "updated_at",
        ]
    )
    ActionLog.objects.create(
        org=org,
        action_area=action,
        user=user,
        event_type="restored",
        message="Återställd från papperskorg",
    )
    return True


def purge_action(action):
    action.delete()


def move_all_to_trash(org, user):
    observation_count = 0
    action_count = 0

    for observation in Observation.objects.for_org(org).not_trashed():
        if move_observation_to_trash(observation, org, user):
            observation_count += 1

    for action in ActionArea.objects.for_org(org).not_trashed():
        if move_action_to_trash(action, org, user):
            action_count += 1

    return observation_count, action_count


def empty_trash(org):
    observation_count = Observation.objects.for_org(org).trashed_only().count()
    action_count = ActionArea.objects.for_org(org).trashed_only().count()

    Observation.objects.for_org(org).trashed_only().delete()
    ActionArea.objects.for_org(org).trashed_only().delete()

    return observation_count, action_count
