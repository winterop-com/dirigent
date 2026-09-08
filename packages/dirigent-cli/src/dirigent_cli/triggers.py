"""The trigger and alerting command groups: schedules, webhooks, and alert rules."""

from pathlib import Path
from typing import Annotated, Any, cast

import typer

from dirigent_cli.commands import paged, parse_log_levels, parse_params, parse_priority
from dirigent_cli.context import Session, client_for, state_of
from dirigent_cli.output import (
    console,
    emit_fact,
    emit_one,
    emit_records,
    moment,
    refuse,
    render_bool,
    styled,
    table,
)
from dirigent_client import AlertEvent, AlertScope, WebhookTokenOut

schedule_app = typer.Typer(
    name="schedule", help="A pipeline's clocks: cron, interval, or one-time.", no_args_is_help=True
)
webhook_app = typer.Typer(name="webhook", help="Inbound webhooks and their delivery history.", no_args_is_help=True)
trigger_document_app = typer.Typer(
    name="trigger-document",
    help="Documents that declare clocks for a pipeline defined elsewhere.",
    no_args_is_help=True,
)
alerts_app = typer.Typer(name="alerts", help="Alert rules, and testing a channel.", no_args_is_help=True)
alerts_rules_app = typer.Typer(name="rules", help="The rules that bind an event to a channel.", no_args_is_help=True)
alerts_app.add_typer(alerts_rules_app)


def _check_clock(cron: str | None, interval: str | None, at: str | None) -> None:
    """Refuse zero or two clocks before anything is sent."""
    declared = [flag for flag, value in (("--cron", cron), ("--interval", interval), ("--at", at)) if value]
    if len(declared) != 1:
        named = ", ".join(declared) or "none"
        _fail(f"a schedule takes exactly one of --cron, --interval, or --at ({named} given)")


def _fail(message: str) -> None:
    """Write a refusal the CLI decided on its own as a record, and exit non-zero."""
    refuse(message)
    raise typer.Exit(code=1)


def _params_for(dg: Session, pipeline: str, values: list[str] | None, files: list[str] | None) -> dict[str, Any]:
    """Build a schedule's parameter overrides against the pipeline's own schema."""
    detail = dg.call(dg.pipelines.get(pipeline))
    document = detail.document or {}
    schema = cast("dict[str, Any]", document.get("params") or {})
    return parse_params(values, schema=schema, files=[Path(name) for name in files or []])


@schedule_app.command("create")
def schedule_create(
    ctx: typer.Context,
    pipeline: Annotated[str, typer.Argument(help="The pipeline this schedule belongs to.")],
    code: Annotated[str, typer.Argument(help="What to call it; unique within the pipeline.")],
    name: Annotated[str | None, typer.Option("--name", help="A human title for this schedule.")] = None,
    description: Annotated[str | None, typer.Option("--description", help="What this schedule is for.")] = None,
    cron: Annotated[str | None, typer.Option("--cron", help="A cron expression, in the schedule's timezone.")] = None,
    interval: Annotated[str | None, typer.Option("--interval", help="A humane duration, such as 1h or 30m.")] = None,
    at: Annotated[str | None, typer.Option("--at", help="An ISO instant, for a schedule that fires once.")] = None,
    timezone: Annotated[str, typer.Option("--tz", help="The IANA zone the clock is read in.")] = "UTC",
    param: Annotated[
        list[str] | None,
        typer.Option("-p", "--param", help="key=value parameter override, repeatable."),
    ] = None,
    param_file: Annotated[
        list[str] | None,
        typer.Option("-P", "--params-file", help="A file of parameter overrides, in YAML or JSON."),
    ] = None,
    log_level: Annotated[
        list[str] | None,
        typer.Option(
            "--log-level",
            help="A level every fired run keeps (debug) or PATTERN=LEVEL for one block family; "
            "repeatable. Omitted keeps info and up.",
        ),
    ] = None,
    priority: Annotated[
        str | None,
        typer.Option(
            "--priority",
            help="How far ahead of other runs a fired run is claimed: low, normal, or high. "
            "Omitted takes the pipeline's own.",
        ),
    ] = None,
) -> None:
    """Declare a schedule on a pipeline, with its own timezone and parameter overrides."""
    _check_clock(cron, interval, at)
    with client_for(state_of(ctx)) as dg:
        params = _params_for(dg, pipeline, param, param_file)
        created = dg.call(
            dg.schedules.create(
                pipeline,
                code,
                name=name,
                description=description,
                cron=cron,
                interval=interval,
                at=_instant(at),
                timezone=timezone,
                params=params,
                log_levels=parse_log_levels(log_level),
                priority=parse_priority(priority),
            )
        )
    emit_fact(
        "schedule.created",
        message="created",
        code=created.code,
        pipeline=pipeline,
        name=created.name,
        clock=str(created.cron or created.interval or created.at),
        timezone=created.timezone,
        next_fire_at=created.next_fire_at,
    )


def _instant(value: str | None) -> Any:
    """Read the ``--at`` flag as an ISO instant."""
    from datetime import datetime

    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        _fail(f"--at takes an ISO instant, and {value!r} is not one")


@schedule_app.command("list")
def schedule_list(
    ctx: typer.Context,
    pipeline: Annotated[str, typer.Argument(help="The pipeline whose schedules to list.")],
) -> None:
    """List a pipeline's schedules, with when each one next fires."""
    with client_for(state_of(ctx)) as dg:
        rows = list(paged(lambda after, size: dg.call(dg.schedules.list(pipeline, after=after, limit=size)), None))
    if state_of(ctx).json_output:
        return emit_records("schedule", rows)
    table(
        f"schedules of {pipeline}",
        ["code", "name", "clock", "timezone", "paused", "next firing", "last fired"],
        [
            [
                row.code,
                row.name or "-",
                str(row.cron or row.interval or row.at),
                row.timezone,
                render_bool(row.paused),
                moment(row.next_fire_at),
                moment(row.last_fired_at),
            ]
            for row in rows
        ],
    )


@schedule_app.command("pause")
def schedule_pause(
    ctx: typer.Context,
    pipeline: Annotated[str, typer.Argument()],
    code: Annotated[str, typer.Argument()],
) -> None:
    """Stop a schedule firing, keeping it and its history."""
    with client_for(state_of(ctx)) as dg:
        dg.call(dg.schedules.pause(pipeline, code))
    emit_fact("schedule.paused", message="paused", code=code, pipeline=pipeline)


@schedule_app.command("resume")
def schedule_resume(
    ctx: typer.Context,
    pipeline: Annotated[str, typer.Argument()],
    code: Annotated[str, typer.Argument()],
) -> None:
    """Start a schedule firing again, from the next slot rather than the ones it missed."""
    with client_for(state_of(ctx)) as dg:
        row = dg.call(dg.schedules.resume(pipeline, code))
    emit_fact(
        "schedule.resumed",
        message="resumed",
        code=code,
        pipeline=pipeline,
        next_fire_at=row.next_fire_at,
    )


@schedule_app.command("firings")
def schedule_firings(
    ctx: typer.Context,
    pipeline: Annotated[str, typer.Argument()],
    code: Annotated[str, typer.Argument()],
) -> None:
    """Show what a schedule has actually done, including the firings it skipped."""
    with client_for(state_of(ctx)) as dg:
        rows = list(
            paged(lambda after, size: dg.call(dg.schedules.firings(pipeline, code, after=after, limit=size)), None)
        )
    if state_of(ctx).json_output:
        return emit_records("firing", rows)
    table(
        f"firings of {code}",
        ["due", "fired", "outcome", "misfired", "run", "detail"],
        [
            [
                moment(row.scheduled_for),
                moment(row.created_at),
                styled(row.outcome.value),
                render_bool(row.misfired),
                str(row.run_id or "-")[:8],
                row.detail or "-",
            ]
            for row in rows
        ],
    )


@schedule_app.command("delete")
def schedule_delete(
    ctx: typer.Context,
    pipeline: Annotated[str, typer.Argument()],
    code: Annotated[str, typer.Argument()],
) -> None:
    """Remove a schedule and its firing history."""
    with client_for(state_of(ctx)) as dg:
        dg.call(dg.schedules.delete(pipeline, code))
    emit_fact("schedule.deleted", message="deleted", code=code, pipeline=pipeline)


def _print_token(minted: WebhookTokenOut, *, base_url: str) -> None:
    """Print a minted token once, with the URL already assembled.

    The instance stores only the token's hash; there is no second chance to read it.
    """
    console.print(f"\n  POST  [bold]{base_url.rstrip('/')}{minted.url_path}[/]")
    console.print(f"  Token [bold]{minted.token}[/]")
    console.print("\n[yellow]This token is shown once.[/] The instance stores only its hash.\n")


@webhook_app.command("create")
def webhook_create(
    ctx: typer.Context,
    pipeline: Annotated[str, typer.Argument(help="The pipeline this webhook starts.")],
    code: Annotated[str, typer.Argument(help="What to call it; unique within the pipeline.")],
    name: Annotated[str | None, typer.Option("--name", help="A human title for this webhook.")] = None,
    description: Annotated[str | None, typer.Option("--description", help="What this webhook is for.")] = None,
    map_value: Annotated[
        list[str] | None,
        typer.Option("--map", help="param=$.path.into.payload, repeatable."),
    ] = None,
    hmac_secret: Annotated[
        str | None,
        typer.Option("--hmac-secret", help="Require an X-Dirigent-Signature over the raw body."),
    ] = None,
    rate_limit: Annotated[int, typer.Option("--rate-limit", help="Deliveries a minute this token may make.")] = 60,
    priority: Annotated[
        str | None,
        typer.Option(
            "--priority",
            help="How far ahead of other runs an accepted delivery's run is claimed: low, normal, or high. "
            "Omitted takes the pipeline's own.",
        ),
    ] = None,
) -> None:
    """Declare a webhook and print its token once, with the URL to POST to."""
    mapping: dict[str, str] = {}
    for entry in map_value or []:
        if "=" not in entry:
            _fail(f"--map takes param=$.path.into.payload, and {entry!r} has no '='")
        key, path = entry.split("=", 1)
        mapping[key.strip()] = path.strip()
    with client_for(state_of(ctx)) as dg:
        minted = dg.call(
            dg.webhooks.create(
                pipeline,
                code,
                name=name,
                description=description,
                params_from_payload=mapping,
                hmac_secret=hmac_secret,
                rate_limit_per_minute=rate_limit,
                priority=parse_priority(priority),
            )
        )
        base = dg.url
    if state_of(ctx).json_output:
        return emit_fact(
            "webhook.created",
            message="created",
            code=minted.code,
            pipeline=pipeline,
            url=f"{base.rstrip('/')}{minted.url_path}",
            token=minted.token,
        )
    console.print(f"[green]created[/] webhook [bold]{minted.code}[/] on {pipeline}")
    _print_token(minted, base_url=base)


@webhook_app.command("list")
def webhook_list(
    ctx: typer.Context,
    pipeline: Annotated[str, typer.Argument(help="The pipeline whose webhooks to list.")],
) -> None:
    """List a pipeline's webhooks, with their mapping but never their tokens."""
    with client_for(state_of(ctx)) as dg:
        rows = list(paged(lambda after, size: dg.call(dg.webhooks.list(pipeline, after=after, limit=size)), None))
    if state_of(ctx).json_output:
        return emit_records("webhook", rows)
    table(
        f"webhooks of {pipeline}",
        ["code", "name", "token", "signed", "active", "limit/min", "maps", "last delivery"],
        [
            [
                row.code,
                row.name or "-",
                f"{row.token_prefix}...",
                render_bool(row.signed),
                render_bool(row.active),
                str(row.rate_limit_per_minute),
                ", ".join(sorted(row.params_from_payload)) or "-",
                moment(row.last_delivery_at),
            ]
            for row in rows
        ],
    )


@webhook_app.command("rotate-token")
def webhook_rotate(
    ctx: typer.Context,
    pipeline: Annotated[str, typer.Argument()],
    code: Annotated[str, typer.Argument()],
) -> None:
    """Mint a new token and forget the old one; every caller has to be updated."""
    with client_for(state_of(ctx)) as dg:
        minted = dg.call(dg.webhooks.rotate_token(pipeline, code))
        base = dg.url
    if state_of(ctx).json_output:
        return emit_fact(
            "webhook.token_rotated",
            message="rotated",
            code=code,
            pipeline=pipeline,
            url=f"{base.rstrip('/')}{minted.url_path}",
            token=minted.token,
        )
    console.print(f"[green]rotated[/] the token of webhook [bold]{code}[/]; the previous one no longer works")
    _print_token(minted, base_url=base)


@webhook_app.command("deliveries")
def webhook_deliveries(
    ctx: typer.Context,
    pipeline: Annotated[str, typer.Argument()],
    code: Annotated[str, typer.Argument()],
) -> None:
    """Show what has arrived at a webhook, refusals included."""
    with client_for(state_of(ctx)) as dg:
        rows = list(
            paged(lambda after, size: dg.call(dg.webhooks.deliveries(pipeline, code, after=after, limit=size)), None)
        )
    if state_of(ctx).json_output:
        return emit_records("delivery", rows)
    table(
        f"deliveries to {code}",
        ["received", "outcome", "run", "from", "detail"],
        [
            [
                moment(row.created_at),
                styled(row.outcome.value),
                str(row.run_id or "-")[:8],
                row.source or "-",
                row.reason or "-",
            ]
            for row in rows
        ],
    )


@webhook_app.command("delete")
def webhook_delete(
    ctx: typer.Context,
    pipeline: Annotated[str, typer.Argument()],
    code: Annotated[str, typer.Argument()],
) -> None:
    """Remove a webhook, its token, and its delivery history."""
    with client_for(state_of(ctx)) as dg:
        dg.call(dg.webhooks.delete(pipeline, code))
    emit_fact("webhook.deleted", message="deleted", code=code, pipeline=pipeline)


@alerts_rules_app.command("list")
def alerts_rules_list(
    ctx: typer.Context,
) -> None:
    """List the alert rules this instance holds."""
    with client_for(state_of(ctx)) as dg:
        rows = list(paged(lambda after, size: dg.call(dg.alerts.rules(after=after, limit=size)), None))
    if state_of(ctx).json_output:
        return emit_records("alert_rule", rows)
    table(
        "alert rules",
        ["code", "name", "event", "scope", "notifier", "throttle", "active", "last sent"],
        [
            [
                row.code,
                row.name or "-",
                row.event.value,
                row.pipeline or row.scope.value,
                row.notifier,
                row.throttle,
                render_bool(row.active),
                moment(row.last_sent_at),
            ]
            for row in rows
        ],
    )


@alerts_rules_app.command("create")
def alerts_rules_create(
    ctx: typer.Context,
    code: Annotated[str, typer.Argument(help="What to call the rule.")],
    event: Annotated[
        str,
        typer.Option(
            "--event",
            help="The event that fires it: run_failed, run_completed_with_errors, run_succeeded, or run_stuck.",
        ),
    ],
    notifier: Annotated[str, typer.Option("--notifier", help="The channel to deliver through, such as log.")],
    name: Annotated[str | None, typer.Option("--name", help="A human title for this rule.")] = None,
    description: Annotated[str | None, typer.Option("--description", help="What this rule is for.")] = None,
    pipeline: Annotated[str | None, typer.Option("--pipeline", help="Watch one pipeline instead of all.")] = None,
    connection: Annotated[str | None, typer.Option("--connection", help="The credential the channel uses.")] = None,
    template: Annotated[str | None, typer.Option("--template", help="Subject template, reading ${run.*}.")] = None,
    throttle: Annotated[str, typer.Option("--throttle", help="At most one message per window, e.g. 15m.")] = "0s",
) -> None:
    """Declare an alert rule binding an event at a scope to a channel."""
    if event not in set(AlertEvent):
        _fail(f"{event!r} is not an alert event ({', '.join(sorted(AlertEvent))})")
    with client_for(state_of(ctx)) as dg:
        created = dg.call(
            dg.alerts.create_rule(
                code,
                name=name,
                description=description,
                event=AlertEvent(event),
                notifier=notifier,
                scope=AlertScope.PIPELINE if pipeline else AlertScope.GLOBAL,
                pipeline=pipeline,
                connection=connection,
                template=template,
                throttle=throttle,
            )
        )
    emit_fact(
        "alert_rule.created",
        message="created",
        code=created.code,
        name=created.name,
        event=created.event.value,
        scope=created.pipeline or created.scope.value,
        notifier=created.notifier,
        connection=created.connection,
        throttle=created.throttle,
    )


@alerts_rules_app.command("delete")
def alerts_rules_delete(ctx: typer.Context, code: Annotated[str, typer.Argument()]) -> None:
    """Remove an alert rule; the notifications it already raised are kept."""
    with client_for(state_of(ctx)) as dg:
        dg.call(dg.alerts.delete_rule(code))
    emit_fact("alert_rule.deleted", message="deleted", code=code, notifications="kept")


@alerts_rules_app.command("pause")
def alerts_rules_pause(ctx: typer.Context, code: Annotated[str, typer.Argument()]) -> None:
    """Hold a rule's deliveries; the rule itself is left as it was declared."""
    _set_rule_paused(ctx, code, paused=True)


@alerts_rules_app.command("resume")
def alerts_rules_resume(ctx: typer.Context, code: Annotated[str, typer.Argument()]) -> None:
    """Let a held rule deliver again."""
    _set_rule_paused(ctx, code, paused=False)


def _set_rule_paused(ctx: typer.Context, code: str, *, paused: bool) -> None:
    """Write a rule's paused flag and say what it is now."""
    with client_for(state_of(ctx)) as dg:
        rule = dg.call(dg.alerts.set_rule_paused(code, paused=paused))
    emit_fact(
        "alert_rule.paused" if rule.paused else "alert_rule.resumed",
        message="paused" if rule.paused else "resumed",
        code=rule.code,
        event=rule.event.value,
        notifier=rule.notifier,
    )


@alerts_app.command("test")
def alerts_test(
    ctx: typer.Context,
    notifier: Annotated[str, typer.Argument(help="The channel to send through, such as log or webhook.")],
    connection: Annotated[
        str | None,
        typer.Option("--connection", help="The credential record the channel delivers through."),
    ] = None,
    subject: Annotated[str, typer.Option("--subject", help="What the test message says.")] = "dirigent test alert",
) -> None:
    """Send a test message through a channel, on the same queue a real alert takes."""
    with client_for(state_of(ctx)) as dg:
        queued = dg.call(dg.alerts.test(notifier=notifier, connection=connection, subject=subject))
    emit_fact(
        "notification.queued",
        message="queued",
        notification_id=str(queued.notification_id),
        notifier=queued.notifier,
        connection=connection,
        subject=subject,
        detail=queued.detail,
    )


@alerts_app.command("queue")
def alerts_queue(
    ctx: typer.Context,
) -> None:
    """Show queued and delivered alerts."""
    with client_for(state_of(ctx)) as dg:
        rows = list(paged(lambda after, size: dg.call(dg.alerts.notifications(after=after, limit=size)), None))
    if state_of(ctx).json_output:
        return emit_records("notification", rows)
    table(
        "notifications",
        ["subject", "notifier", "status", "tries", "sent", "error"],
        [
            [
                row.subject,
                row.notifier,
                styled(row.status.value),
                str(row.attempt),
                moment(row.sent_at),
                (row.error or "-")[:60],
            ]
            for row in rows
        ],
    )


@trigger_document_app.command("list")
def trigger_document_list(ctx: typer.Context) -> None:
    """List the triggers documents this instance holds, with the pipeline each one fires."""
    with client_for(state_of(ctx)) as dg:
        rows = list(paged(lambda after, size: dg.call(dg.trigger_documents.list(after=after, limit=size)), None))
    if state_of(ctx).json_output:
        return emit_records("trigger_document", rows)
    table(
        "trigger documents",
        ["code", "name", "pipeline", "source", "applied by", "applied"],
        [
            [
                row.code,
                row.name or "-",
                row.pipeline,
                row.provenance_source.value,
                row.applied_by or "-",
                moment(row.updated_at),
            ]
            for row in rows
        ],
    )


@trigger_document_app.command("show")
def trigger_document_show(
    ctx: typer.Context,
    code: Annotated[str, typer.Argument(help="The triggers document to read.")],
) -> None:
    """Show one triggers document and the schedules and webhooks it owns."""
    with client_for(state_of(ctx)) as dg:
        detail = dg.call(dg.trigger_documents.get(code))
    if state_of(ctx).json_output:
        return emit_one("trigger_document", detail)
    console.print(f"[bold]{detail.name or detail.code}[/]  [dim]{detail.code}[/]")
    console.print(f"  pipeline  [bold]{detail.pipeline}[/]")
    console.print(f"  digest    [dim]{detail.digest}[/]")
    console.print(f"  schedules {', '.join(detail.schedules) or '-'}")
    console.print(f"  webhooks  {', '.join(detail.webhooks) or '-'}")
    if detail.description:
        console.print(f"\n{detail.description}")


@trigger_document_app.command("delete")
def trigger_document_delete(
    ctx: typer.Context,
    code: Annotated[str, typer.Argument(help="The triggers document to remove.")],
) -> None:
    """Remove a triggers document and every schedule and webhook it declared."""
    with client_for(state_of(ctx)) as dg:
        dg.call(dg.trigger_documents.delete(code))
    emit_fact("trigger_document.deleted", message="deleted", code=code, schedules="deleted", webhooks="deleted")


@alerts_app.command("retry")
def alerts_retry(
    ctx: typer.Context,
    notification: Annotated[str, typer.Argument(metavar="NOTIFICATION", help="The notification's id.")],
) -> None:
    """Put one notification back on the queue, due now."""
    with client_for(state_of(ctx)) as dg:
        row = dg.call(dg.alerts.retry(notification))
    emit_fact(
        "notification.retried",
        message="queued",
        notification_id=str(row.id),
        notifier=row.notifier,
        subject=row.subject,
        attempt=row.attempt,
        available_at=row.available_at,
    )
