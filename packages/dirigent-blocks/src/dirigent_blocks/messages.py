"""Every refusal the built-in notifiers make, catalogued under the ``notify`` prefix."""

from dirigent_common import Catalogue

NOTIFY = Catalogue("notify")

WEBHOOK_HAS_NO_URL = NOTIFY.define(
    "webhook.no_url",
    "the webhook notifier has no url; set one on the connection this rule delivers through",
)

SLACK_TWO_WAYS = NOTIFY.define(
    "slack.two_ways",
    "set webhook_url or bot_token, not both: they are two ways to reach the same channel",
)

SLACK_WEBHOOK_HAS_A_CHANNEL = NOTIFY.define(
    "slack.webhook_has_a_channel",
    "a webhook_url carries its own channel; drop channel or use bot_token instead",
)

SLACK_TOKEN_NEEDS_A_CHANNEL = NOTIFY.define(
    "slack.token_needs_a_channel",
    "a bot_token needs a channel to post to: a channel id, or #name",
)

SLACK_HAS_NEITHER = NOTIFY.define(
    "slack.has_neither",
    "the slack notifier has no webhook_url and no bot_token; set one on the connection this rule delivers through",
)

SLACK_REFUSED = NOTIFY.define("slack.refused", "slack refused the message: {detail}")

SLACK_ANSWERED_OTHERWISE = NOTIFY.define(
    "slack.answered_otherwise",
    "slack answered something that is not a result: {detail}",
)

EMAIL_IS_MISSING = NOTIFY.define(
    "email.missing",
    "the email notifier has no {missing}; set it on the connection this rule delivers through",
)
