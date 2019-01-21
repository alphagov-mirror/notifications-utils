import pytest

from notifications_utils.notification_status import NotificationStatus


def test_can_create_a_status():
    s = NotificationStatus('created', failure=False, notification_types=['email'], to=[], billable=True)

    assert s.name == 'created'


def test_status_attributes_are_immutable():
    s = NotificationStatus('created', failure=False, notification_types=['email'], to=[], billable=True)

    with pytest.raises(AttributeError):
        s.name = 'new-created'


def test_final_is_set_from_to():
    s = NotificationStatus('delivered', failure=False, notification_types=['email'], to=[], billable=True)

    assert s.final

    s = NotificationStatus('created', failure=False, notification_types=['email'], to=['delivered'], billable=False)

    assert not s.final
