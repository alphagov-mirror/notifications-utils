class NotificationStatus(str):
    __slots__ = [
        'name',  # status name
        'failure',  # does the status indicate a failure to deliver the notification?
        'notification_types',  # which notification_types does the status apply to?
        'billable',  # should the user be billed for this notification?
        'to',  # which statuses can be transitioned to from this status?
        'final',  # status is final if it doesn't have any 'to' transitions
        'aliases',  # additional status names used for filtering (e.g. "failed")
    ]

    def __new__(cls, name, *, failure, to, notification_types, aliases=None, final=None, billable):
        self = str.__new__(cls, name)
        attributes = {
            'name': name,
            'failure': failure,
            'notification_types': frozenset(notification_types),
            'aliases': frozenset((aliases or []) + [name]),
            'billable': billable,
            'to': to,
            'final': not to if final is None else final,
        }

        for k, v in attributes.items():
            object.__setattr__(self, k, v)

        return self

    @property
    def success(self):
        return (self.failure is False) and (self.final is True) and (self.billable is True)

    def __setattr__(self, key, value):
        raise AttributeError("Status attributes are immutable")


ALL = [
    NotificationStatus(
        'cancelled',
        to=[],
        notification_types=['letter'],
        failure=False, billable=False,
    ),

    NotificationStatus(
        'created',
        to=[
            'pending',
            'pending-virus-check',
            'sending',
            'sent',
        ],
        notification_types=['email', 'sms', 'letter'],
        aliases=['accepted'],
        failure=False, billable=False,
    ),

    NotificationStatus(
        'sending',
        to=[
            'sent',
            'delivered',
            'technical-failure', 'temporary-failure', 'permanent-failure',
            'returned-letter',
            'cancelled',
        ],
        notification_types=['email', 'sms', 'letter'],
        # api_display_name={
        #     'letter': 'accepted',
        # },
        aliases=['accepted'],
        failure=False, billable=True,
    ),

    NotificationStatus(
        'sent',  # international sms
        to=[
            'delivered',
        ],
        final=True,
        notification_types=['sms'],
        failure=False, billable=True,
    ),

    NotificationStatus(
        'delivered',
        to=[],
        notification_types=['email', 'sms', 'letter'],
        aliases=['received'],
        failure=False, billable=True,
    ),
    NotificationStatus(
        'pending',
        to=['    WIP     '],
        notification_types=['sms'],
        failure=False, billable=False,
    ),

    # TODO failed is deprecated as a status and should
    # be removed from DB and API tests. It's still used
    # as an alias for filters
    NotificationStatus(
        'failed',
        to=[],
        notification_types=['email', 'sms'],
        failure=True, billable=True,
    ),

    NotificationStatus(
        'technical-failure',
        to=[],
        notification_types=['email', 'sms', 'letter'],
        aliases=['failed'],
        failure=True, billable=False,
    ),
    NotificationStatus(
        'temporary-failure',
        to=[],
        notification_types=['email', 'sms'],
        aliases=['failed'],
        failure=True, billable=True,
    ),
    NotificationStatus(
        'permanent-failure',
        to=[],
        notification_types=['email', 'sms'],
        aliases=['failed'],
        failure=True, billable=True,
    ),
    NotificationStatus(
        'pending-virus-check',
        to=['    WIP     '],
        notification_types=['letter'],
        failure=False, billable=False,
    ),
    NotificationStatus(
        'validation-failed',
        to=[],
        notification_types=['letter'],
        aliases=['failed'],
        failure=True, billable=False,
    ),
    NotificationStatus(
        'virus-scan-failed',
        to=[],
        notification_types=['letter'],
        aliases=['failed'],
        failure=True, billable=False,
    ),
    NotificationStatus(
        'returned-letter',
        to=[],
        notification_types=['letter'],
        aliases=['failed'],
        failure=True, billable=True,
    ),
]

_ALL_DICT = {n.name: n for n in ALL}


def get_status(name):
    # Status column is nullable
    if name is None:
        return None
    return _ALL_DICT[name]


def get_status_list(*, notification_type=None, names=None, **kwargs):
    # TODO some uses of Notification.substitute_status pass in a
    # string instead of a list
    if isinstance(names, str):
        names = set([names])
    elif names is not None:
        names = set(names)

    return [
        s for s in ALL
        if all(getattr(s, k) == v for k, v in kwargs.items())
        and (notification_type is None or notification_type in s.notification_types)
        and (names is None or names & s.aliases)
    ]
