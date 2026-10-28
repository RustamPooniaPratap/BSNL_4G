"""Business rules of the raw daily upload: circle codes, the availability column and the outage calculation.

Availability basis (verified, not assumed): for the 4G Saturation sites of the Odisha daily dump of 13 Oct 2026,
``Nw Avail (4G TCS)`` equals the daily uptime the Master workbook holds for every one of the 1,543 matching
sites, and the workbook's outage minutes equal ``1440 * (1 - TCS / 100)`` at full precision (the dump's own
``Outage Min.`` column is the same value rounded to whole minutes, so it is not used). ``Nw Avail (4G)`` is
blank for almost all of these sites and is not the source.

So for 4G Saturation: availability = ``Nw Avail (4G TCS)``; outage minutes = 1440 * (1 - availability / 100),
over a full 24-hour reporting day, stored unrounded. A blank or invalid value is never read as 0.

LWE: the same dump format is expected, but the availability column is not confirmed and the identifier mapping
is not provided, so no LWE row can be imported yet (see resolvers.LweResolver).
"""
from __future__ import annotations

from dataclasses import dataclass

MINUTES_PER_DAY = 1440

# Raw circle codes -> site-master circle codes. Only verified aliases: the Odisha dump writes "OR" for the master's
# "OD" (the same sites, UVOR... IDs). Every other raw code equal to a master code is used as is.
CIRCLE_ALIASES = {'OR': 'OD'}


def canonical_circle(raw: str) -> str:
    code = (raw or '').strip().upper()
    return CIRCLE_ALIASES.get(code, code)


@dataclass(frozen=True)
class ProjectRules:
    project: str
    availability_field: str  # parser field holding the authoritative availability
    availability_column: str  # its header, for display
    availability_confirmed: bool
    other_fields: tuple[str, ...] = ()  # other availability columns shown for comparison, never used


PROJECT_RULES = {
    '4G Saturation': ProjectRules('4G Saturation', 'avail_4g_tcs', 'Nw Avail (4G TCS)', True, ('avail_4g',)),
    'LWE': ProjectRules('LWE', 'avail_4g_tcs', 'Nw Avail (4G TCS)', False, ('avail_4g',)),
}


@dataclass(frozen=True)
class Availability:
    value: float | None
    column: str
    code: str | None  # None when usable; otherwise a reason code
    message: str = ''
    note: str = ''


def resolve_availability(values: dict[str, str], rules: ProjectRules) -> Availability:
    """The availability of one row from the project's authoritative column, validated (0-100, a number)."""
    raw = values.get(rules.availability_field, '').strip()
    others = {f: values.get(f, '').strip() for f in rules.other_fields}
    if not raw:
        filled = [f for f, v in others.items() if v]
        note = (' Another availability column has a value; it is not used in its place.' if filled else '')
        return Availability(None, rules.availability_column, 'missing_availability',
                            f'{rules.availability_column} is blank: not read as 0% or as 0 outage minutes.' + note)
    try:
        value = float(raw.replace(',', ''))
    except ValueError:
        return Availability(None, rules.availability_column, 'invalid_availability', f'{rules.availability_column} "{raw}" is not a number.')
    if not 0 <= value <= 100:
        return Availability(None, rules.availability_column, 'availability_out_of_range',
                            f'{rules.availability_column} {raw} is outside 0–100 (availability is a percentage).')
    note = ''
    for f, v in others.items():
        try:
            if v and abs(float(v) - value) > 1e-9:
                note = f'The other availability column has {v}; {rules.availability_column} is the confirmed source.'
        except ValueError:
            continue
    return Availability(value, rules.availability_column, None, note=note)


def outage_minutes(availability: float) -> float:
    """Outage of a full 24-hour reporting day from the availability percentage (unrounded)."""
    if not 0 <= availability <= 100:
        raise ValueError('Availability must be between 0 and 100.')
    return MINUTES_PER_DAY * (1 - availability / 100)
