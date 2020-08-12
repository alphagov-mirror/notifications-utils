import uuid
import datetime
from time import process_time
import os
import pytest

from bs4 import BeautifulSoup
from functools import partial
from unittest import mock
from flask import Markup
from freezegun import freeze_time
from orderedset import OrderedSet

from notifications_utils.formatters import unlink_govuk_escaped
from notifications_utils.template import (
    BaseEmailTemplate,
    BaseLetterTemplate,
    Template,
    HTMLEmailTemplate,
    LetterPreviewTemplate,
    LetterImageTemplate,
    PlainTextEmailTemplate,
    SMSBodyPreviewTemplate,
    SMSMessageTemplate,
    SMSPreviewTemplate,
    EmailPreviewTemplate,
    LetterPrintTemplate,
    SubjectMixin,
    BaseBroadcastTemplate,
    BroadcastMessageTemplate,
    BroadcastPreviewTemplate,
)

from tests.xml_schemas import validate_xml


@pytest.mark.parametrize('template_class, expected_error', (
    (Template, (
        "Can't instantiate abstract class Template with abstract methods __str__"
    )),
    (BaseEmailTemplate, (
        "Can't instantiate abstract class BaseEmailTemplate with abstract methods __str__"
    )),
    (BaseLetterTemplate, (
        "Can't instantiate abstract class BaseLetterTemplate with abstract methods __str__"
    )),
    (BaseBroadcastTemplate, (
        "Can't instantiate abstract class BaseBroadcastTemplate with abstract methods __str__"
    )),
))
def test_abstract_classes_cant_be_instantiated(template_class, expected_error):
    with pytest.raises(TypeError) as error:
        template_class({})
    assert str(error.value) == expected_error


@pytest.mark.parametrize('template_class, expected_error', (
    (HTMLEmailTemplate, (
        'Cannot initialise HTMLEmailTemplate with sms template_type'
    )),
    (LetterPreviewTemplate, (
        'Cannot initialise LetterPreviewTemplate with sms template_type'
    )),
    (BroadcastPreviewTemplate, (
        'Cannot initialise BroadcastPreviewTemplate with sms template_type'
    )),
))
def test_errors_for_incompatible_template_type(template_class, expected_error):
    with pytest.raises(TypeError) as error:
        template_class({'content': '', 'subject': '', 'template_type': 'sms'})
    assert str(error.value) == expected_error


def test_html_email_inserts_body():
    assert 'the &lt;em&gt;quick&lt;/em&gt; brown fox' in str(HTMLEmailTemplate(
        {'content': 'the <em>quick</em> brown fox', 'subject': '', 'template_type': 'email'}
    ))


@pytest.mark.parametrize(
    "content", ('DOCTYPE', 'html', 'body', 'GOV.UK', 'hello world')
)
def test_default_template(content):
    assert content in str(HTMLEmailTemplate({
        'content': 'hello world', 'subject': '', 'template_type': 'email',
    }))


@pytest.mark.parametrize(
    "show_banner", (True, False)
)
def test_govuk_banner(show_banner):
    email = HTMLEmailTemplate({
        'content': 'hello world', 'subject': '', 'template_type': 'email',
    })
    email.govuk_banner = show_banner
    if show_banner:
        assert "GOV.UK" in str(email)
    else:
        assert "GOV.UK" not in str(email)


def test_brand_banner_shows():
    email = str(HTMLEmailTemplate(
        {'content': 'hello world', 'subject': '', 'template_type': 'email'},
        brand_banner=True,
        govuk_banner=False
    ))
    assert (
        '<td width="10" height="10" valign="middle"></td>'
    ) not in email
    assert (
        'role="presentation" width="100%" style="border-collapse: collapse;min-width: 100%;width: 100% !important;"'
    ) in email


@pytest.mark.parametrize(
    "brand_logo, brand_text, brand_colour",
    [
        ('http://example.com/image.png', 'Example', 'red'),
        ('http://example.com/image.png', 'Example', '#f00'),
        ('http://example.com/image.png', 'Example', None),
        ('http://example.com/image.png', '', '#f00'),
        (None, 'Example', '#f00')
    ]
)
def test_brand_data_shows(brand_logo, brand_text, brand_colour):
    email = str(HTMLEmailTemplate(
        {'content': 'hello world', 'subject': '', 'template_type': 'email'},
        brand_banner=True,
        govuk_banner=False,
        brand_logo=brand_logo,
        brand_text=brand_text,
        brand_colour=brand_colour
    ))

    assert 'GOV.UK' not in email
    if brand_logo:
        assert brand_logo in email
    if brand_text:
        assert brand_text in email
    if brand_colour:
        assert 'bgcolor="{}"'.format(brand_colour) in email


def test_alt_text_with_brand_text_and_govuk_banner_shown():
    email = str(HTMLEmailTemplate(
        {'content': 'hello world', 'subject': '', 'template_type': 'email'},
        govuk_banner=True,
        brand_logo='http://example.com/image.png',
        brand_text='Example',
        brand_banner=True,
        brand_name='Notify Logo'
    ))
    assert 'alt=" "' in email
    assert 'alt="Notify Logo"' not in email


def test_alt_text_with_no_brand_text_and_govuk_banner_shown():
    email = str(HTMLEmailTemplate(
        {'content': 'hello world', 'subject': '', 'template_type': 'email'},
        govuk_banner=True,
        brand_logo='http://example.com/image.png',
        brand_text=None,
        brand_banner=True,
        brand_name='Notify Logo'
    ))
    assert 'alt=" "' in email
    assert 'alt="Notify Logo"' in email


@pytest.mark.parametrize('brand_banner, brand_text, expected_alt_text', [
    (True, None, 'alt="Notify Logo"'),
    (True, 'Example', 'alt=" "'),
    (False, 'Example', 'alt=" "'),
    (False, None, 'alt="Notify Logo"'),
])
def test_alt_text_with_no_govuk_banner(brand_banner, brand_text, expected_alt_text):
    email = str(HTMLEmailTemplate(
        {'content': 'hello world', 'subject': '', 'template_type': 'email'},
        govuk_banner=False,
        brand_logo='http://example.com/image.png',
        brand_text=brand_text,
        brand_banner=brand_banner,
        brand_name='Notify Logo'
    ))

    assert expected_alt_text in email


@pytest.mark.parametrize(
    "complete_html", (True, False)
)
@pytest.mark.parametrize(
    "branding_should_be_present, brand_logo, brand_text, brand_colour",
    [
        (True, 'http://example.com/image.png', 'Example', '#f00'),
        (True, 'http://example.com/image.png', 'Example', None),
        (True, 'http://example.com/image.png', '', None),
        (False, None, 'Example', '#f00'),
        (False, 'http://example.com/image.png', None, '#f00')
    ]
)
@pytest.mark.parametrize(
    "content", ('DOCTYPE', 'html', 'body')
)
def test_complete_html(complete_html, branding_should_be_present, brand_logo, brand_text, brand_colour, content):

    email = str(HTMLEmailTemplate(
        {'content': 'hello world', 'subject': '', 'template_type': 'email'},
        complete_html=complete_html,
        brand_logo=brand_logo,
        brand_text=brand_text,
        brand_colour=brand_colour,
    ))

    if complete_html:
        assert content in email
    else:
        assert content not in email

    if branding_should_be_present:
        assert brand_logo in email
        assert brand_text in email

        if brand_colour:
            assert brand_colour in email
            assert '##' not in email


def test_preheader_is_at_start_of_html_emails():
    assert (
        '<body style="font-family: Helvetica, Arial, sans-serif;font-size: 16px;margin: 0;color:#0b0c0c;">\n'
        '\n'
        '<span style="display: none;font-size: 1px;color: #fff; max-height: 0;">content…</span>'
    ) in str(
        HTMLEmailTemplate({
            'content': 'content', 'subject': 'subject', 'template_type': 'email'
        })
    )


@pytest.mark.parametrize('content, values, expected_preheader', [
    (
        (
            'Hello (( name ))\n'
            '\n'
            '# This - is a "heading"\n'
            '\n'
            'My favourite websites\' URLs are:\n'
            '- GOV.UK\n'
            '- https://www.example.com\n'
        ),
        {'name': 'Jo'},
        'Hello Jo This – is a “heading” My favourite websites’ URLs are: • GOV.​UK • https://www.example.com',
    ),
    (
        (
            '[Markdown link](https://www.example.com)\n'
        ),
        {},
        'Markdown link',
    ),
    (
        """
            Lorem Ipsum is simply dummy text of the printing and
            typesetting industry.

            Lorem Ipsum has been the industry’s standard dummy text
            ever since the 1500s, when an unknown printer took a galley
            of type and scrambled it to make a type specimen book.

            Lorem Ipsum is simply dummy text of the printing and
            typesetting industry.

            Lorem Ipsum has been the industry’s standard dummy text
            ever since the 1500s, when an unknown printer took a galley
            of type and scrambled it to make a type specimen book.
        """,
        {},
        (
            'Lorem Ipsum is simply dummy text of the printing and '
            'typesetting industry. Lorem Ipsum has been the industry’s '
            'standard dummy text ever since the 1500s, when an unknown '
            'printer took a galley of type and scrambled it to make a '
            'type specimen book. Lorem Ipsu'
        ),
    ),
    (
        'short email',
        {},
        'short email',
    ),
])
@mock.patch(
    'notifications_utils.template.HTMLEmailTemplate.jinja_template.render',
    return_value='mocked'
)
def test_content_of_preheader_in_html_emails(
    mock_jinja_template,
    content,
    values,
    expected_preheader,
):
    assert str(HTMLEmailTemplate(
        {'content': content, 'subject': 'subject', 'template_type': 'email'},
        values
    )) == 'mocked'
    assert mock_jinja_template.call_args[0][0]['preheader'] == expected_preheader


@pytest.mark.parametrize('template_class, template_type, extra_args, result, markdown_renderer', [
    [
        HTMLEmailTemplate,
        'email',
        {},
        (
            'the quick brown fox\n'
            '\n'
            'jumped over the lazy dog\n'
        ),
        'notifications_utils.template.notify_email_markdown',
    ],
    [
        LetterPreviewTemplate,
        'letter',
        {},
        (
            'the quick brown fox\n'
            '\n'
            'jumped over the lazy dog\n'
        ),
        'notifications_utils.template.notify_letter_preview_markdown'
    ],
])
def test_markdown_in_templates(
    template_class,
    template_type,
    extra_args,
    result,
    markdown_renderer,
):
    with mock.patch(markdown_renderer, return_value='') as mock_markdown_renderer:
        str(template_class(
            {
                "content": (
                    'the quick ((colour)) ((animal))\n'
                    '\n'
                    'jumped over the lazy dog'
                ),
                'subject': 'animal story',
                'template_type': template_type,
            },
            {'animal': 'fox', 'colour': 'brown'},
            **extra_args
        ))
    mock_markdown_renderer.assert_called_once_with(result)


@pytest.mark.parametrize(
    'template_class, template_type', [
        (HTMLEmailTemplate, 'email'),
        (EmailPreviewTemplate, 'email'),
        (SMSPreviewTemplate, 'sms'),
        (BroadcastPreviewTemplate, 'broadcast'),
        pytest.param(SMSBodyPreviewTemplate, 'sms', marks=pytest.mark.xfail),
    ]
)
@pytest.mark.parametrize(
    "url, url_with_entities_replaced", [
        ("http://example.com", "http://example.com"),
        ("http://www.gov.uk/", "http://www.gov.uk/"),
        ("https://www.gov.uk/", "https://www.gov.uk/"),
        ("http://service.gov.uk", "http://service.gov.uk"),
        (
            "http://service.gov.uk/blah.ext?q=a%20b%20c&order=desc#fragment",
            "http://service.gov.uk/blah.ext?q=a%20b%20c&amp;order=desc#fragment",
        ),
        pytest.param("example.com", "example.com", marks=pytest.mark.xfail),
        pytest.param("www.example.com", "www.example.com", marks=pytest.mark.xfail),
        pytest.param(
            "http://service.gov.uk/blah.ext?q=one two three",
            "http://service.gov.uk/blah.ext?q=one two three",
            marks=pytest.mark.xfail,
        ),
        pytest.param("ftp://example.com", "ftp://example.com", marks=pytest.mark.xfail),
        pytest.param("mailto:test@example.com", "mailto:test@example.com", marks=pytest.mark.xfail),
    ]
)
def test_makes_links_out_of_URLs(template_class, template_type, url, url_with_entities_replaced):
    assert '<a style="word-wrap: break-word; color: #005ea5;" href="{}">{}</a>'.format(
        url_with_entities_replaced, url_with_entities_replaced
    ) in str(template_class({'content': url, 'subject': '', 'template_type': template_type}))


@pytest.mark.parametrize('content, html_snippet', (
    (
        (
            'You’ve been invited to a service. Click this link:\n'
            'https://service.example.com/accept_invite/a1b2c3d4\n'
            '\n'
            'Thanks\n'
        ),
        (
            '<a style="word-wrap: break-word; color: #005ea5;"'
            ' href="https://service.example.com/accept_invite/a1b2c3d4">'
            'https://service.example.com/accept_invite/a1b2c3d4'
            '</a>'
        ),
    ),
    (
        (
            'https://service.example.com/accept_invite/?a=b&c=d&'
        ),
        (
            '<a style="word-wrap: break-word; color: #005ea5;"'
            ' href="https://service.example.com/accept_invite/?a=b&amp;c=d&amp;">'
            'https://service.example.com/accept_invite/?a=b&amp;c=d&amp;'
            '</a>'
        ),
    ),
))
def test_HTML_template_has_URLs_replaced_with_links(content, html_snippet):
    assert html_snippet in str(HTMLEmailTemplate({
        'content': content, 'subject': '', 'template_type': 'email'
    }))


@pytest.mark.parametrize(
    "template_content,expected", [
        ("gov.uk", u"gov.\u200Buk"),
        ("GOV.UK", u"GOV.\u200BUK"),
        ("Gov.uk", u"Gov.\u200Buk"),
        ("https://gov.uk", "https://gov.uk"),
        ("https://www.gov.uk", "https://www.gov.uk"),
        ("www.gov.uk", "www.gov.uk"),
        ("gov.uk/register-to-vote", "gov.uk/register-to-vote"),
        ("gov.uk?q=", "gov.uk?q=")
    ]
)
def test_escaping_govuk_in_email_templates(template_content, expected):
    assert unlink_govuk_escaped(template_content) == expected
    assert expected in str(PlainTextEmailTemplate({
        'content': template_content, 'subject': '', 'template_type': 'email',
    }))
    assert expected in str(HTMLEmailTemplate({
        'content': template_content, 'subject': '', 'template_type': 'email',
    }))


def test_stripping_of_unsupported_characters_in_email_templates():
    template_content = "line one\u2028line two"
    expected = "line oneline two"
    assert expected in str(PlainTextEmailTemplate({
        'content': template_content, 'subject': '', 'template_type': 'email',
    }))
    assert expected in str(HTMLEmailTemplate({
        'content': template_content, 'subject': '', 'template_type': 'email',
    }))


@mock.patch('notifications_utils.template.add_prefix', return_value='')
@pytest.mark.parametrize(
    "template_class, prefix, body, expected_call", [
        (SMSMessageTemplate, "a", "b", (Markup("b"), "a")),
        (SMSPreviewTemplate, "a", "b", (Markup("b"), "a")),
        (BroadcastPreviewTemplate, "a", "b", (Markup("b"), "a")),
        (SMSMessageTemplate, None, "b", (Markup("b"), None)),
        (SMSPreviewTemplate, None, "b", (Markup("b"), None)),
        (BroadcastPreviewTemplate, None, "b", (Markup("b"), None)),
        (SMSMessageTemplate, '<em>ht&ml</em>', "b", (Markup("b"), '<em>ht&ml</em>')),
        (SMSPreviewTemplate, '<em>ht&ml</em>', "b", (Markup("b"), '&lt;em&gt;ht&amp;ml&lt;/em&gt;')),
        (BroadcastPreviewTemplate, '<em>ht&ml</em>', "b", (Markup("b"), '&lt;em&gt;ht&amp;ml&lt;/em&gt;')),
    ]
)
def test_sms_message_adds_prefix(add_prefix, template_class, prefix, body, expected_call):
    template = template_class({'content': body, 'template_type': template_class.template_type})
    template.prefix = prefix
    template.sender = None
    str(template)
    add_prefix.assert_called_once_with(*expected_call)


@mock.patch('notifications_utils.template.add_prefix', return_value='')
@pytest.mark.parametrize(
    'template_class', [
        SMSMessageTemplate,
        SMSPreviewTemplate,
        BroadcastPreviewTemplate,
    ]
)
@pytest.mark.parametrize(
    "show_prefix, prefix, body, sender, expected_call", [
        (False, "a", "b", "c", (Markup("b"), None)),
        (True, "a", "b", None, (Markup("b"), "a")),
        (True, "a", "b", False, (Markup("b"), "a")),
    ]
)
def test_sms_message_adds_prefix_only_if_asked_to(
    add_prefix,
    show_prefix,
    prefix,
    body,
    sender,
    expected_call,
    template_class,
):
    template = template_class(
        {'content': body, 'template_type': template_class.template_type},
        prefix=prefix,
        show_prefix=show_prefix,
        sender=sender,
    )
    str(template)
    add_prefix.assert_called_once_with(*expected_call)


@pytest.mark.parametrize('content_to_look_for', [
    'GOVUK', 'sms-message-sender'
])
@pytest.mark.parametrize("show_sender", [
    True,
    pytest.param(False, marks=pytest.mark.xfail),
])
def test_sms_message_preview_shows_sender(
    show_sender,
    content_to_look_for,
):
    assert content_to_look_for in str(SMSPreviewTemplate(
        {'content': 'foo', 'template_type': 'sms'},
        sender='GOVUK',
        show_sender=show_sender,
    ))


def test_sms_message_preview_hides_sender_by_default():
    assert SMSPreviewTemplate({
        'content': 'foo', 'template_type': 'sms'
    }).show_sender is False


@mock.patch('notifications_utils.template.sms_encode', return_value='downgraded')
@pytest.mark.parametrize(
    'template_class, extra_args, expected_call', (
        (SMSMessageTemplate, {'prefix': 'Service name'}, 'Service name: Message'),
        (SMSPreviewTemplate, {'prefix': 'Service name'}, 'Service name: Message'),
        (BroadcastMessageTemplate, {}, 'Message'),
        (BroadcastPreviewTemplate, {'prefix': 'Service name'}, 'Service name: Message'),
        (SMSBodyPreviewTemplate, {}, 'Message'),
    )
)
def test_sms_messages_downgrade_non_sms(
    mock_sms_encode,
    template_class,
    extra_args,
    expected_call,
):
    template = str(template_class(
        {'content': 'Message', 'template_type': template_class.template_type},
        **extra_args
    ))
    assert 'downgraded' in str(template)
    mock_sms_encode.assert_called_once_with(expected_call)


@pytest.mark.parametrize('template_class', (
    SMSPreviewTemplate, BroadcastPreviewTemplate,
))
@mock.patch('notifications_utils.template.sms_encode', return_value='downgraded')
def test_sms_messages_dont_downgrade_non_sms_if_setting_is_false(mock_sms_encode, template_class):
    template = str(template_class(
        {'content': '😎', 'template_type': template_class.template_type},
        prefix='👉',
        downgrade_non_sms_characters=False,
    ))
    assert '👉: 😎' in str(template)
    assert mock_sms_encode.called is False


@pytest.mark.parametrize('template_class', (
    SMSPreviewTemplate, BroadcastPreviewTemplate,
))
@mock.patch('notifications_utils.template.nl2br')
def test_sms_preview_adds_newlines(nl2br, template_class):
    content = "the\nquick\n\nbrown fox"
    str(template_class({'content': content, 'template_type': template_class.template_type}))
    nl2br.assert_called_once_with(content)


@pytest.mark.parametrize('content', [
    (  # Unix-style
        'one newline\n'
        'two newlines\n'
        '\n'
        'end'
    ),
    (  # Windows-style
        'one newline\r\n'
        'two newlines\r\n'
        '\r\n'
        'end'
    ),
    (  # Mac Classic style
        'one newline\r'
        'two newlines\r'
        '\r'
        'end'
    ),
    (  # A mess
        '\t\t\n\r one newline\xa0\n'
        'two newlines\r'
        '\r\n'
        'end\n\n  \r \n \t '
    ),
])
def test_sms_message_normalises_newlines(content):
    assert repr(str(
        SMSMessageTemplate({'content': content, 'template_type': 'sms'})
    )) == repr(
        'one newline\n'
        'two newlines\n'
        '\n'
        'end'
    )


@pytest.mark.parametrize('content', [
    (  # Unix-style
        'one newline\n'
        'two newlines\n'
        '\n'
        'end'
    ),
    (  # Windows-style
        'one newline\r\n'
        'two newlines\r\n'
        '\r\n'
        'end'
    ),
    (  # Mac Classic style
        'one newline\r'
        'two newlines\r'
        '\r'
        'end'
    ),
    (  # A mess
        '\t\t\n\r one newline\xa0\n'
        'two newlines\r'
        '\r\n'
        'end\n\n  \r \n \t '
    ),
])
def test_broadcast_message_normalises_newlines(content):
    xml = BeautifulSoup(
        str(BroadcastMessageTemplate(
            {'content': content, 'template_type': 'broadcast'}
        )),
        'lxml-xml',
    )
    assert xml.select_one('alert info description').text == (
        'one newline\n'
        'two newlines\n'
        '\n'
        'end'
    )


@freeze_time("2012-12-12 12:12:12")
@mock.patch('notifications_utils.template.LetterPreviewTemplate.jinja_template.render')
@mock.patch('notifications_utils.template.unlink_govuk_escaped')
@mock.patch('notifications_utils.template.notify_letter_preview_markdown', return_value='Bar')
@pytest.mark.parametrize('values, expected_address', [
    ({}, [
        "<span class='placeholder-no-brackets'>address line 1</span>",
        "<span class='placeholder-no-brackets'>address line 2</span>",
        "<span class='placeholder-no-brackets'>address line 3</span>",
        "<span class='placeholder-no-brackets'>address line 4</span>",
        "<span class='placeholder-no-brackets'>address line 5</span>",
        "<span class='placeholder-no-brackets'>address line 6</span>",
        "<span class='placeholder-no-brackets'>postcode</span>",
    ]),
    ({
        'address line 1': '123 Fake Street',
        'address line 6': 'United Kingdom',
    }, [
        "123 Fake Street",
        "<span class='placeholder-no-brackets'>address line 2</span>",
        "<span class='placeholder-no-brackets'>address line 3</span>",
        "<span class='placeholder-no-brackets'>address line 4</span>",
        "<span class='placeholder-no-brackets'>address line 5</span>",
        "United Kingdom",
        "<span class='placeholder-no-brackets'>postcode</span>",
    ]),
    ({
        'address line 1': '123 Fake Street',
        'address line 2': 'City of Town',
        'postcode': 'SW1A 1AA',
    }, [
        "123 Fake Street",
        "City of Town",
        "SW1A 1AA",
    ])
])
@pytest.mark.parametrize('contact_block, expected_rendered_contact_block', [
    (
        None,
        ''
    ),
    (
        '',
        ''
    ),
    (
        """
            The Pension Service
            Mail Handling Site A
            Wolverhampton  WV9 1LU

            Telephone: 0845 300 0168
            Email: fpc.customercare@dwp.gsi.gov.uk
            Monday - Friday  8am - 6pm
            www.gov.uk
        """,
        (
            'The Pension Service<br>'
            'Mail Handling Site A<br>'
            'Wolverhampton  WV9 1LU<br>'
            '<br>'
            'Telephone: 0845 300 0168<br>'
            'Email: fpc.customercare@dwp.gsi.gov.uk<br>'
            'Monday - Friday  8am - 6pm<br>'
            'www.gov.uk'
        )
    )
])
@pytest.mark.parametrize('extra_args, expected_logo_file_name, expected_logo_class', [
    ({}, None, None),
    ({'logo_file_name': 'example.foo'}, 'example.foo', 'foo'),
])
@pytest.mark.parametrize('additional_extra_args, expected_date', [
    ({}, '12 December 2012'),
    ({'date': None}, '12 December 2012'),
    ({'date': datetime.date.fromtimestamp(0)}, '1 January 1970'),
])
def test_letter_preview_renderer(
    letter_markdown,
    unlink_govuk,
    jinja_template,
    values,
    expected_address,
    contact_block,
    expected_rendered_contact_block,
    extra_args,
    expected_logo_file_name,
    expected_logo_class,
    additional_extra_args,
    expected_date,
):
    extra_args.update(additional_extra_args)
    str(LetterPreviewTemplate(
        {'content': 'Foo', 'subject': 'Subject', 'template_type': 'letter'},
        values,
        contact_block=contact_block,
        **extra_args
    ))
    jinja_template.assert_called_once_with({
        'address': expected_address,
        'subject': 'Subject',
        'message': 'Bar',
        'date': expected_date,
        'contact_block': expected_rendered_contact_block,
        'admin_base_url': 'http://localhost:6012',
        'logo_file_name': expected_logo_file_name,
        'logo_class': expected_logo_class,
    })
    letter_markdown.assert_called_once_with(Markup('Foo\n'))
    unlink_govuk.assert_not_called()


@freeze_time("2001-01-01 12:00:00.000000")
@mock.patch('notifications_utils.template.LetterPreviewTemplate.jinja_template.render')
def test_letter_preview_renderer_without_mocks(jinja_template):

    str(LetterPreviewTemplate(
        {'content': 'Foo', 'subject': 'Subject', 'template_type': 'letter'},
        {'addressline1': 'name', 'addressline2': 'street', 'postcode': 'SW1 1AA'},
        contact_block='',
    ))

    jinja_template_locals = jinja_template.call_args_list[0][0][0]

    assert jinja_template_locals['address'] == [
        'name',
        'street',
        'SW1 1AA',
    ]
    assert jinja_template_locals['subject'] == 'Subject'
    assert jinja_template_locals['message'] == "<p>Foo</p>"
    assert jinja_template_locals['date'] == '1 January 2001'
    assert jinja_template_locals['contact_block'] == ''
    assert jinja_template_locals['admin_base_url'] == 'http://localhost:6012'
    assert jinja_template_locals['logo_file_name'] is None


@freeze_time("2012-12-12 12:12:12")
@mock.patch('notifications_utils.template.LetterImageTemplate.jinja_template.render')
@pytest.mark.parametrize('page_count, expected_oversized, expected_page_numbers', [
    (
        1, False,
        [1],
    ),
    (
        5, False,
        [1, 2, 3, 4, 5],
    ),
    (
        10, False,
        [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
    ),
    (
        11, True,
        [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
    ),
    (
        99, True,
        [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
    ),
])
@pytest.mark.parametrize(
    'postage_args, expected_show_postage, expected_postage_class_value, expected_postage_description',
    (
        pytest.param({}, False, None, None),
        pytest.param({'postage': None}, False, None, None),
        pytest.param({'postage': 'first'}, True, 'letter-postage-first', 'first class'),
        pytest.param({'postage': 'second'}, True, 'letter-postage-second', 'second class'),
        pytest.param({'postage': 'europe'}, True, 'letter-postage-international', 'international'),
        pytest.param({'postage': 'rest-of-world'}, True, 'letter-postage-international', 'international'),
        pytest.param(
            {'postage': 'third'}, True, 'letter-postage-third', 'third class',
            marks=pytest.mark.xfail(raises=TypeError),
        ),
    ),
)
def test_letter_image_renderer(
    jinja_template,
    page_count,
    expected_page_numbers,
    expected_oversized,
    postage_args,
    expected_show_postage,
    expected_postage_class_value,
    expected_postage_description,
):
    str(LetterImageTemplate(
        {'content': 'Content', 'subject': 'Subject', 'template_type': 'letter'},
        image_url='http://example.com/endpoint.png',
        page_count=page_count,
        contact_block='10 Downing Street',
        **postage_args
    ))
    jinja_template.assert_called_once_with({
        'image_url': 'http://example.com/endpoint.png',
        'page_numbers': expected_page_numbers,
        'address': [
            "<span class='placeholder-no-brackets'>address line 1</span>",
            "<span class='placeholder-no-brackets'>address line 2</span>",
            "<span class='placeholder-no-brackets'>address line 3</span>",
            "<span class='placeholder-no-brackets'>address line 4</span>",
            "<span class='placeholder-no-brackets'>address line 5</span>",
            "<span class='placeholder-no-brackets'>address line 6</span>",
            "<span class='placeholder-no-brackets'>postcode</span>",
        ],
        'contact_block': '10 Downing Street',
        'date': '12 December 2012',
        'subject': 'Subject',
        'message': '<p>Content</p>',
        'show_postage': expected_show_postage,
        'postage_class_value': expected_postage_class_value,
        'postage_description': expected_postage_description,
    })


def test_letter_image_template_renders_visually_hidden_address():
    template = BeautifulSoup(
        str(LetterImageTemplate(
            {'content': '', 'subject': '', 'template_type': 'letter'},
            {
                'address_line_1': 'line 1',
                'address_line_2': 'line 2',
                'postcode': 'postcode',
            },
            image_url='http://example.com/endpoint.png',
            page_count=1,
        )),
        features='html.parser',
    )
    assert str(template.select_one('.visually-hidden ul')) == (
        '<ul>'
        '<li>line 1</li>'
        '<li>line 2</li>'
        '<li>postcode</li>'
        '</ul>'
    )


@pytest.mark.parametrize('page_image_url', [
    pytest.param('http://example.com/endpoint.png?page=0', marks=pytest.mark.xfail),
    'http://example.com/endpoint.png?page=1',
    'http://example.com/endpoint.png?page=2',
    'http://example.com/endpoint.png?page=3',
    pytest.param('http://example.com/endpoint.png?page=4', marks=pytest.mark.xfail),
])
def test_letter_image_renderer_pagination(page_image_url):
    assert page_image_url in str(LetterImageTemplate(
        {'content': '', 'subject': '', 'template_type': 'letter'},
        image_url='http://example.com/endpoint.png',
        page_count=3,
    ))


@pytest.mark.parametrize('partial_call, expected_exception, expected_message', [
    (
        partial(LetterImageTemplate),
        TypeError,
        'image_url is required',
    ),
    (
        partial(LetterImageTemplate, page_count=1),
        TypeError,
        'image_url is required',
    ),
    (
        partial(LetterImageTemplate, image_url='foo'),
        TypeError,
        'page_count is required',
    ),
    (
        partial(LetterImageTemplate, image_url='foo', page_count='foo'),
        ValueError,
        'invalid literal for int() with base 10: \'foo\'',
    ),
    (
        partial(LetterImageTemplate, image_url='foo', page_count=1, postage='third'),
        TypeError,
        'postage must be None, \'first\', \'second\', \'europe\' or \'rest-of-world\''
    ),
])
def test_letter_image_renderer_requires_arguments(
    partial_call,
    expected_exception,
    expected_message,
):
    with pytest.raises(expected_exception) as exception:
        partial_call({'content': '', 'subject': '', 'template_type': 'letter'})
    assert str(exception.value) == expected_message


@pytest.mark.parametrize('postage, expected_attribute_value, expected_postage_text', (
    (None, None, None),
    (
        'first',
        ['letter-postage', 'letter-postage-first'],
        'Postage: first class',
    ),
    (
        'second',
        ['letter-postage', 'letter-postage-second'],
        'Postage: second class',
    ),
    (
        'europe',
        ['letter-postage', 'letter-postage-international'],
        'Postage: international',
    ),
    (
        'rest-of-world',
        ['letter-postage', 'letter-postage-international'],
        'Postage: international',
    ),
))
def test_letter_image_renderer_passes_postage_to_html_attribute(
    postage,
    expected_attribute_value,
    expected_postage_text,
):
    template = BeautifulSoup(
        str(LetterImageTemplate(
            {'content': '', 'subject': '', 'template_type': 'letter'},
            image_url='foo',
            page_count=1,
            postage=postage,
        )),
        features='html.parser',
    )
    if expected_attribute_value:
        assert template.select_one('.letter-postage')['class'] == expected_attribute_value
        assert template.select_one('.letter-postage').text.strip() == expected_postage_text
    else:
        assert not template.select('.letter-postage')


@pytest.mark.parametrize('template_class', (
    SMSBodyPreviewTemplate,
    SMSMessageTemplate,
    SMSPreviewTemplate,
    BroadcastMessageTemplate,
    BroadcastPreviewTemplate,
))
@pytest.mark.parametrize('template_json', (
    {"content": ''},
    {"content": '', 'subject': 'subject'},
))
def test_sms_templates_have_no_subject(template_class, template_json):
    template_json.update(template_type=template_class.template_type)
    assert not hasattr(
        template_class(template_json),
        'subject',
    )


def test_subject_line_gets_applied_to_correct_template_types():
    for cls in [
        EmailPreviewTemplate,
        HTMLEmailTemplate,
        PlainTextEmailTemplate,
        LetterPreviewTemplate,
        LetterImageTemplate,
    ]:
        assert issubclass(cls, SubjectMixin)
    for cls in [
        SMSBodyPreviewTemplate,
        SMSMessageTemplate,
        SMSPreviewTemplate,
        BroadcastMessageTemplate,
        BroadcastPreviewTemplate,
    ]:
        assert not issubclass(cls, SubjectMixin)


@pytest.mark.parametrize('template_class, template_type, extra_args', (
    (EmailPreviewTemplate, 'email', {}),
    (HTMLEmailTemplate, 'email', {}),
    (PlainTextEmailTemplate, 'email', {}),
    (LetterPreviewTemplate, 'letter', {}),
    (LetterPrintTemplate, 'letter', {}),
    (LetterImageTemplate, 'letter', {
        'image_url': 'http://example.com',
        'page_count': 1,
    }),
))
def test_subject_line_gets_replaced(template_class, template_type, extra_args):
    template = template_class({
        "content": '', 'template_type': template_type, 'subject': '((name))'
    }, **extra_args)
    assert template.subject == Markup("<span class='placeholder'>((name))</span>")
    template.values = {'name': 'Jo'}
    assert template.subject == 'Jo'


@pytest.mark.parametrize('template_class, template_type, extra_args', (
    (EmailPreviewTemplate, 'email', {}),
    (HTMLEmailTemplate, 'email', {}),
    (PlainTextEmailTemplate, 'email', {}),
    (LetterPreviewTemplate, 'letter', {}),
    (LetterPrintTemplate, 'letter', {}),
    (LetterImageTemplate, 'letter', {
        'image_url': 'http://example.com',
        'page_count': 1,
    }),
))
@pytest.mark.parametrize("content, values, expected_count", [
    ("Content with ((placeholder))", {"placeholder": "something extra"}, 28),
    ("Content with ((placeholder))", {"placeholder": ""}, 12),
    ("Just content", {}, 12),
    ("((placeholder))  ", {"placeholder": "  "}, 0),
    ("  ", {}, 0),
])
def test_character_count_for_non_sms_templates(
    template_class,
    template_type,
    extra_args,
    content,
    values,
    expected_count,
):
    template = template_class({
        "content": content, 'subject': 'Hi', 'template_type': template_type,
    }, **extra_args)
    template.values = values
    assert template.content_count == expected_count


@pytest.mark.parametrize('template_class', [
    SMSMessageTemplate,
    SMSPreviewTemplate,
])
@pytest.mark.parametrize("content, values, prefix, expected_count_in_template, expected_count_in_notification", [
    # is an unsupported unicode character so should be replaced with a ?
    ("深", {}, None, 1, 1),
    # is a supported unicode character so should be kept as is
    ("Ŵ", {}, None, 1, 1),
    ("'First line.\n", {}, None, 12, 12),
    ("\t\n\r", {}, None, 0, 0),
    ("Content with ((placeholder))", {"placeholder": "something extra here"}, None, 28, 33),
    ("Content with ((placeholder))", {"placeholder": ""}, None, 28, 12),
    ("Just content", {}, None, 12, 12),
    ("((placeholder))  ", {"placeholder": "  "}, None, 15, 0),
    ("  ", {}, None, 0, 0),
    ("Content with ((placeholder))", {"placeholder": "something extra here"}, "GDS", 33, 38),
    ("Just content", {}, "GDS", 17, 17),
    ("((placeholder))  ", {"placeholder": "  "}, "GDS", 20, 4),
    ("  ", {}, "GDS", 4, 4),  # Becomes `GDS:`
    ("  G      D       S  ", {}, None, 5, 5),  # Becomes `G D S`
    ("P1 \n\n\n\n\n\n P2", {}, None, 6, 6),  # Becomes `P1\n\nP2`
])
def test_character_count_for_sms_templates(
    content, values, prefix, expected_count_in_template, expected_count_in_notification, template_class
):
    template = template_class(
        {"content": content, 'template_type': 'sms'},
        prefix=prefix,
    )
    template.sender = None
    assert template.content_count == expected_count_in_template
    template.values = values
    assert template.content_count == expected_count_in_notification


@pytest.mark.parametrize('template_class', [
    BroadcastMessageTemplate,
    BroadcastPreviewTemplate,
])
@pytest.mark.parametrize("content, values, expected_count_in_template, expected_count_in_notification", [
    # is an unsupported unicode character so should be replaced with a ?
    ("深", {}, 1, 1),
    # is a supported unicode character so should be kept as is
    ("Ŵ", {}, 1, 1),
    ("'First line.\n", {}, 12, 12),
    ("\t\n\r", {}, 0, 0),
    ("Content with ((placeholder))", {"placeholder": "something extra here"}, 28, 33),
    ("Content with ((placeholder))", {"placeholder": ""}, 28, 12),
    ("Just content", {}, 12, 12),
    ("((placeholder))  ", {"placeholder": "  "}, 15, 0),
    ("  ", {}, 0, 0),
    ("  G      D       S  ", {}, 5, 5),  # Becomes `G D S`
    ("P1 \n\n\n\n\n\n P2", {}, 6, 6),  # Becomes `P1\n\nP2`
])
def test_character_count_for_broadcast_templates(
    content, values, expected_count_in_template, expected_count_in_notification, template_class
):
    template = template_class(
        {"content": content, 'template_type': 'broadcast'},
    )
    assert template.content_count == expected_count_in_template
    template.values = values
    assert template.content_count == expected_count_in_notification


@pytest.mark.parametrize('template_class', (
    SMSMessageTemplate,
    BroadcastMessageTemplate,
))
@pytest.mark.parametrize(
    "msg, expected_sms_fragment_count",
    [
        ('à' * 71, 1),  # welsh character in GSM
        ('à' * 160, 1),
        ('à' * 161, 2),
        ('à' * 306, 2),
        ('à' * 307, 3),
        ('à' * 612, 4),
        ('à' * 613, 5),
        ('à' * 765, 5),
        ('à' * 766, 6),
        ('à' * 918, 6),
        ('à' * 919, 7),

        ('ÿ' * 70, 1),  # welsh character not in GSM, so send as unicode
        ('ÿ' * 71, 2),
        ('ÿ' * 134, 2),
        ('ÿ' * 135, 3),
        ('ÿ' * 268, 4),
        ('ÿ' * 269, 5),
        ('ÿ' * 402, 6),
        ('ÿ' * 403, 7),
        ('à' * 70 + 'ÿ', 2),  # just one non-gsm character means it's sent at unicode
        ('🚀' * 160, 1),  # non-welsh unicode characters are downgraded to gsm, so are only one fragment long
    ])
def test_sms_fragment_count_accounts_for_unicode_and_welsh_characters(
    template_class,
    msg,
    expected_sms_fragment_count,
):
    template = template_class({'content': msg, 'template_type': template_class.template_type})
    assert template.fragment_count == expected_sms_fragment_count


@pytest.mark.parametrize('template_class', [
    SMSMessageTemplate,
    SMSPreviewTemplate,
])
@pytest.mark.parametrize('content, values, prefix, expected_result', [
    ("", {}, None, True),
    ("", {}, "GDS", True),
    ("((placeholder))", {"placeholder": ""}, "GDS", True),
    ("((placeholder))", {"placeholder": "Some content"}, None, False),
    ("Some content", {}, "GDS", False),
])
def test_is_message_empty_sms_templates(content, values, prefix, expected_result, template_class):
    template = template_class(
        {"content": content, 'template_type': 'sms'},
        prefix=prefix,
    )
    template.sender = None
    template.values = values
    assert template.is_message_empty() == expected_result


@pytest.mark.parametrize('template_class', [
    BroadcastMessageTemplate,
    BroadcastPreviewTemplate,
])
@pytest.mark.parametrize('content, values, expected_result', [
    ("", {}, True),
    ("((placeholder))", {"placeholder": ""}, True),
    ("((placeholder))", {"placeholder": "Some content"}, False),
    ("Some content", {}, False),
])
def test_is_message_empty_broadcast_templates(content, values, expected_result, template_class):
    template = template_class(
        {"content": content, 'template_type': 'broadcast'},
    )
    template.sender = None
    template.values = values
    assert template.is_message_empty() == expected_result


@pytest.mark.parametrize('template_class, template_type', (
    (HTMLEmailTemplate, 'email'),
    (LetterPrintTemplate, 'letter'),
))
@pytest.mark.parametrize('content, values, expected_result', [
    ("", {}, True),
    ("((placeholder))", {"placeholder": ""}, True),
    ("((placeholder))", {"placeholder": "   \t   \r\n"}, True),
    ("((placeholder))", {"placeholder": "Some content"}, False),
    ("((placeholder??show_or_hide))", {"placeholder": False}, True),
    ("Some content", {}, False),
    ("((placeholder)) some content", {"placeholder": ""}, False),
    ("Some content ((placeholder))", {"placeholder": ""}, False),
])
def test_is_message_empty_email_and_letter_templates(
    template_class,
    template_type,
    content,
    values,
    expected_result,
):
    template = template_class({
        "content": content, 'subject': 'Hi', 'template_type': template_class.template_type,
    })
    template.sender = None
    template.values = values
    assert template.is_message_empty() == expected_result


@pytest.mark.parametrize('template_class, template_type', (
    (HTMLEmailTemplate, 'email'),
    (LetterPrintTemplate, 'letter'),
))
@pytest.mark.parametrize('content, values', [
    ("Some content", {}),
    ("((placeholder)) some content", {"placeholder": ""}),
    ("Some content ((placeholder))", {"placeholder": ""}),
    pytest.param(
        "((placeholder))", {"placeholder": "Some content"},
        marks=pytest.mark.xfail(raises=AssertionError),
    ),
])
def test_is_message_empty_email_and_letter_templates_tries_not_to_count_chars(
    mocker,
    template_class,
    template_type,
    content,
    values,
):
    template = template_class({
        "content": content, 'subject': 'Hi', 'template_type': template_type,
    })
    mock_content = mocker.patch.object(
        template_class,
        'content_count',
        create=True,
        new_callable=mock.PropertyMock,
        return_value=None,
    )
    template.values = values
    template.is_message_empty()
    assert mock_content.called is False


@pytest.mark.parametrize('template_class, template_type, extra_args, expected_field_calls', [
    (PlainTextEmailTemplate, 'email', {}, [
        mock.call('content', {}, html='passthrough', markdown_lists=True)
    ]),
    (HTMLEmailTemplate, 'email', {}, [
        mock.call('content', {}, html='escape', markdown_lists=True, redact_missing_personalisation=False),
        mock.call('content', {}, html='escape', markdown_lists=True),
    ]),
    (EmailPreviewTemplate, 'email', {}, [
        mock.call('content', {}, html='escape', markdown_lists=True, redact_missing_personalisation=False),
        mock.call('subject', {}, html='escape', redact_missing_personalisation=False),
        mock.call('((email address))', {}, with_brackets=False),
    ]),
    (SMSMessageTemplate, 'sms', {}, [
        mock.call('content', {}, html='passthrough'),
    ]),
    (SMSPreviewTemplate, 'sms', {}, [
        mock.call('((phone number))', {}, with_brackets=False, html='escape'),
        mock.call('content', {}, html='escape', redact_missing_personalisation=False),
    ]),
    (BroadcastMessageTemplate, 'broadcast', {}, [
        mock.call('content', {}, html='escape'),
    ]),
    (BroadcastPreviewTemplate, 'broadcast', {}, [
        mock.call('((phone number))', {}, with_brackets=False, html='escape'),
        mock.call('content', {}, html='escape', redact_missing_personalisation=False),
    ]),
    (LetterPreviewTemplate, 'letter', {'contact_block': 'www.gov.uk'}, [
        mock.call('subject', {}, html='escape', redact_missing_personalisation=False),
        mock.call('content', {}, html='escape', markdown_lists=True, redact_missing_personalisation=False),
        mock.call((
            '((address line 1))\n'
            '((address line 2))\n'
            '((address line 3))\n'
            '((address line 4))\n'
            '((address line 5))\n'
            '((address line 6))\n'
            '((postcode))'
        ), {}, with_brackets=False, html='escape'),
        mock.call('www.gov.uk', {}, html='escape', redact_missing_personalisation=False),
    ]),
    (LetterImageTemplate, 'letter', {
        'image_url': 'http://example.com', 'page_count': 1, 'contact_block': 'www.gov.uk'
    }, [
        mock.call((
            '((address line 1))\n'
            '((address line 2))\n'
            '((address line 3))\n'
            '((address line 4))\n'
            '((address line 5))\n'
            '((address line 6))\n'
            '((postcode))'
        ), {}, with_brackets=False, html='escape'),
        mock.call('www.gov.uk', {}, html='escape', redact_missing_personalisation=False),
        mock.call('subject', {}, html='escape', redact_missing_personalisation=False),
        mock.call('content', {}, html='escape', markdown_lists=True, redact_missing_personalisation=False),
    ]),
    (EmailPreviewTemplate, 'email', {'redact_missing_personalisation': True}, [
        mock.call('content', {}, html='escape', markdown_lists=True, redact_missing_personalisation=True),
        mock.call('subject', {}, html='escape', redact_missing_personalisation=True),
        mock.call('((email address))', {}, with_brackets=False),
    ]),
    (SMSPreviewTemplate, 'sms', {'redact_missing_personalisation': True}, [
        mock.call('((phone number))', {}, with_brackets=False, html='escape'),
        mock.call('content', {}, html='escape', redact_missing_personalisation=True),
    ]),
    (BroadcastPreviewTemplate, 'broadcast', {'redact_missing_personalisation': True}, [
        mock.call('((phone number))', {}, with_brackets=False, html='escape'),
        mock.call('content', {}, html='escape', redact_missing_personalisation=True),
    ]),
    (SMSBodyPreviewTemplate, 'sms', {}, [
        mock.call('content', {}, html='escape', redact_missing_personalisation=True),
    ]),
    (LetterPreviewTemplate, 'letter', {'contact_block': 'www.gov.uk', 'redact_missing_personalisation': True}, [
        mock.call('subject', {}, html='escape', redact_missing_personalisation=True),
        mock.call('content', {}, html='escape', markdown_lists=True, redact_missing_personalisation=True),
        mock.call((
            '((address line 1))\n'
            '((address line 2))\n'
            '((address line 3))\n'
            '((address line 4))\n'
            '((address line 5))\n'
            '((address line 6))\n'
            '((postcode))'
        ), {}, with_brackets=False, html='escape'),
        mock.call('www.gov.uk', {}, html='escape', redact_missing_personalisation=True),
    ]),
])
@mock.patch('notifications_utils.template.Field.__init__', return_value=None)
@mock.patch('notifications_utils.template.Field.__str__', return_value='1\n2\n3\n4\n5\n6\n7\n8')
def test_templates_handle_html_and_redacting(
    mock_field_str,
    mock_field_init,
    template_class,
    template_type,
    extra_args,
    expected_field_calls,
):
    assert str(template_class(
        {'content': 'content', 'subject': 'subject', 'template_type': template_type},
        **extra_args
    ))
    assert mock_field_init.call_args_list == expected_field_calls


@pytest.mark.parametrize('template_class, template_type, extra_args, expected_remove_whitespace_calls', [
    (PlainTextEmailTemplate, 'email', {}, [
        mock.call('\n\ncontent'),
        mock.call(Markup('subject')),
        mock.call(Markup('subject')),
    ]),
    (HTMLEmailTemplate, 'email', {}, [
        mock.call(
            '<p style="Margin: 0 0 20px 0; font-size: 19px; line-height: 25px; color: #0B0C0C;">'
            'content'
            '</p>'
        ),
        mock.call('\n\ncontent'),
        mock.call(Markup('subject')),
        mock.call(Markup('subject')),
    ]),
    (EmailPreviewTemplate, 'email', {}, [
        mock.call(
            '<p style="Margin: 0 0 20px 0; font-size: 19px; line-height: 25px; color: #0B0C0C;">'
            'content'
            '</p>'
        ),
        mock.call(Markup('subject')),
        mock.call(Markup('subject')),
        mock.call(Markup('subject')),
    ]),
    (SMSMessageTemplate, 'sms', {}, [
        mock.call('content'),
    ]),
    (SMSPreviewTemplate, 'sms', {}, [
        mock.call('content'),
    ]),
    (SMSBodyPreviewTemplate, 'sms', {}, [
        mock.call('content'),
    ]),
    (BroadcastMessageTemplate, 'broadcast', {}, [
        mock.call('content'),
    ]),
    (BroadcastPreviewTemplate, 'broadcast', {}, [
        mock.call('content'),
    ]),
    (LetterPreviewTemplate, 'letter', {'contact_block': 'www.gov.uk'}, [
        mock.call(Markup('subject')),
        mock.call(Markup('<p>content</p>')),
        mock.call(Markup('www.gov.uk')),
        mock.call(Markup('subject')),
        mock.call(Markup('subject')),
    ]),
])
@mock.patch('notifications_utils.template.remove_whitespace_before_punctuation', side_effect=lambda x: x)
def test_templates_remove_whitespace_before_punctuation(
    mock_remove_whitespace,
    template_class,
    template_type,
    extra_args,
    expected_remove_whitespace_calls,
):
    template = template_class(
        {'content': 'content', 'subject': 'subject', 'template_type': template_type},
        **extra_args
    )

    assert str(template)

    if hasattr(template, 'subject'):
        assert template.subject

    assert mock_remove_whitespace.call_args_list == expected_remove_whitespace_calls


@pytest.mark.parametrize('template_class, template_type, extra_args, expected_calls', [
    (PlainTextEmailTemplate, 'email', {}, [
        mock.call('\n\ncontent'),
        mock.call(Markup('subject')),
    ]),
    (HTMLEmailTemplate, 'email', {}, [
        mock.call(
            '<p style="Margin: 0 0 20px 0; font-size: 19px; line-height: 25px; color: #0B0C0C;">'
            'content'
            '</p>'
        ),
        mock.call('\n\ncontent'),
        mock.call(Markup('subject')),
    ]),
    (EmailPreviewTemplate, 'email', {}, [
        mock.call(
            '<p style="Margin: 0 0 20px 0; font-size: 19px; line-height: 25px; color: #0B0C0C;">'
            'content'
            '</p>'
        ),
        mock.call(Markup('subject')),
    ]),
    (SMSMessageTemplate, 'sms', {}, [
    ]),
    (SMSPreviewTemplate, 'sms', {}, [
    ]),
    (SMSBodyPreviewTemplate, 'sms', {}, [
    ]),
    (BroadcastMessageTemplate, 'broadcast', {}, [
    ]),
    (BroadcastPreviewTemplate, 'broadcast', {}, [
    ]),
    (LetterPreviewTemplate, 'letter', {'contact_block': 'www.gov.uk'}, [
        mock.call(Markup('subject')),
        mock.call(Markup('<p>content</p>')),
    ]),
])
@mock.patch('notifications_utils.template.make_quotes_smart', side_effect=lambda x: x)
@mock.patch('notifications_utils.template.replace_hyphens_with_en_dashes', side_effect=lambda x: x)
def test_templates_make_quotes_smart_and_dashes_en(
    mock_en_dash_replacement,
    mock_smart_quotes,
    template_class,
    template_type,
    extra_args,
    expected_calls,
):
    template = template_class(
        {'content': 'content', 'subject': 'subject', 'template_type': template_type},
        **extra_args
    )

    assert str(template)

    if hasattr(template, 'subject'):
        assert template.subject

    mock_smart_quotes.assert_has_calls(expected_calls)
    mock_en_dash_replacement.assert_has_calls(expected_calls)


@pytest.mark.parametrize('content', (
    "first.o'last@example.com",
    "first.o’last@example.com",
))
@pytest.mark.parametrize('template_class', (
    HTMLEmailTemplate,
    PlainTextEmailTemplate,
    EmailPreviewTemplate,
))
def test_no_smart_quotes_in_email_addresses(template_class, content):
    template = template_class({
        'content': content,
        'subject': content,
        'template_type': 'email',
    })
    assert "first.o'last@example.com" in str(template)
    assert template.subject == "first.o'last@example.com"


def test_smart_quotes_removed_from_long_template_in_under_a_second():
    long_string = 'a' * 100000
    template = PlainTextEmailTemplate({
        'content': long_string, 'subject': '', 'template_type': 'email',
    })

    start_time = process_time()

    str(template)

    assert process_time() - start_time < 1


@pytest.mark.parametrize('template_instance, expected_placeholders', [
    (
        SMSMessageTemplate(
            {"content": "((content))", "subject": "((subject))", "template_type": "sms"},
        ),
        ['content'],
    ),
    (
        SMSPreviewTemplate(
            {"content": "((content))", "subject": "((subject))", "template_type": "sms"},
        ),
        ['content'],
    ),
    (
        SMSBodyPreviewTemplate(
            {"content": "((content))", "subject": "((subject))", "template_type": "sms"},
        ),
        ['content'],
    ),
    (
        BroadcastMessageTemplate(
            {"content": "((content))", "subject": "((subject))", "template_type": "broadcast"},
        ),
        ['content'],
    ),
    (
        BroadcastPreviewTemplate(
            {"content": "((content))", "subject": "((subject))", "template_type": "broadcast"},
        ),
        ['content'],
    ),
    (
        PlainTextEmailTemplate(
            {"content": "((content))", "subject": "((subject))", "template_type": "email"},
        ),
        ['subject', 'content'],
    ),
    (
        HTMLEmailTemplate(
            {"content": "((content))", "subject": "((subject))", "template_type": "email"},
        ),
        ['subject', 'content'],
    ),
    (
        EmailPreviewTemplate(
            {"content": "((content))", "subject": "((subject))", "template_type": "email"},
        ),
        ['subject', 'content'],
    ),
    (
        LetterPreviewTemplate(
            {"content": "((content))", "subject": "((subject))", "template_type": "letter"},
            contact_block='((contact_block))',
        ),
        ['contact_block', 'subject', 'content'],
    ),
    (
        LetterImageTemplate(
            {"content": "((content))", "subject": "((subject))", "template_type": "letter"},
            contact_block='((contact_block))',
            image_url='http://example.com',
            page_count=99,
        ),
        ['contact_block', 'subject', 'content'],
    ),
])
def test_templates_extract_placeholders(
    template_instance,
    expected_placeholders,
):
    assert template_instance.placeholders == OrderedSet(expected_placeholders)


@pytest.mark.parametrize('extra_args', [
    {
        'from_name': 'Example service'
    },
    {
        'from_name': 'Example service',
        'from_address': 'test@example.com',
    },
    pytest.param({}, marks=pytest.mark.xfail),
])
def test_email_preview_shows_from_name(extra_args):
    template = EmailPreviewTemplate(
        {'content': 'content', 'subject': 'subject', 'template_type': 'email'},
        **extra_args
    )
    assert '<th>From</th>' in str(template)
    assert 'Example service' in str(template)
    assert 'test@example.com' not in str(template)


def test_email_preview_escapes_html_in_from_name():
    template = EmailPreviewTemplate(
        {'content': 'content', 'subject': 'subject', 'template_type': 'email'},
        from_name='<script>alert("")</script>',
        from_address='test@example.com',
    )
    assert '<script>' not in str(template)
    assert '&lt;script&gt;alert("")&lt;/script&gt;' in str(template)


@pytest.mark.parametrize('extra_args', [
    {
        'reply_to': 'test@example.com'
    },
    pytest.param({}, marks=pytest.mark.xfail),
])
def test_email_preview_shows_reply_to_address(extra_args):
    template = EmailPreviewTemplate(
        {'content': 'content', 'subject': 'subject', 'template_type': 'email'},
        **extra_args
    )
    assert '<th>Reply&nbsp;to</th>' in str(template)
    assert 'test@example.com' in str(template)


@pytest.mark.parametrize('template_values, expected_content', [
    (
        {},
        '<span class=\'placeholder-no-brackets\'>email address</span>'
    ),
    (
        {'email address': 'test@example.com'},
        'test@example.com'
    ),
])
def test_email_preview_shows_recipient_address(
    template_values,
    expected_content,
):
    template = EmailPreviewTemplate(
        {'content': 'content', 'subject': 'subject', 'template_type': 'email'},
        template_values,
    )
    assert expected_content in str(template)


@pytest.mark.parametrize("address, expected", [
    (
        {
            "address line 1": "line 1",
            "address line 2": "line 2",
            "address line 3": "line 3",
            "address line 4": "line 4",
            "address line 5": "line 5",
            "address line 6": "line 6",
            "postcode": "n14w q",
        },
        (
            "<ul>"
            "<li>line 1</li>"
            "<li>line 2</li>"
            "<li>line 3</li>"
            "<li>line 4</li>"
            "<li>line 5</li>"
            "<li>line 6</li>"
            "<li>N1 4WQ</li>"
            "</ul>"
        ),
    ), (
        {
            "addressline1": "line 1",
            "addressline2": "line 2",
            "addressline3": "line 3",
            "addressline4": "line 4",
            "addressline5": "line 5",
            "addressLine6": "line 6",
            "postcode": "not a postcode",
        },
        (
            "<ul>"
            "<li>line 1</li>"
            "<li>line 2</li>"
            "<li>line 3</li>"
            "<li>line 4</li>"
            "<li>line 5</li>"
            "<li>line 6</li>"
            "<li>not a postcode</li>"
            "</ul>"
        ),
    ),
    (
        {
            "address line 1": "line 1",
            "postcode": "n1 4wq",
        },
        (
            '<ul>'
            '<li>line 1</li>'
            '<li><span class="placeholder-no-brackets">address line 2</span></li>'
            '<li><span class="placeholder-no-brackets">address line 3</span></li>'
            '<li><span class="placeholder-no-brackets">address line 4</span></li>'
            '<li><span class="placeholder-no-brackets">address line 5</span></li>'
            '<li><span class="placeholder-no-brackets">address line 6</span></li>'
            # Postcode is not normalised until the address is complete
            '<li>n1 4wq</li>'
            '</ul>'
        ),
    ),
    (
        {
            "addressline1": "line 1",
            "addressline2": "line 2",
            "addressline3": None,
            "addressline6": None,
            "postcode": "N1 4Wq",
        },
        (
            "<ul>"
            "<li>line 1</li>"
            "<li>line 2</li>"
            "<li>N1 4WQ</li>"
            "</ul>"
        ),
    ),
    (
        {
            "addressline1": "line 1",
            "addressline2": "line 2     ,   ",
            "addressline3": "\t     ,",
            "postcode": "N1 4WQ",
        },
        (
            "<ul>"
            "<li>line 1</li>"
            "<li>line 2</li>"
            "<li>N1 4WQ</li>"
            "</ul>"
        ),
    ),
    (
        {
            "addressline1": "line 1",
            "addressline2": "line 2",
            "postcode": "SW1A 1AA",  # ignored in favour of line 7
            "addressline7": "N1 4WQ",
        },
        (
            "<ul>"
            "<li>line 1</li>"
            "<li>line 2</li>"
            "<li>N1 4WQ</li>"
            "</ul>"
        ),
    ),
    (
        {
            "addressline1": "line 1",
            "addressline2": "line 2",
            "addressline7": "N1 4WQ",  # means postcode isn’t needed
        },
        (
            "<ul>"
            "<li>line 1</li>"
            "<li>line 2</li>"
            "<li>N1 4WQ</li>"
            "</ul>"
        ),
    ),
])
@pytest.mark.parametrize('template_class', (LetterPreviewTemplate, LetterPrintTemplate))
def test_letter_address_format(template_class, address, expected):
    template = BeautifulSoup(
        str(template_class(
            {'content': '', 'subject': '', 'template_type': 'letter'},
            address,
        )),
        features='html.parser',
    )
    assert str(template.select_one('#to ul')) == expected


@freeze_time("2001-01-01 12:00:00.000000")
@pytest.mark.parametrize('markdown, expected', [
    (
        (
            'Here is a list of bullets:\n'
            '\n'
            '* one\n'
            '* two\n'
            '* three\n'
            '\n'
            'New paragraph'
        ),
        (
            '<ul>\n'
            '<li>one</li>\n'
            '<li>two</li>\n'
            '<li>three</li>\n'
            '</ul>\n'
            '<p>New paragraph</p>\n'
        )
    ),
    (
        (
            '# List title:\n'
            '\n'
            '* one\n'
            '* two\n'
            '* three\n'
        ),
        (
            '<h2>List title:</h2>\n'
            '<ul>\n'
            '<li>one</li>\n'
            '<li>two</li>\n'
            '<li>three</li>\n'
            '</ul>\n'
        )
    ),
    (
        (
            'Here’s an ordered list:\n'
            '\n'
            '1. one\n'
            '2. two\n'
            '3. three\n'
        ),
        (
            '<p>Here’s an ordered list:</p><ol>\n'
            '<li>one</li>\n'
            '<li>two</li>\n'
            '<li>three</li>\n'
            '</ol>'
        )
    ),
])
def test_lists_in_combination_with_other_elements_in_letters(markdown, expected):
    assert expected in str(LetterPreviewTemplate(
        {'content': markdown, 'subject': 'Hello', 'template_type': 'letter'},
        {},
    ))


@pytest.mark.parametrize('template_class', [
    SMSMessageTemplate,
    SMSPreviewTemplate,
])
def test_message_too_long_ignoring_prefix(template_class):
    body = ('b' * 917) + '((foo))'
    template = template_class(
        {'content': body, 'template_type': template_class.template_type},
        prefix='a' * 100,
        values={'foo': 'cc'}
    )
    # content length is prefix + 919 characters (more than limit of 918)
    assert template.is_message_too_long() is True


@pytest.mark.parametrize('template_class', [
    SMSMessageTemplate,
    SMSPreviewTemplate,
])
def test_message_is_not_too_long_ignoring_prefix(template_class):
    body = ('b' * 917) + '((foo))'
    template = template_class(
        {'content': body, 'template_type': template_class.template_type},
        prefix='a' * 100,
        values={'foo': 'c'},
    )
    # content length is prefix + 918 characters (not more than limit of 918)
    assert template.is_message_too_long() is False


@pytest.mark.parametrize('extra_characters, expected_too_long', (
    ('cc', True),  # content length is 919 characters (more than limit of 918)
    ('c', False),  # content length is 918 characters (not more than limit of 918)
))
@pytest.mark.parametrize('template_class', [
    BroadcastMessageTemplate,
    BroadcastPreviewTemplate,
])
def test_broadcast_message_too_long(template_class, extra_characters, expected_too_long):
    body = ('b' * 917) + '((foo))'
    template = template_class(
        {'content': body, 'template_type': 'broadcast'},
        values={'foo': extra_characters}
    )
    assert template.is_message_too_long() is expected_too_long


@pytest.mark.parametrize('template_class, template_type, kwargs', [
    (EmailPreviewTemplate, 'email', {}),
    (HTMLEmailTemplate, 'email', {}),
    (PlainTextEmailTemplate, 'email', {}),
    (LetterPreviewTemplate, 'letter', {}),
    (LetterImageTemplate, 'letter', {'image_url': 'foo', 'page_count': 1}),
])
def test_non_sms_ignores_message_too_long(template_class, template_type, kwargs):
    body = 'a' * 1000
    template = template_class(
        {'content': body, 'subject': 'foo', 'template_type': template_type},
        **kwargs
    )
    assert template.is_message_too_long() is False


@pytest.mark.parametrize(
    (
        'content,'
        'expected_preview_markup,'
    ), [
        (
            'a\n\n\nb',
            (
                '<p>a</p>'
                '<p>b</p>'
            ),
        ),
        (
            (
                'a\n'
                '\n'
                '* one\n'
                '* two\n'
                '* three\n'
                'and a half\n'
                '\n'
                '\n'
                '\n'
                '\n'
                'foo'
            ),
            (
                '<p>a</p><ul>\n'
                '<li>one</li>\n'
                '<li>two</li>\n'
                '<li>three<br>and a half</li>\n'
                '</ul>\n'
                '<p>foo</p>'
            ),
        ),
    ]
)
def test_multiple_newlines_in_letters(
    content,
    expected_preview_markup,
):
    assert expected_preview_markup in str(LetterPreviewTemplate(
        {'content': content, 'subject': 'foo', 'template_type': 'letter'}
    ))


@pytest.mark.parametrize('subject', [
    ' no break ',
    ' no\tbreak ',
    '\tno break\t',
    'no \r\nbreak',
    'no \nbreak',
    'no \rbreak',
    '\rno break\n',
])
@pytest.mark.parametrize('template_class, template_type, extra_args', [
    (PlainTextEmailTemplate, 'email', {}),
    (HTMLEmailTemplate, 'email', {}),
    (EmailPreviewTemplate, 'email', {}),
    (LetterPreviewTemplate, 'letter', {}),
])
def test_whitespace_in_subjects(template_class, template_type, subject, extra_args):

    template_instance = template_class(
        {'content': 'foo', 'subject': subject, 'template_type': template_type},
        **extra_args
    )
    assert template_instance.subject == 'no break'


@pytest.mark.parametrize('template_class', [
    EmailPreviewTemplate,
    HTMLEmailTemplate,
    PlainTextEmailTemplate,
])
def test_whitespace_in_subject_placeholders(template_class):
    assert template_class(
        {'content': '', 'subject': '\u200C Your tax   ((status))', 'template_type': 'email'},
        values={'status': ' is\ndue '}
    ).subject == 'Your tax is due'


@pytest.mark.parametrize('template_class, expected_output', [
    (
        PlainTextEmailTemplate,
        'paragraph one\n\n\xa0\n\nparagraph two',
    ),
    (
        HTMLEmailTemplate,
        (
            '<p style="Margin: 0 0 20px 0; font-size: 19px; line-height: 25px; color: #0B0C0C;">paragraph one</p>'
            '<p style="Margin: 0 0 20px 0; font-size: 19px; line-height: 25px; color: #0B0C0C;">&nbsp;</p>'
            '<p style="Margin: 0 0 20px 0; font-size: 19px; line-height: 25px; color: #0B0C0C;">paragraph two</p>'
        ),
    ),
])
def test_govuk_email_whitespace_hack(template_class, expected_output):

    template_instance = template_class({
        'content': 'paragraph one\n\n&nbsp;\n\nparagraph two',
        'subject': 'foo',
        'template_type': 'email',
    })
    assert expected_output in str(template_instance)


def test_letter_preview_uses_non_breaking_hyphens():
    assert 'non\u2011breaking' in str(LetterPreviewTemplate({
        'content': 'non-breaking',
        'subject': 'foo',
        'template_type': 'letter',
    }))
    assert '–' in str(LetterPreviewTemplate({
        'content': 'en dash - not hyphen - when set with spaces',
        'subject': 'foo',
        'template_type': 'letter',
    }))


@freeze_time("2001-01-01 12:00:00.000000")
def test_nested_lists_in_lettr_markup():

    template_content = str(LetterPreviewTemplate({
        'content': (
            'nested list:\n'
            '\n'
            '1. one\n'
            '2. two\n'
            '3. three\n'
            '  - three one\n'
            '  - three two\n'
            '  - three three\n'
        ),
        'subject': 'foo',
        'template_type': 'letter',
    }))

    assert (
        '      <p>\n'
        '        1 January 2001\n'
        '      </p>\n'
        # Note that the H1 tag has no trailing whitespace
        '      <h1>foo</h1>\n'
        '      <p>nested list:</p><ol>\n'
        '<li>one</li>\n'
        '<li>two</li>\n'
        '<li>three<ul>\n'
        '<li>three one</li>\n'
        '<li>three two</li>\n'
        '<li>three three</li>\n'
        '</ul></li>\n'
        '</ol>\n'
        '\n'
        '    </div>\n'
        '  </body>\n'
        '</html>'
    ) in template_content


def test_that_print_template_is_the_same_as_preview():
    assert dir(LetterPreviewTemplate) == dir(LetterPrintTemplate)
    assert os.path.basename(LetterPreviewTemplate.jinja_template.filename) == 'preview.jinja2'
    assert os.path.basename(LetterPrintTemplate.jinja_template.filename) == 'print.jinja2'


def test_plain_text_email_whitespace():
    email = PlainTextEmailTemplate({'template_type': 'email', 'subject': 'foo', 'content': (
        '# Heading\n'
        '\n'
        '1. one\n'
        '2. two\n'
        '3. three\n'
        '\n'
        '***\n'
        '\n'
        '# Heading\n'
        '\n'
        'Paragraph\n'
        '\n'
        'Paragraph\n'
        '\n'
        '^ callout\n'
        '\n'
        '1. one not four\n'
        '1. two not five'
    )})
    assert str(email) == (
        'Heading\n'
        '-----------------------------------------------------------------\n'
        '\n'
        '1. one\n'
        '2. two\n'
        '3. three\n'
        '\n'
        '=================================================================\n'
        '\n'
        '\n'
        'Heading\n'
        '-----------------------------------------------------------------\n'
        '\n'
        'Paragraph\n'
        '\n'
        'Paragraph\n'
        '\n'
        'callout\n'
        '\n'
        '1. one not four\n'
        '2. two not five\n'
    )


@pytest.mark.parametrize('renderer, template_type, expected_content', (
    (PlainTextEmailTemplate, 'email', (
        'Heading link: https://example.com\n'
        '-----------------------------------------------------------------\n'
    )),
    (HTMLEmailTemplate, 'email', (
        '<h2 style="Margin: 0 0 20px 0; padding: 0; font-size: 27px; '
        'line-height: 35px; font-weight: bold; color: #0B0C0C;">'
        'Heading <a style="word-wrap: break-word; color: #005ea5;" href="https://example.com">link</a>'
        '</h2>'
    )),
    (LetterPreviewTemplate, 'letter', (
        '<h2>Heading link: <strong>example.com</strong></h2>'
    )),
    (LetterPrintTemplate, 'letter', (
        '<h2>Heading link: <strong>example.com</strong></h2>'
    )),
))
def test_heading_only_template_renders(renderer, template_type, expected_content):
    assert expected_content in str(renderer({
        'subject': 'foo',
        'content': (
            '# Heading [link](https://example.com)'
        ),
        'template_type': template_type,
    }))


@pytest.mark.parametrize("template_class", [
    LetterPreviewTemplate,
    LetterPrintTemplate,
])
@pytest.mark.parametrize("filename, expected_html_class", [
    ('example.png', 'class="png"'),
    ('example.svg', 'class="svg"'),
])
def test_image_class_applied_to_logo(template_class, filename, expected_html_class):
    assert expected_html_class in str(template_class(
        {'content': 'Foo', 'subject': 'Subject', 'template_type': 'letter'},
        logo_file_name=filename,
    ))


@pytest.mark.parametrize("template_class", [
    LetterPreviewTemplate,
    LetterPrintTemplate,
])
def test_image_not_present_if_no_logo(template_class):
    # can't test that the html doesn't move in utils - tested in template preview instead
    assert '<img' not in str(template_class(
        {'content': 'Foo', 'subject': 'Subject', 'template_type': 'letter'},
        logo_file_name=None,
    ))


@pytest.mark.parametrize('content', (
    (
        'The     quick brown fox.\n'
        '\n\n\n\n'
        'Jumps over the lazy dog.   \n'
        'Single linebreak above.'
    ),
    (
        '\n   \n'
        'The quick brown fox.  \n\n'
        '          Jumps over the lazy dog   .  \n'
        'Single linebreak above. \n  \n \n'
    ),
))
@pytest.mark.parametrize('template_class, expected', (
    (SMSBodyPreviewTemplate, (
        'The quick brown fox.\n'
        '\n'
        'Jumps over the lazy dog.\n'
        'Single linebreak above.'
    )),
    (SMSMessageTemplate, (
        'The quick brown fox.\n'
        '\n'
        'Jumps over the lazy dog.\n'
        'Single linebreak above.'
    )),
    (SMSPreviewTemplate, (
        '\n\n'
        '<div class="sms-message-wrapper">\n'
        '  The quick brown fox.<br><br>Jumps over the lazy dog.<br>Single linebreak above.\n'
        '</div>'
    )),
    (BroadcastPreviewTemplate, (
        '<div class="broadcast-message-wrapper">\n'
        '  The quick brown fox.<br><br>Jumps over the lazy dog.<br>Single linebreak above.\n'
        '</div>'
    )),
))
def test_text_messages_collapse_consecutive_whitespace(
    template_class,
    content,
    expected,
):
    template = template_class({"content": content, "template_type": template_class.template_type})
    assert str(template) == expected
    assert template.content_count == 70 == len(
        'The quick brown fox.\n'
        '\n'
        'Jumps over the lazy dog.\n'
        'Single linebreak above.'
    )


def test_letter_preview_template_lazy_loads_images():
    page = BeautifulSoup(
        str(LetterImageTemplate(
            {'content': 'Content', 'subject': 'Subject', 'template_type': 'letter'},
            image_url='http://example.com/endpoint.png',
            page_count=3,
        )),
        'html.parser',
    )
    assert [
        (img['src'], img['loading'])
        for img in page.select('img')
    ] == [
        ('http://example.com/endpoint.png?page=1', 'eager'),
        ('http://example.com/endpoint.png?page=2', 'lazy'),
        ('http://example.com/endpoint.png?page=3', 'lazy'),
    ]


def test_broadcast_message_outputs_polygons():
    raw_xml = str(BroadcastMessageTemplate(
        {'content': 'foo', 'template_type': 'broadcast'},
        polygons=[
            [[0.001, -0.001], [0.002, -0.002], [0.003, -0.003]],
            [[-99.999, 1.234], [-99.998, 5.678]],
        ]
    ))
    tree = BeautifulSoup(raw_xml, 'lxml-xml')
    assert [
        polygon.text
        for polygon in tree.select_one('alert info area').select('polygon')
    ] == [
        '0.001,-0.001 0.002,-0.002 0.003,-0.003',
        '-99.999,1.234 -99.998,5.678',
    ]


def test_broadcast_message_outputs_valid_xml_according_to_schema():
    raw_xml = str(BroadcastMessageTemplate(
        {'content': 'foo', 'template_type': 'broadcast'},
        polygons=[
            [[1, -1], [2, -2]],
        ]
    ))
    validate_xml(raw_xml.encode('utf-8'), 'CAP-v1.2.xsd')


def test_broadcast_message_puts_correct_values_in_elements():
    raw_xml = str(BroadcastMessageTemplate(
        {'content': 'this is a ((alert_type))', 'template_type': 'broadcast'},
        values={'alert_type': 'test'},
        polygons=[],
        identifier='unique',
    ))
    tree = BeautifulSoup(raw_xml, 'lxml-xml')

    for element, expected_text in (
        ('sender', 'https://www.notifications.service.gov.uk/'),
        ('identifier', 'unique'),
        ('status', 'Actual'),
        ('msgType', 'Alert'),
        ('scope', 'Public'),
        ('info category', 'Health'),
        ('info responseType', 'None'),
        ('info urgency', 'Immediate'),
        ('info severity', 'Extreme'),
        ('info certainty', 'Observed'),
        ('info description', 'this is a test'),
    ):
        assert tree.select_one(element).text == expected_text


@freeze_time('2020-06-01 02:03:04')
def test_broadcast_message_formats_timestamps_correctly():
    raw_xml = str(BroadcastMessageTemplate(
        {'content': 'content', 'template_type': 'broadcast'},
        identifier='unique',
    ))
    tree = BeautifulSoup(raw_xml, 'lxml-xml')
    # note the `-00:00` timezone
    assert tree.select_one('sent').text == '2020-06-01T02:03:04-00:00'


@freeze_time('2020-06-01 02:03:04')
def test_broadcast_message_reference():
    msg = BroadcastMessageTemplate(
        {'content': 'content', 'template_type': 'broadcast'},
        identifier='unique',
    )

    assert msg.reference == 'https://www.notifications.service.gov.uk/,unique,2020-06-01T02:03:04-00:00'


def test_broadcast_message_from_event():
    event = {
        'id': str(uuid.UUID(int=0)),
        'sent_at': '2020-06-01T02:03:04.000Z',
        'message_type': 'update',
        'transmitted_content': {'body': 'test content'},
        'transmitted_sender': 'currently unused',
        'transmitted_starts_at': None,
        'transmitted_finishes_at': '2020-06-07T12:00:00.000Z',
        'previous_event_references': [],
        'areas': [],
        'polygons': [],
    }

    msg = BroadcastMessageTemplate.from_event(event)

    assert msg.identifier == event['id']
    assert msg.sent == datetime.datetime(2020, 6, 1, 2, 3, 4)  # nb: no timezone
    assert msg.msg_type == 'Update'  # nb: title case
    xml = str(msg)
    tree = BeautifulSoup(xml, 'lxml-xml')
    # note the `-00:00` timezone
    assert tree.select_one('sent').text == '2020-06-01T02:03:04-00:00'
    assert tree.select_one('expires').text == '2020-06-07T12:00:00-00:00'
    assert tree.select_one('info description').text == 'test content'


def test_broadcast_message_from_event_matches_from_template():
    event = {
        'id': str(uuid.UUID(int=0)),
        'sent_at': '2020-06-07T12:00:00.000Z',
        'message_type': 'alert',
        'transmitted_content': {'body': 'test content'},
        'transmitted_sender': 'currently unused',
        'transmitted_starts_at': '2020-06-07T12:00:00.000Z',
        'transmitted_finishes_at': '2020-06-10T12:00:00.000Z',
        'previous_event_references': [],
        'areas': [],
        'polygons': [],
    }

    event_msg = BroadcastMessageTemplate.from_event(event)
    with freeze_time('2020-06-07T12:00:00.000Z'):
        template_msg = BroadcastMessageTemplate(
            {'content': 'test content', 'template_type': 'broadcast'},
            identifier=str(uuid.UUID(int=0)),
        )

    assert str(event_msg) == str(template_msg)


def test_broadcast_message_from_event_renders_references_list():
    event = {
        'id': str(uuid.UUID(int=0)),
        'sent_at': '2020-06-01T02:03:04.000Z',
        'message_type': 'update',
        'transmitted_content': {'body': 'test content'},
        'transmitted_sender': 'currently unused',
        'transmitted_starts_at': None,
        'transmitted_finishes_at': '2020-06-07T12:00:00.000Z',
        'previous_event_references': [
            'notify,unique-1,2020-06-01T00:00:00-00:00',
            'notify,unique-2,2020-06-01T01:01:01-00:00'
        ],
        'areas': [],
        'polygons': [],
    }

    raw_xml = str(BroadcastMessageTemplate.from_event(event))
    tree = BeautifulSoup(raw_xml, 'lxml-xml')

    expected_references = 'notify,unique-1,2020-06-01T00:00:00-00:00 notify,unique-2,2020-06-01T01:01:01-00:00'
    assert tree.select_one('references').text == expected_references
