"""
Event Schedule - :mod:`fastf1.events`
=====================================

The :class:`EventSchedule` provides information about past and upcoming
Formula 1 events.

An :class:`Event` can be a race weekend or a testing event. Each event
consists of multiple :class:`~fastf1.core.Session`.

The event schedule objects are built on top of pandas'
:class:`pandas.DataFrame` (event schedule) and :class:`pandas.Series` (event).
Therefore, the usual methods of these pandas objects can be used in addition
to the special methods described here.

Event Schedule Data
-------------------

The event schedule and each event provide the following information as
DataFrame columns or Series values:

  - ``RoundNumber`` | :class:`int` |
    The number of the championship round. This is unique for race
    weekends, while testing events all share the round number zero.

  - ``Country`` | :class:`str` | The country in which the event is held.

  - ``Location`` | :class:`str` |
    The event location; usually the city or region in which the track is
    situated.

  - ``OfficialEventName`` | :class:`str` |
    The official event name as advertised, including sponsor names and stuff.

  - ``EventName`` | :class:`str` |
    A shorter event name usually containing the country or location but no
    no sponsor names. This name is required internally for proper api access.

  - ``EventDate`` | :class:`datetime` |
    The events reference date and time. This is used mainly internally.
    Usually, this is the same as the date of the last session.

  - ``EventFormat`` | :class:`str` |
    The format of the event. One of 'conventional', 'sprint', 'testing'.

  - ``Session*`` | :class:`str` |
    The name of the session. One of 'Practice 1', 'Practice 2', 'Practice 3',
    'Qualifying', 'Sprint Qualifying' or 'Race'.
    Testing sessions are considered practice.
    ``*`` denotes the number of
    the session (1, 2, 3, 4, 5).

  - ``Session*Date`` | :class:`datetime` |
    The date and time at which the session is scheduled to start or was
    scheduled to start.
    ``*`` denotes the number of the session (1, 2, 3, 4, 5).

  - ``F1ApiSupport`` | :class:`bool` |
    Denotes whether this session is supported by the official F1 API.
    Lap timing data and telemetry data can only be loaded if this is true.


Supported Seasons
.................

FastF1 provides its own event schedule for the 2018 season and all later
seasons. The schedule for the all seasons before 2018 is built using data from
the Ergast API. Only limited data is available for these seasons. Usage of the
Ergast API can be enforced for all seasons, in which case the same limitations
apply for the more recent seasons too.

**Exact scheduled starting times for all sessions**:
Supported starting with the 2018 season.
Starting dates for sessions before 2018 (or when enforcing usage of the Ergast
API) assume that each race weekend was held according to the 'conventional'
schedule (Practice 1/2 on friday, Practice 3/Qualifying on Saturday, Race on
Sunday). A starting date and time can only be provided for the race session.
All other sessions are calculated from this and no starting times can be
provided for these. These assumptions will be incorrect for certain events!

**Testing events**: Supported for the 2020 season and later seasons. Not
supported if usage of the Ergast API is enforced.


Event Schedule
..............

- 'conventional': Practice 1, Practice 2, Practice 3, Qualifying, Race
- 'sprint': Practice 1, Qualifying, Practice 2, Sprint, Race
- 'testing': no fixed session order; usually three practice sessions on
  three separate days


.. _SessionIdentifier:

Session identifiers
-------------------

Multiple event (schedule) related functions and methods make use of a session
identifier to differentiate between the various sessions of one event.
This identifier can currently be one of the following:

    - session name abbreviation: ``'FP1', 'FP2', 'FP3', 'Q', 'S',
      'SQ', 'R'``
    - full session name: ``'Practice 1', 'Practice 2',
      'Practice 3', 'Sprint Qualifying', 'Sprint', 'Qualifying', 'Race'``;
      provided names will be normalized, so that the name is
      case-insensitive
    - number of the session: ``1, 2, 3, 4, 5``

Note that 'Sprint' is called 'Sprint Qualifying' only in the 2021 season.
The event name will silently be corrected if you use 'Sprint'/'S' for the 2021
season or 'Sprint Qualifying'/'SQ' for the subsequent seasons.


Functions for accessing schedule data
-------------------------------------

The functions for accessing event schedule data are documented in
:ref:`GeneralFunctions`.


Data Objects
------------


Overview
........


.. autosummary::
    EventSchedule
    Event


API Reference
.............


.. autoclass:: EventSchedule
    :members:
    :undoc-members:
    :show-inheritance:
    :autosummary:


.. autoclass:: Event
    :members:
    :undoc-members:
    :show-inheritance:
    :autosummary:

"""  # noqa: W605 invalid escape sequence (escaped space)
import collections
import datetime
import logging
import warnings
from typing import Union, Optional

import dateutil.parser

with warnings.catch_warnings():
    warnings.filterwarnings(
        'ignore', message="Using slow pure-python SequenceMatcher"
    )
    # suppress that warning, it's confusing at best here, we don't need fast
    # sequence matching and the installation (on windows) requires some effort
    from thefuzz import fuzz

import pandas as pd

from fastf1.api import Cache
from fastf1.core import Session
import fastf1.ergast
from fastf1.utils import recursive_dict_get

_SESSION_TYPE_ABBREVIATIONS = {
    'R': 'Race',
    'Q': 'Qualifying',
    'S': 'Sprint',
    'SQ': 'Sprint Qualifying',
    'FP1': 'Practice 1',
    'FP2': 'Practice 2',
    'FP3': 'Practice 3'
}

_SCHEDULE_BASE_URL = "https://raw.githubusercontent.com/" \
                     "theOehrly/f1schedule/master/"


def get_session(
        year: int,
        gp: Union[str, int],
        identifier: Optional[Union[int, str]] = None,
        *,
        force_ergast: bool = False,
) -> Session:
    """Create a :class:`~fastf1.core.Session` object based on year, event name
    and session identifier.

    .. note:: This function will return a :class:`~fastf1.core.Session`
        object, but it will not load any session specific data like lap timing,
        telemetry, ... yet. For this, you will need to call
        :func:`~fastf1.core.Session.load` on the returned object.

    To get a testing session, use :func:`get_testing_session`.

    Examples:

        Get the second free practice of the first race of 2021 by its session
        name abbreviation::

            >>> get_session(2021, 1, 'FP2')

        Get the qualifying of the 2020 Austrian Grand Prix by full session
        name::

            >>> get_session(2020, 'Austria', 'Qualifying')

        Get the 3rd session if the 5th Grand Prix in 2021::

            >>> get_session(2021, 5, 3)

    Args:
        year: Championship year
        gp: Name as str or round number as int. If gp is
            a string, a fuzzy match will be performed on all events and the
            closest match will be selected.
            Fuzzy matching uses country, location, name and officialName of
            each event as reference.

            Some examples that will be correctly interpreted: 'bahrain',
            'australia', 'abudabi', 'monza'.

            See :func:`get_event_by_name` for some further remarks on the
            fuzzy matching.

        identifier: see :ref:`SessionIdentifier`

        force_ergast: Always use data from the ergast database to
            create the event schedule
    """
    event = get_event(year, gp, force_ergast=force_ergast)
    return event.get_session(identifier)


def get_testing_session(year: int, test_number: int, session_number: int) \
        -> Session:
    """Create a :class:`~fastf1.core.Session` object for testing sessions
    based on year, test  event number and session number.

    Args:
        year: Championship year
        test_number: Number of the testing event (usually at most two)
        session_number: Number of the session withing a specific testing
            event. Each testing event usually has three sessions.

    .. versionadded:: 2.2
    """
    event = get_testing_event(year, test_number)
    return event.get_session(session_number)


def get_event(
        year: int,
        gp: Union[int, str],
        *,
        force_ergast: bool = False,
        strict_search: bool = False
) -> "Event":
    """Create an :class:`~fastf1.events.Event` object for a specific
    season and gp.

    To get a testing event, use :func:`get_testing_event`.

    Args:
        year: Championship year
        gp: Name as str or round number as int. If gp is
            a string, a fuzzy match will be performed on all events and the
            closest match will be selected.
            Fuzzy matching uses country, location, name and officialName of
            each event as reference.
            Note that the round number cannot be used to get a testing event,
            as all testing event are round 0!
        force_ergast: Always use data from the ergast database to
            create the event schedule
        strict_search: Match precisely the query, or default to
            fuzzy search. If no event is found with
            ``strict_search=True``, the function will return None

    .. versionadded:: 2.2
    """
    schedule = get_event_schedule(year=year, include_testing=False,
                                  force_ergast=force_ergast)

    if type(gp) is str:
        event = schedule.get_event_by_name(gp, strict_search=strict_search)
    else:
        event = schedule.get_event_by_round(gp)

    return event


def get_testing_event(year: int, test_number: int) -> "Event":
    """Create a :class:`fastf1.events.Event` object for testing sessions
    based on year and test event number.

    Args:
        year: Championship year
        test_number: Number of the testing event (usually at most two)

    .. versionadded:: 2.2
    """
    schedule = get_event_schedule(year=year)
    schedule = schedule[schedule.is_testing()]

    try:
        assert test_number >= 1
        return schedule.iloc[test_number - 1]
    except (IndexError, AssertionError):
        raise ValueError(f"Test event number {test_number} does not exist")


def get_event_schedule(
        year: int,
        *,
        include_testing: bool = True,
        force_ergast: bool = False
) -> "EventSchedule":
    """Create an :class:`~fastf1.events.EventSchedule` object for a specific
    season.

    Args:
        year: Championship year
        include_testing: Include or exclude testing sessions from the
            event schedule.
        force_ergast: Always use data from the ergast database to
            create the event schedule

    .. versionadded:: 2.2
    """
    if ((year not in range(2018, datetime.datetime.now().year + 1))
            or force_ergast):
        schedule = _get_schedule_from_ergast(year)
    else:
        try:
            schedule = _get_schedule(year)
        except Exception as exc:
            logging.error(f"Failed to access primary schedule backend. "
                          f"Falling back to Ergast! Reason: {exc})")
            schedule = _get_schedule_from_ergast(year)

    if not include_testing:
        schedule = schedule[~schedule.is_testing()]
    return schedule


def get_events_remaining(
        dt: Optional[datetime.datetime] = None,
        *,
        include_testing: bool = True,
        force_ergast: bool = False
) -> 'EventSchedule':
    """Create an :class:`~fastf1.events.EventSchedule` object for remaining season.

    Args:
        dt: Optional DateTime to get events after.
        include_testing: Include or exclude testing sessions from the
            event schedule.
        force_ergast: Always use data from the ergast database to
            create the event schedule

    .. versionadded:: 2.3
    """
    if dt is None:
        dt = datetime.datetime.now()

    events = get_event_schedule(
        dt.year, include_testing=include_testing, force_ergast=force_ergast)
    result = events.loc[events["EventDate"] >= dt]
    return result


def _get_schedule(year):
    response = Cache.requests_get(
        _SCHEDULE_BASE_URL + f"schedule_{year}.json"
    )
    df = pd.read_json(response.text)

    # change column names from snake_case to UpperCamelCase
    col_renames = {col: ''.join([s.capitalize() for s in col.split('_')])
                   for col in df.columns}
    df = df.rename(columns=col_renames)

    schedule = EventSchedule(df, year=year, force_default_cols=True)
    return schedule


def _get_schedule_from_ergast(year) -> "EventSchedule":
    # create an event schedule using data from the ergast database
    season = fastf1.ergast.fetch_season(year)
    data = collections.defaultdict(list)
    for rnd in season:
        data['RoundNumber'].append(int(rnd.get('round')))
        data['Country'].append(
            recursive_dict_get(rnd, 'Circuit', 'Location', 'country')
        )
        data['Location'].append(
            recursive_dict_get(rnd, 'Circuit', 'Location', 'locality')
        )
        data['EventName'].append(rnd.get('raceName'))
        data['OfficialEventName'].append("")

        try:
            date = pd.to_datetime(
                f"{rnd.get('date', '')}T{rnd.get('time', '')}",
            ).tz_localize(None)
        except dateutil.parser.ParserError:
            date = pd.NaT
        data['EventDate'].append(date)

        if 'Sprint' in rnd:
            sprint_name = 'Sprint Qualifying' if year == 2021 else 'Sprint'
            data['EventFormat'].append("sprint")
            data['Session1'].append('Practice 1')
            data['Session1Date'].append(date.floor('D') - pd.Timedelta(days=2))
            data['Session2'].append('Qualifying')
            data['Session2Date'].append(date.floor('D') - pd.Timedelta(days=2))
            data['Session3'].append('Practice 2')
            data['Session3Date'].append(date.floor('D') - pd.Timedelta(days=1))
            data['Session4'].append(sprint_name)
            data['Session4Date'].append(date.floor('D') - pd.Timedelta(days=1))
            data['Session5'].append('Race')
            data['Session5Date'].append(date)
        else:
            data['EventFormat'].append("conventional")
            data['Session1'].append('Practice 1')
            data['Session1Date'].append(date.floor('D') - pd.Timedelta(days=2))
            data['Session2'].append('Practice 2')
            data['Session2Date'].append(date.floor('D') - pd.Timedelta(days=2))
            data['Session3'].append('Practice 3')
            data['Session3Date'].append(date.floor('D') - pd.Timedelta(days=1))
            data['Session4'].append('Qualifying')
            data['Session4Date'].append(date.floor('D') - pd.Timedelta(days=1))
            data['Session5'].append('Race')
            data['Session5Date'].append(date)

        data['F1ApiSupport'].append(True if year >= 2018 else False)
        # simplified; this is only true most of the time

    df = pd.DataFrame(data)
    schedule = EventSchedule(df, year=year, force_default_cols=True)
    return schedule


class EventSchedule(pd.DataFrame):
    """This class implements a per-season event schedule.

    This class is usually not instantiated directly. You should use
    :func:`get_event_schedule` to get an event schedule for a specific
    season.

    Args:
        *args: passed on to :class:`pandas.DataFrame` superclass
        year (int): Championship year
        force_default_cols (bool): Enforce that all default columns and only
            the default columns exist
        **kwargs: passed on to :class:`pandas.DataFrame` superclass
            (except 'columns' which is unsupported for the event schedule)

    .. versionadded:: 2.2
    """

    _COL_TYPES = {
        'RoundNumber': int,
        'Country': str,
        'Location': str,
        'OfficialEventName': str,
        'EventDate': 'datetime64[ns]',
        'EventName': str,
        'EventFormat': str,
        'Session1': str,
        'Session1Date': 'datetime64[ns]',
        'Session2': str,
        'Session2Date': 'datetime64[ns]',
        'Session3': str,
        'Session3Date': 'datetime64[ns]',
        'Session4': str,
        'Session4Date': 'datetime64[ns]',
        'Session5': str,
        'Session5Date': 'datetime64[ns]',
        'F1ApiSupport': bool
    }

    _metadata = ['year']

    _internal_names = pd.DataFrame._internal_names + ['base_class_view']
    _internal_names_set = set(_internal_names)

    def __init__(self, *args, year: int = 0,
                 force_default_cols: bool = False, **kwargs):
        if force_default_cols:
            kwargs['columns'] = list(self._COL_TYPES)
        super().__init__(*args, **kwargs)
        self.year = year

        # apply column specific dtypes
        for col, _type in self._COL_TYPES.items():
            if col not in self.columns:
                continue
            if self[col].isna().all():
                if _type == 'datetime64[ns]':
                    self[col] = pd.NaT
                else:
                    self[col] = _type()
            self[col] = self[col].astype(_type)

    def __repr__(self):
        return self.base_class_view.__repr__()

    @property
    def _constructor(self):
        def _new(*args, **kwargs):
            return EventSchedule(*args, **kwargs).__finalize__(self)

        return _new

    @property
    def _constructor_sliced(self):
        def _new(*args, **kwargs):
            return Event(*args, **kwargs).__finalize__(self)

        return _new

    @property
    def base_class_view(self):
        """For a nicer debugging experience; can view DataFrame through
        this property in various IDEs"""
        return pd.DataFrame(self)

    def is_testing(self):
        """Return `True` or `False`, depending on whether each event is a
        testing event."""
        return pd.Series(self['EventFormat'] == 'testing')

    def get_event_by_round(self, round: int) -> "Event":
        """Get an :class:`Event` by its round number.

        Args:
            round: The round number
        Raises:
            ValueError: The round does not exist in the event schedule
        """
        if round == 0:
            raise ValueError("Cannot get testing event by round number!")
        mask = self['RoundNumber'] == round
        if not mask.any():
            raise ValueError(f"Invalid round: {round}")
        return self[mask].iloc[0]

    def _strict_event_search(self, name: str):
        """
        Match Event Name exactly, ignoring case.
        """

        query = name.lower()
        for i, event in self.iterrows():
            if 'EventName' in event:
                if event['EventName'].lower() == query:
                    return self.loc[i]
        else:
            return None

    def _fuzzy_event_search(self, name: str) -> "Event":

        def _matcher_strings(ev):
            strings = list()
            if 'Location' in ev:
                strings.append(ev['Location'])
            if 'Country' in ev:
                strings.append(ev['Country'])
            if 'EventName' in ev:
                strings.append(ev['EventName'].replace("Grand Prix", ""))
            if 'OfficialEventName' in ev:
                strings.append(ev['OfficialEventName']
                               .replace("FORMULA 1", "")
                               .replace(str(self.year), "")
                               .replace("GRAND PRIX", ""))
            return strings

        max_ratio = 0
        index = 0
        for i, event in self.iterrows():
            ratio = max(
                [fuzz.ratio(val.casefold(), name.casefold())
                 for val in _matcher_strings(event)]
            )
            if ratio > max_ratio:
                max_ratio = ratio
                index = i
        return self.loc[index]

    def get_event_by_name(
            self,
            name: str,
            *,
            strict_search: bool = False
    ) -> "Event":
        """Get an :class:`Event` by its name.

        A fuzzy match is performed to find the event that best matches the
        given name. Fuzzy matching is performed using the country, location,
        name and officialName of each event. This is not guaranteed to return
        the correct result. You should therefore always check if the function
        actually returns the event you had wanted.
        To gurantee the function returns the event queried, toggle
        strict_search, which will only return an event if its event name
        matches (non case sensitive) the query string.

        .. warning:: You should avoid adding common words to ``name`` to avoid
            false string matches.
            For example, you should rather use "Belgium" instead of "Belgian
            Grand Prix" as ``name``.

        Args:
            name: The name of the event. For example,
                ``.get_event_by_name("british")`` and
                ``.get_event_by_name("silverstone")`` will both return the
                event for the British Grand Prix.
            strict_search: Search only for exact query matches
                instead of using fuzzy search. For example,
                ``.get_event_by_name("British Grand Prix", strict_search=True)`` # noqa: E501
                will return the event for the British Grand Prix, whereas
                ``.get_event_by_name("British", strict_search=True)``
                will return ``None``
        """

        if strict_search:
            return self._strict_event_search(name)
        else:
            return self._fuzzy_event_search(name)


class Event(pd.Series):
    """This class represents a single event (race weekend or testing event).

    Each event consists of one or multiple sessions, depending on the type
    of event and depending on the event format.

    This class is usually not instantiated directly. You should use
    :func:`get_event` or similar to get a specific event.

    Args:
          year (int): Championship year
    """
    _metadata = ['year']

    def __init__(self, *args, year: int = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.year = year

    @property
    def _constructor(self):
        def _new(*args, **kwargs):
            return Event(*args, **kwargs).__finalize__(self)

        return _new

    def is_testing(self) -> bool:
        """Return `True` or `False`, depending on whether this event is a
        testing event."""
        return self['EventFormat'] == 'testing'

    def get_session_name(self, identifier) -> str:
        """Return the full session name of a specific session from this event.

        Examples:

            >>> import fastf1
            >>> event = fastf1.get_event(2021, 1)
            >>> event.get_session_name(3)
            'Practice 3'
            >>> event.get_session_name('Q')
            'Qualifying'
            >>> event.get_session_name('praCtice 1')
            'Practice 1'

        Args:
            identifier: see :ref:`SessionIdentifier`

        Raises:
            ValueError: No matching session or invalid identifier
        """
        try:
            num = float(identifier)
        except ValueError:
            # by name or abbreviation
            for name in _SESSION_TYPE_ABBREVIATIONS.values():
                if identifier.casefold() == name.casefold():
                    session_name = name
                    break
            else:
                try:
                    session_name = \
                        _SESSION_TYPE_ABBREVIATIONS[identifier.upper()]
                except KeyError:
                    raise ValueError(f"Invalid session type '{identifier}'")

            # 'Sprint' is called 'Sprint Qualifying' only in 2021
            if (self.year == 2021) and (session_name == 'Sprint'):
                session_name = 'Sprint Qualifying'
            elif (self.year > 2021) and (session_name == 'Sprint Qualifying'):
                session_name = 'Sprint'

            if session_name not in self.values:
                raise ValueError(f"Session type '{identifier}' does not "
                                 f"exist for this event")
        else:
            # by number
            if (float(num).is_integer()
                    and (num := int(num)) in (1, 2, 3, 4, 5)):
                session_name = self[f'Session{num}']
            else:
                raise ValueError(f"Invalid session type '{num}'")
            if not session_name:
                raise ValueError(f"Session number {num} does not "
                                 f"exist for this event")

        return session_name

    def get_session_date(self, identifier: Union[str, int]) \
            -> datetime.datetime:
        """Return the date and time (if available) at which a specific session
        of this event is or was held.

        Args:
            identifier: see :ref:`SessionIdentifier`

        Raises:
            ValueError: No matching session or invalid identifier
        """
        session_name = self.get_session_name(identifier)
        relevant_columns = self.loc[['Session1', 'Session2', 'Session3',
                                     'Session4', 'Session5']]
        mask = (relevant_columns == session_name)
        if not mask.any():
            raise ValueError(f"Session type '{identifier}' does not exist "
                             f"for this event")
        else:
            _name = mask.idxmax()
            date = self[f"{_name}Date"]
            if pd.isnull(date):
                raise ValueError(f"Session type '{identifier}' does not "
                                 f"exist for this event")
            return date

    def get_session(self, identifier: Union[int, str]) -> "Session":
        """Return a session from this event.

        Args:
            identifier: see :ref:`SessionIdentifier`

        Raises:
            ValueError: No matching session or invalid identifier
        """
        try:
            num = float(identifier)
        except ValueError:
            # by name or abbreviation
            session_name = self.get_session_name(identifier)
            if session_name not in self.values:
                raise ValueError(f"Session type '{identifier}' does not "
                                 f"exist for this event")
        else:
            # by number
            if (float(num).is_integer()
                    and (num := int(num)) in (1, 2, 3, 4, 5)):
                session_name = self[f'Session{num}']
            else:
                raise ValueError(f"Invalid session type '{num}'")
            if not session_name:
                raise ValueError(f"Session number {num} does not "
                                 f"exist for this event")

        return Session(event=self, session_name=session_name,
                       f1_api_support=self.F1ApiSupport)

    def get_race(self) -> "Session":
        """Return the race session."""
        return self.get_session('Race')

    def get_qualifying(self) -> "Session":
        """Return the qualifying session."""
        return self.get_session('Qualifying')

    def get_sprint(self) -> "Session":
        """Return the sprint session."""
        return self.get_session('Sprint')

    def get_practice(self, number: int) -> "Session":
        """Return the specified practice session.
        Args:
            number: 1, 2 or 3 - Free practice session number
        """
        return self.get_session(f'Practice {number}')
