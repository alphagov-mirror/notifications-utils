import math
from abc import ABC, abstractmethod
from os import path
from datetime import datetime, timedelta
from functools import lru_cache

from dateutil import parser
from jinja2 import Environment, FileSystemLoader
from flask import Markup
from html import unescape

from notifications_utils import LETTER_MAX_PAGE_COUNT, SMS_CHAR_COUNT_LIMIT
from notifications_utils.columns import Columns
from notifications_utils.field import Field, PlainTextField
from notifications_utils.formatters import (
    unlink_govuk_escaped,
    nl2br,
    add_prefix,
    autolink_sms,
    notify_email_markdown,
    notify_email_preheader_markdown,
    notify_plain_text_email_markdown,
    notify_letter_preview_markdown,
    sms_encode,
    escape_html,
    remove_whitespace_before_punctuation,
    make_quotes_smart,
    replace_hyphens_with_en_dashes,
    replace_hyphens_with_non_breaking_hyphens,
    strip_leading_whitespace,
    add_trailing_newline,
    normalise_whitespace,
    normalise_whitespace_and_newlines,
    normalise_multiple_newlines,
    remove_smart_quotes_from_email_addresses,
    strip_unsupported_characters,
    formatted_list,
)
from notifications_utils.countries.data import Postage
from notifications_utils.take import Take
from notifications_utils.template_change import TemplateChange
from notifications_utils.sanitise_text import SanitiseSMS


template_env = Environment(loader=FileSystemLoader(
    path.join(
        path.dirname(path.abspath(__file__)),
        'jinja_templates',
    )
))


class Template(ABC):

    encoding = "utf-8"

    def __init__(
        self,
        template,
        values=None,
        redact_missing_personalisation=False,
    ):
        if not isinstance(template, dict):
            raise TypeError('Template must be a dict')
        if values is not None and not isinstance(values, dict):
            raise TypeError('Values must be a dict')
        if template.get('template_type') != self.template_type:
            raise TypeError(
                f'Cannot initialise {self.__class__.__name__} '
                f'with {template.get("template_type")} template_type'
            )
        self.id = template.get("id", None)
        self.name = template.get("name", None)
        self.content = template["content"]
        self.values = values
        self._template = template
        self.redact_missing_personalisation = redact_missing_personalisation

    def __repr__(self):
        return "{}(\"{}\", {})".format(self.__class__.__name__, self.content, self.values)

    @abstractmethod
    def __str__(self):
        pass

    @property
    def content_with_placeholders_filled_in(self):
        return str(Field(
            self.content,
            self.values,
            html='passthrough',
            redact_missing_personalisation=self.redact_missing_personalisation,
            markdown_lists=True,
        )).strip()

    @property
    def values(self):
        if hasattr(self, '_values'):
            return self._values
        return {}

    @values.setter
    def values(self, value):
        if not value:
            self._values = {}
        else:
            placeholders = Columns.from_keys(self.placeholders)
            self._values = Columns(value).as_dict_with_keys(
                self.placeholders | set(
                    key for key in value.keys()
                    if Columns.make_key(key) not in placeholders.keys()
                )
            )

    @property
    def placeholders(self):
        return get_placeholders(self.content)

    @property
    def missing_data(self):
        return list(
            placeholder for placeholder in self.placeholders
            if self.values.get(placeholder) is None
        )

    @property
    def additional_data(self):
        return self.values.keys() - self.placeholders

    def get_raw(self, key, default=None):
        return self._template.get(key, default)

    def compare_to(self, new):
        return TemplateChange(self, new)

    @property
    def content_count(self):
        return len(self.content_with_placeholders_filled_in)

    def is_message_empty(self):

        if not self.content:
            return True

        if not self.content.startswith('((') or not self.content.endswith('))'):
            # If the content doesn’t start or end with a placeholder we
            # can guarantee it’s not empty, no matter what
            # personalisation has been provided.
            return False

        return self.content_count == 0

    def is_message_too_long(self):
        return False


class BaseSMSTemplate(Template):

    template_type = 'sms'

    def __init__(
        self,
        template,
        values=None,
        prefix=None,
        show_prefix=True,
        sender=None,
    ):
        self.prefix = prefix
        self.show_prefix = show_prefix
        self.sender = sender
        self._content_count = None
        super().__init__(template, values)

    @property
    def values(self):
        return super().values

    @values.setter
    def values(self, value):

        # If we change the values of the template it’s possible the
        # content count will have changed, so we need to reset the
        # cached count.
        if self._content_count is not None:
            self._content_count = None

        # Assigning to super().values doesn’t work here. We need to get
        # the property object instead, which has the special method
        # fset, which invokes the setter it as if we were
        # assigning to it outside this class.
        super(BaseSMSTemplate, type(self)).values.fset(self, value)

    @property
    def content_with_placeholders_filled_in(self):
        # We always call SMSMessageTemplate.__str__ regardless of
        # subclass, to avoid any HTML formatting. SMS templates differ
        # in that the content can include the service name as a prefix.
        # So historically we’ve returned the fully-formatted message,
        # rather than some plain-text represenation of the content. To
        # preserve compatibility for consumers of the API we maintain
        # that behaviour by overriding this method here.
        return SMSMessageTemplate.__str__(self)

    @property
    def prefix(self):
        return self._prefix if self.show_prefix else None

    @prefix.setter
    def prefix(self, value):
        self._prefix = value

    @property
    def content_count(self):
        """
        Return the number of characters in the message. Note that we don't distinguish between GSM and non-GSM
        characters at this point, as `get_sms_fragment_count` handles that separately.

        Also note that if values aren't provided, will calculate the raw length of the unsubstituted placeholders,
        as in the message `foo ((placeholder))` has a length of 19.
        """
        if self._content_count is None:
            self._content_count = len(SMSMessageTemplate._get_unsanitised_content(self))
        return self._content_count

    @property
    def content_count_without_prefix(self):
        # subtract 2 extra characters to account for the colon and the space,
        # added max zero in case the content is empty the __str__ methods strips the white space.
        if self.prefix:
            return max((self.content_count - len(self.prefix) - 2), 0)
        else:
            return self.content_count

    @property
    def fragment_count(self):
        content_with_placeholders = str(self)
        return get_sms_fragment_count(self.content_count, non_gsm_characters(content_with_placeholders))

    def is_message_too_long(self):
        """
        Message is validated with out the prefix.
        We have decided to be lenient and let the message go over the character limit. The SMS provider will
        send messages well over our limit. There were some inconsistencies with how we were validating the
        length of a message. This should be the method used anytime we want to reject a message for being too long.
        """
        return self.content_count_without_prefix > SMS_CHAR_COUNT_LIMIT

    def is_message_empty(self):
        return self.content_count_without_prefix == 0


class SMSMessageTemplate(BaseSMSTemplate):

    def __str__(self):
        return sms_encode(self._get_unsanitised_content())

    def _get_unsanitised_content(self):
        # This is faster to call than __str__ if all you need to know is
        # how many characters are in the message
        return Take(PlainTextField(
            self.content, self.values, html='passthrough'
        )).then(
            add_prefix, self.prefix
        ).then(
            remove_whitespace_before_punctuation
        ).then(
            normalise_whitespace_and_newlines
        ).then(
            normalise_multiple_newlines
        ).then(
            str.strip
        )


class SMSBodyPreviewTemplate(BaseSMSTemplate):

    def __init__(
        self,
        template,
        values=None,
    ):
        super().__init__(template, values, show_prefix=False)

    def __str__(self):

        return Markup(Take(Field(
            self.content,
            self.values,
            html='escape',
            redact_missing_personalisation=True,
        )).then(
            sms_encode
        ).then(
            remove_whitespace_before_punctuation
        ).then(
            normalise_whitespace_and_newlines
        ).then(
            normalise_multiple_newlines
        ).then(
            str.strip
        ))


class SMSPreviewTemplate(BaseSMSTemplate):

    jinja_template = template_env.get_template('sms_preview_template.jinja2')

    def __init__(
        self,
        template,
        values=None,
        prefix=None,
        show_prefix=True,
        sender=None,
        show_recipient=False,
        show_sender=False,
        downgrade_non_sms_characters=True,
        redact_missing_personalisation=False,
    ):
        self.show_recipient = show_recipient
        self.show_sender = show_sender
        self.downgrade_non_sms_characters = downgrade_non_sms_characters
        super().__init__(template, values, prefix, show_prefix, sender)
        self.redact_missing_personalisation = redact_missing_personalisation

    def __str__(self):

        return Markup(self.jinja_template.render({
            'sender': self.sender,
            'show_sender': self.show_sender,
            'recipient': Field('((phone number))', self.values, with_brackets=False, html='escape'),
            'show_recipient': self.show_recipient,
            'body': Take(Field(
                self.content,
                self.values,
                html='escape',
                redact_missing_personalisation=self.redact_missing_personalisation,
            )).then(
                add_prefix, (escape_html(self.prefix) or None) if self.show_prefix else None
            ).then(
                sms_encode if self.downgrade_non_sms_characters else str
            ).then(
                remove_whitespace_before_punctuation
            ).then(
                normalise_whitespace_and_newlines
            ).then(
                normalise_multiple_newlines
            ).then(
                nl2br
            ).then(
                autolink_sms
            )
        }))


class BaseBroadcastTemplate(BaseSMSTemplate):
    template_type = 'broadcast'


class BroadcastPreviewTemplate(BaseBroadcastTemplate, SMSPreviewTemplate):
    jinja_template = template_env.get_template('broadcast_preview_template.jinja2')


class BroadcastMessageTemplate(BaseBroadcastTemplate, SMSMessageTemplate):

    jinja_template = template_env.get_template('broadcast_message_template.jinja2')
    default_ttl_hours = 72

    def __init__(
        self,
        template,
        values=None,
        areas=[],
        polygons=[],
        identifier='',
        msg_type='Alert'
    ):
        super().__init__(template, values)

        self.areas = areas
        self._polygons = polygons

        self.sent = datetime.utcnow()
        self.expires = datetime.utcnow() + timedelta(hours=self.default_ttl_hours)
        self.notify_identifier = 'https://www.notifications.service.gov.uk/'
        self.identifier = identifier
        self.status = 'Actual'
        self.msg_type = 'Alert'
        self.scope = 'Public'
        self.category = 'Health'
        self.response_type = 'None'
        self.urgency = 'Immediate'
        self.severity = 'Extreme'
        self.certainty = 'Observed'
        self.previous_event_references = []

    @classmethod
    def from_event(cls, broadcast_event):
        """
        should be directly callable with the results of the BroadcastEvent.serialize() function from api/models.py
        """
        template_dict = {
            'template_type': 'broadcast',
            'content': broadcast_event['transmitted_content']['body']
        }
        obj = cls(
            template=template_dict,
            values=None,  # events have already done interpolation of any personalisation
            polygons=broadcast_event['polygons'],
            areas=broadcast_event['areas'],
            identifier=broadcast_event['id'],
        )
        obj.msg_type = broadcast_event['message_type'].title()
        obj.sent = parser.parse(broadcast_event['sent_at']).replace(tzinfo=None)
        obj.expires = parser.parse(broadcast_event['transmitted_finishes_at']).replace(tzinfo=None)
        obj.previous_event_references = broadcast_event['previous_event_references']
        return obj

    def __str__(self):

        properties = dict(self.__dict__)

        properties.update({
            'body': Take(Field(
                self.content.strip(),
                self.values,
                html='escape',
            )).then(
                sms_encode
            ).then(
                remove_whitespace_before_punctuation
            ).then(
                normalise_whitespace_and_newlines
            ).then(
                normalise_multiple_newlines
            ),
            'polygons': self.polygons,
            'sent': self.formatted_datetime_for('sent'),
            'expires': self.formatted_datetime_for('expires'),
            'references': self.previous_event_references,
        })

        return self.jinja_template.render(**properties)

    @property
    def polygons(self):
        return [
            ' '.join(
                f'{lat},{long}' for lat, long in polygon
            )
            for polygon in self._polygons
        ]

    @staticmethod
    def convert_naive_utc_datetime_to_cap_standard_string(dt):
        """
        As defined in section 3.3.2 of http://docs.oasis-open.org/emergency/cap/v1.2/CAP-v1.2-os.html.

        They define the standard "YYYY-MM-DDThh:mm:ssXzh:zm", where X is `+` if the timezone is > UTC, otherwise `-`.
        """
        return f"{dt.strftime('%Y-%m-%dT%H:%M:%S')}-00:00"

    def formatted_datetime_for(self, property_name):
        prop = getattr(self, property_name)
        return self.convert_naive_utc_datetime_to_cap_standard_string(prop)

    @property
    def reference(self):
        """
        The format looks like: f'{sender},{identifier},{sent}'

        this string can be used to refer to a broadcast in the `<references>` field of a future update or cancel.
        """
        return ','.join([
            self.notify_identifier,
            self.identifier,
            self.convert_naive_utc_datetime_to_cap_standard_string(self.sent)
        ])


class SubjectMixin():

    def __init__(
        self,
        template,
        values=None,
        **kwargs
    ):
        self._subject = template['subject']
        super().__init__(template, values, **kwargs)

    @property
    def subject(self):
        return Markup(Take(Field(
            self._subject,
            self.values,
            html='escape',
            redact_missing_personalisation=self.redact_missing_personalisation,
        )).then(
            do_nice_typography
        ).then(
            normalise_whitespace
        ))

    @property
    def placeholders(self):
        return get_placeholders(self._subject) | super().placeholders


class BaseEmailTemplate(SubjectMixin, Template):
    template_type = 'email'

    @property
    def html_body(self):
        return Take(Field(
            self.content,
            self.values,
            html='escape',
            markdown_lists=True,
            redact_missing_personalisation=self.redact_missing_personalisation,
        )).then(
            unlink_govuk_escaped
        ).then(
            strip_unsupported_characters
        ).then(
            add_trailing_newline
        ).then(
            notify_email_markdown
        ).then(
            do_nice_typography
        )


class PlainTextEmailTemplate(BaseEmailTemplate):

    def __str__(self):
        return Take(Field(
            self.content, self.values, html='passthrough', markdown_lists=True
        )).then(
            unlink_govuk_escaped
        ).then(
            strip_unsupported_characters
        ).then(
            add_trailing_newline
        ).then(
            notify_plain_text_email_markdown
        ).then(
            do_nice_typography
        ).then(
            unescape
        ).then(
            strip_leading_whitespace
        ).then(
            add_trailing_newline
        )

    @property
    def subject(self):
        return Markup(Take(Field(
            self._subject,
            self.values,
            html='passthrough',
            redact_missing_personalisation=self.redact_missing_personalisation
        )).then(
            do_nice_typography
        ).then(
            normalise_whitespace
        ))


class HTMLEmailTemplate(BaseEmailTemplate):

    jinja_template = template_env.get_template('email_template.jinja2')

    PREHEADER_LENGTH_IN_CHARACTERS = 256

    def __init__(
        self,
        template,
        values=None,
        govuk_banner=True,
        complete_html=True,
        brand_logo=None,
        brand_text=None,
        brand_colour=None,
        brand_banner=False,
        brand_name=None
    ):
        super().__init__(template, values)
        self.govuk_banner = govuk_banner
        self.complete_html = complete_html
        self.brand_logo = brand_logo
        self.brand_text = brand_text
        self.brand_colour = brand_colour
        self.brand_banner = brand_banner
        self.brand_name = brand_name

    @property
    def preheader(self):
        return " ".join(Take(Field(
            self.content,
            self.values,
            html='escape',
            markdown_lists=True,
        )).then(
            unlink_govuk_escaped
        ).then(
            strip_unsupported_characters
        ).then(
            add_trailing_newline
        ).then(
            notify_email_preheader_markdown
        ).then(
            do_nice_typography
        ).split())[:self.PREHEADER_LENGTH_IN_CHARACTERS].strip()

    def __str__(self):

        return self.jinja_template.render({
            'body': self.html_body,
            'preheader': self.preheader,
            'govuk_banner': self.govuk_banner,
            'complete_html': self.complete_html,
            'brand_logo': self.brand_logo,
            'brand_text': self.brand_text,
            'brand_colour': self.brand_colour,
            'brand_banner': self.brand_banner,
            'brand_name': self.brand_name
        })


class EmailPreviewTemplate(BaseEmailTemplate):

    jinja_template = template_env.get_template('email_preview_template.jinja2')

    def __init__(
        self,
        template,
        values=None,
        from_name=None,
        from_address=None,
        reply_to=None,
        show_recipient=True,
        redact_missing_personalisation=False,
    ):
        super().__init__(template, values, redact_missing_personalisation=redact_missing_personalisation)
        self.from_name = from_name
        self.from_address = from_address
        self.reply_to = reply_to
        self.show_recipient = show_recipient

    def __str__(self):
        return Markup(self.jinja_template.render({
            'body': self.html_body,
            'subject': self.subject,
            'from_name': escape_html(self.from_name),
            'from_address': self.from_address,
            'reply_to': self.reply_to,
            'recipient': Field("((email address))", self.values, with_brackets=False),
            'show_recipient': self.show_recipient
        }))

    @property
    def subject(self):
        return Take(Field(
            self._subject,
            self.values,
            html='escape',
            redact_missing_personalisation=self.redact_missing_personalisation
        )).then(
            do_nice_typography
        ).then(
            normalise_whitespace
        )


class BaseLetterTemplate(SubjectMixin, Template):

    template_type = 'letter'

    address_block = '\n'.join([
        '((address line 1))',
        '((address line 2))',
        '((address line 3))',
        '((address line 4))',
        '((address line 5))',
        '((address line 6))',
        '((postcode))',
    ])

    def __init__(
        self,
        template,
        values=None,
        contact_block=None,
        admin_base_url='http://localhost:6012',
        logo_file_name=None,
        redact_missing_personalisation=False,
        date=None,
    ):
        self.contact_block = (contact_block or '').strip()
        super().__init__(template, values, redact_missing_personalisation=redact_missing_personalisation)
        self.admin_base_url = admin_base_url
        self.logo_file_name = logo_file_name
        self.date = date or datetime.utcnow()

    @property
    def subject(self):
        return Take(Field(
            self._subject,
            self.values,
            redact_missing_personalisation=self.redact_missing_personalisation,
            html='escape',
        )).then(
            do_nice_typography
        ).then(
            normalise_whitespace
        )

    @property
    def placeholders(self):
        return get_placeholders(self.contact_block) | super().placeholders

    @property
    def _address_block(self):
        from notifications_utils.postal_address import PostalAddress

        postal_address = PostalAddress.from_personalisation(Columns(self.values))

        if postal_address.has_enough_lines and not postal_address.has_too_many_lines:
            return postal_address.normalised_lines

        return Field(
            self.address_block,
            self.values,
            html='escape',
            with_brackets=False,
        ).splitlines()

    @property
    def _contact_block(self):
        return Take(Field(
            '\n'.join(
                line.strip()
                for line in self.contact_block.split('\n')
            ),
            self.values,
            redact_missing_personalisation=self.redact_missing_personalisation,
            html='escape',
        )).then(
            remove_whitespace_before_punctuation
        ).then(
            nl2br
        )

    @property
    def _date(self):
        return self.date.strftime('%-d %B %Y')

    @property
    def _message(self):
        return Take(Field(
            self.content,
            self.values,
            html='escape',
            markdown_lists=True,
            redact_missing_personalisation=self.redact_missing_personalisation,
        )).then(
            add_trailing_newline
        ).then(
            notify_letter_preview_markdown
        ).then(
            do_nice_typography
        ).then(
            replace_hyphens_with_non_breaking_hyphens
        )


class LetterPreviewTemplate(BaseLetterTemplate):

    jinja_template = template_env.get_template('letter_pdf/preview.jinja2')

    def __str__(self):
        return Markup(self.jinja_template.render({
            'admin_base_url': self.admin_base_url,
            'logo_file_name': self.logo_file_name,
            # logo_class should only ever be None, svg or png
            'logo_class': self.logo_file_name.lower()[-3:] if self.logo_file_name else None,
            'subject': self.subject,
            'message': self._message,
            'address': self._address_block,
            'contact_block': self._contact_block,
            'date': self._date,
        }))


class LetterPrintTemplate(LetterPreviewTemplate):

    jinja_template = template_env.get_template('letter_pdf/print.jinja2')


class LetterImageTemplate(BaseLetterTemplate):

    jinja_template = template_env.get_template('letter_image_template.jinja2')
    first_page_number = 1
    allowed_postage_types = (
        Postage.FIRST,
        Postage.SECOND,
        Postage.EUROPE,
        Postage.REST_OF_WORLD,
    )

    def __init__(
        self,
        template,
        values=None,
        image_url=None,
        page_count=None,
        contact_block=None,
        postage=None,
    ):
        super().__init__(template, values, contact_block=contact_block)
        if not image_url:
            raise TypeError('image_url is required')
        if not page_count:
            raise TypeError('page_count is required')
        if postage not in [None] + list(self.allowed_postage_types):
            raise TypeError('postage must be None, {}'.format(formatted_list(
                self.allowed_postage_types,
                conjunction='or',
                before_each='\'',
                after_each='\'',
            )))
        self.image_url = image_url
        self.page_count = int(page_count)
        self.postage = postage

    @property
    def last_page_number(self):
        return min(self.page_count, LETTER_MAX_PAGE_COUNT) + self.first_page_number

    @property
    def page_numbers(self):
        return list(range(self.first_page_number, self.last_page_number))

    @property
    def postage_description(self):
        return {
            Postage.FIRST: 'first class',
            Postage.SECOND: 'second class',
            Postage.EUROPE: 'international',
            Postage.REST_OF_WORLD: 'international',
        }.get(self.postage)

    @property
    def postage_class_value(self):
        return {
            Postage.FIRST: 'letter-postage-first',
            Postage.SECOND: 'letter-postage-second',
            Postage.EUROPE: 'letter-postage-international',
            Postage.REST_OF_WORLD: 'letter-postage-international',
        }.get(self.postage)

    def __str__(self):
        return Markup(self.jinja_template.render({
            'image_url': self.image_url,
            'page_numbers': self.page_numbers,
            'address': self._address_block,
            'contact_block': self._contact_block,
            'date': self._date,
            'subject': self.subject,
            'message': self._message,
            'show_postage': bool(self.postage),
            'postage_description': self.postage_description,
            'postage_class_value': self.postage_class_value,
        }))


def get_sms_fragment_count(character_count, non_gsm_characters):
    if non_gsm_characters:
        return 1 if character_count <= 70 else math.ceil(float(character_count) / 67)
    else:
        return 1 if character_count <= 160 else math.ceil(float(character_count) / 153)


def non_gsm_characters(content):
    """
    Returns a set of all the non gsm characters in a text. this doesn't include characters that we will downgrade (eg
    emoji, ellipsis, ñ, etc). This only includes welsh non gsm characters that will force the entire SMS to be encoded
    with UCS-2.
    """
    return set(content) & set(SanitiseSMS.WELSH_NON_GSM_CHARACTERS)


def do_nice_typography(value):
    return Take(
        value
    ).then(
        remove_whitespace_before_punctuation
    ).then(
        make_quotes_smart
    ).then(
        remove_smart_quotes_from_email_addresses
    ).then(
        replace_hyphens_with_en_dashes
    )


@lru_cache(maxsize=1024)
def get_placeholders(content):
    return Field(content).placeholders
