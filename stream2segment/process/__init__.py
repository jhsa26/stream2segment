from stream2segment.io.db import close_session
from stream2segment.process.db.models import (Segment, Channel, Event,
                                              Station, DataCenter, Download)
from stream2segment.process.db.sqlevalexpr import exprquery
from stream2segment.process.main import process, imap, SkipSegment
from stream2segment.io import yaml_load  # noqa
from stream2segment.process.db import get_session


def get_segments(dburl, conditions, orderby=None):
    """Return a query object (iterable of `Segment`s) from teh given conditions
    Example of conditions (dict):
    ```
    {
        'id' : '<6',
        'has_data': 'true'
    }
    ```
    :param conditions: a dict of string columns mapped to **string**
        expression, e.g. "column2": "[1, 45]" or "column1": "true" (note:
        string, not the boolean True). A string column is an expression
        denoting an attribute of the reference model class and can include
        relationships.
        Example: if the reference model tablename is 'mymodel', then a string
        column 'name' will refer to 'mymodel.name', 'name.id' denotes on the
        other hand a relationship 'name' on 'mymodel' and will refer to the
        'id' attribute of the table mapped by 'mymodel.name'. The values of
        the dict on the other hand are string expressions in the form
        recognized by `binexpr`. E.g. '>=5', '["4", "5"]' ...
        For each condition mapped to a falsy value (e.g., None or empty
        string), the condition is discarded. See note [*] below for auto-added
        joins  from columns
    :param orderby: a list of string columns (same format
        as `conditions` keys), or a list of tuples where the first element is
        a string column, and the second is either "asc" (ascending) or "desc"
        (descending). In the first case, the order is "asc" by default. See
        note [*] below for auto-added joins from orderby columns
    """
    sess = dburl
    close_sess = False
    try:
        if isinstance(sess, str):
            sess = get_session(dburl)
            close_sess = True
        yield from exprquery(sess.query(Segment), conditions, orderby)
    finally:
        if close_sess:
            close_session(sess)


def get_segment_help(format='html', maxwidth=79, **print_kwargs):
    """Return the :class:`Segment` help (attributes and methods) as string

    :param format: Not supported yet, only html allopwed
    """
    import re, inspect, textwrap
    from itertools import chain
    from stream2segment.io.db.inspection import attnames, get_related_models

    # ======================================================================================
    # Selectable attributes (attributes that can be used in both the instance level
    # and class level for SQL queries) cannot have docs and thus we set the docs here
    # below in the form (attname, description). You can rearrange the attributes as you
    # like (order matters).
    # Falsy descriptions (None, '', False) mean the relative attribute will be hidden
    # from the doc. Otherwise, a description should start always with the Python type
    # (see below) and be in plain text with "\n", * (italic) and ** (bold)
    # allowed (but newlines it might not be rendered in markdowns tables)
    # ======================================================================================

    _SELECTABLE_ATTRS = [
        ["id", "int: segment (unique) db id"],
        ["has_data", "bool: if the segment waveform data is not empty, i.e. it has "
                     "at least 1 byte of data saved. This parameter or `has_valid_data` "
                     "are often necessary in segment selection, e.g.: \n"
                     "has_data: 'true'\n"
                     "Empty segments are those whose server did not return any data "
                     "and are stored anyway for collecting stats and allow to "
                     "customize what should be re-downloaded in further attempts"],
        ["has_valid_data", "bool: if the segment waveform data is not empty and "
                           "could be successfully read as miniSEED during "
                           "download. Often necessary in segment selection, e.g.: \n"
                           "has_valid_data: 'true'"],
        ["event_distance_deg", "float: distance between the segment station and the "
                               "event, in degrees"],
        ["event_distance_km", "float: distance between the segment station and the "
                              "event, in km, assuming a perfectly spherical earth "
                              "with a radius of 6371 km"],
        ["start_time", "datetime.datetime: waveform start time"],
        ["arrival_time", "datetime.datetime: waveform arrival time (value between "
                         "'start_time' and 'end_time')"],
        ["end_time", "datetime.datetime: waveform end time"],
        ["request_start", "datetime.datetime: waveform requested start time"],
        ["request_end", "datetime.datetime: waveform requested end time"],
        ["duration_sec", "float: waveform data duration, in seconds"],
        ["missing_data_sec", "float: number of seconds of missing data, as ratio of "
                             "the requested time window. It might also be negative "
                             "(more data received than requested). Useful in segment "
                             "selection: e.g., if we requested 5 minutes of data and "
                             "we want to process segments with at least 4 minutes of "
                             "downloaded data, then: missing_data_sec: '< 60'"],
        ["missing_data_ratio", "float: portion of missing data, as ratio of the "
                               "requested time window. It might also be negative "
                               "(more data received than requested). Useful in "
                               "segment selection: e.g., to process segments whose "
                               "time window is at least 90% of the requested one: "
                               "missing_data_ratio: '< 0.1'"],
        ["sample_rate", "float: waveform sample rate. It might differ from the "
                        "segment channel sample_rate"],
        ["maxgap_numsamples", "float: maximum gap/overlap (G/O) found in the waveform, "
                              "in number of points. If\n"
                              "0: segment has no G/O\n"
                              ">=1: segment has gaps\n"
                              "<=-1: segment has overlaps.\n"
                              "Values in (-1, 1) are difficult to interpret: a rule "
                              "of thumb is to consider no G/O if values are within "
                              "-0.5 and 0.5. Useful in segment selection: e.g., to "
                              "process segments with no gaps/overlaps:\n"
                              "maxgap_numsamples: '(-0.5, 0.5)'"],
        ["seed_id", "str: the seed identifier in the typical format "
                    "[Network].[Station].[Location].[Channel]. For segments with "
                    "waveform data, `data_seed_id` (see below) might be faster to "
                    "fetch."],
        ["data_seed_id", "str: same as 'segment.seed_id', but faster to get because "
                         "it reads the value stored in the waveform data. The "
                         "drawback is that this value is null for segments with no "
                         "waveform data"],
        ["classlabels_count", "int: the number of class labels assigned "
                              "to this segment"],
        ["data", "bytes: the waveform (raw) data. Used by `segment.stream()`"],
        ["queryauth", "bool: if the segment download required authentication "
                      "(data is restricted)"],
        ["download_code", None],  # <- IGNORED
        # ["event", "object (attributes below)"],
        ["event.id", "int"],
        ["event.event_id", "str: the id returned by the web service or catalog"],
        ["event.time", "datetime.datetime"],
        ["event.latitude", "float"],
        ["event.longitude", "float"],
        ["event.depth_km", "float"],
        ["event.author", "str"],
        ["event.catalog", "str"],
        ["event.contributor", "str"],
        ["event.contributor_id", "str"],
        ["event.mag_type", "str"],
        ["event.magnitude", "float"],
        ["event.mag_author", "str"],
        ["event.event_location_name", "str"],
        ['event.event_type', 'str: the event type (e.g. "earthquake")'],
        # ["channel", "object (attributes below)"],
        ["channel.id", "int"],
        ["channel.location", "str"],
        ["channel.channel", "str"],
        ["channel.depth", "float"],
        ["channel.azimuth", "float"],
        ["channel.dip", "float"],
        ["channel.sensor_description", "str"],
        ["channel.scale", "float"],
        ["channel.scale_freq", "float"],
        ["channel.scale_units", "str"],
        ["channel.sample_rate", "float"],
        ["channel.band_code", "str: the first letter of channel.channel"],
        ["channel.instrument_code", "str: the second letter of channel.channel"],
        ["channel.orientation_code", "str: the third letter of channel.channel"],
        ["channel.band_instrument_code", "str: the first two letters of channel.channel"],
        # ["channel.station", "object: same as segment.station (see below)"],
        # ["station", "object (attributes below)"],
        ["station.id", "int"],
        ["station.network", "str: the station's network code, e.g. 'AZ'"],
        ["station.station", "str: the station code, e.g. 'NHZR'"],
        ["station.netsta_code", "str: the network + station code, concatenated with "
                                "the dot, e.g.: 'AZ.NHZR'"],
        ["station.latitude", "float"],
        ["station.longitude", "float"],
        ["station.elevation", "float"],
        ["station.site_name", "str"],
        ["station.start_time", "datetime.datetime"],
        ["station.end_time", "datetime.datetime"],
        ["station.has_inventory", "bool: tells if the segment's station inventory "
                                  "has data saved (at least one byte of data). "
                                  "Useful in segment selection. E.g., to process "
                                  "only segments with inventory downloaded:\n"
                                  "station.has_inventory: 'true'"],
        ["station.datacenter", "object (same as segment.datacenter, see below)"],
        # ["datacenter", "object (attributes below)"],
        ["datacenter.id", "int"],
        ["datacenter.station_url", "str"],
        ["datacenter.dataselect_url", "str"],
        ["datacenter.organization_name", "str"],
        # ["download", "object (attributes below): the download execution"],
        ["download.id", "int"],
        ["download.run_time", "datetime.datetime"],
        ["classes.id", "int: the id(s) of the class labels assigned to the segment"],
        ["classes.label", "int: the unique name(s) of the class labels assigned to "
                          "the segment"],
        ["classes.description", "int: the description(s) of the class labels "
                                "assigned to the segment"],
        # attrs mapped to None are ignored:
        ["station.inventory_xml", None], # bytes
        ["download.log", None], # str
        ["download.warnings", None], # int
        ["download.errors", None], # int
        ["download.config", None], # str
        ["download.program_version", None], # str
    ]

    # Prepare a list of strings (aname, socstring) tuples:
    table = []

    # Append selectable attributes:
    table += [('**Selectable attributes**', '**Type and optional description**')]
    table += [_ for _ in _SELECTABLE_ATTRS if _[1]]

    # Append Standard methods/ attributes:
    table += [('**Standard attributes or methods**', '**Description**')]
    # Define the main attributes/methods to be shown first (those not listed
    # below will simply be shown next):
    _MAIN_ATTS = ('stream', 'inventory', 'url', 'sds_path', 'dbsession')
    # Before looping through the Segment class, define what to skip:
    skip_attrs = set(attnames(Segment)) | {'metadata'}  # <- reserved att names
    signatures = {}
    # Now loop:
    for aname in chain(_MAIN_ATTS, dir(Segment)):
        if aname[:1] == '_' or aname in skip_attrs:
            continue
        # if aname is in _MAIN_ATTRS, avoid displaying it twice later
        # when handling dir(Segment):
        skip_attrs.add(aname)
        try:
            att = getattr(Segment, aname)
            docstr = (att.__doc__ or '').strip()
            if not docstr:
                continue
            # Append the method/ attribute for the moment:
            table.append((aname, docstr))
            # Get `att` signature, if method (<=> is callable):
            if callable(att):
                sig_str = '()'
                sig = inspect.signature(att)
                if len(sig.parameters) > 1:
                    sig_str = "(" + str(sig)[7:]  # remove "(self, "
                # sig_str might have special characters (*, **) which should
                # not be confused with their markdown meaning (italic, bold)
                # this is why we do not add `sig_str` to `aname` but keep all
                # signatures in a separate dict for the moment:
                signatures[aname] = sig_str
        except Exception:  # getattr might fail (e.g. for hybrid properties with no expr)
            pass

    format = format or ''

    lines = []
    # one format supported for the moment (html):
    if format.lower() in ('html', 'htm'):
        pre_code_re = re.compile(r'\n*```\n*(.*?)\n*```\n*', re.DOTALL)
        code_re = re.compile('`(.*?)`')
        br_re = re.compile('\n')
        b_re = re.compile(r'\*\*(.+?)\*\*')
        i_re = re.compile(r'\*(.+?)\*')
        param_re = re.compile(r'\:param (\w+)\:', re.MULTILINE)
        link_re = re.compile(r'(https?:\/\/[\w\~\-\.\?\&\=\%\/\#]+)',
                             re.IGNORECASE | re.MULTILINE)
        raises_re = re.compile(r'\:raises?\:')

        def convert(string):
            search = pre_code_re.search(string)
            if search and search.group(1):
                string = convert(string[:search.start()]) + \
                    '<p><pre><code>' +\
                    textwrap.dedent(search.group(1)) + '</code></pre></p>' +\
                    convert(string[search.end():])
            else:
                # string = pre_code_re.sub('<code>\\1</code>', string)
                string = code_re.sub('<code>\\1</code>', string)
                string = b_re.sub('<b>\\1</b>', string)
                string = i_re.sub('<i>\\1</i>', string)
                string = br_re.sub('<br/>', string)
                string = param_re.sub('<i>Parameter</i> <b>\\1</b>:', string)
                string = link_re.sub('<a target="_blank" href="\\1">\\1</a>', string)
                string = raises_re.sub('<i>Raises</i>', string)
            return string

        if maxwidth and maxwidth > 0:
            lines.append('<table class="s2s-segment-summary-table" '
                         'style="max-width:%dem;">' % maxwidth)
        else:
            lines.append('<table>')
        for aname, aval in table:
            if not aval:
                continue  # safety check (shoulw not happen)
            attname = '<span>{0}</span>'.format(convert(aname))
            if aname in signatures:
                attname = attname.replace(aname, aname+signatures[aname])
            # replace markdown with html:
            attval = convert(aval)
            # notebook prints everything right aligned. So let's force left align:
            # style = 'style="text-align:left"'
            style_td = 'style="text-align:left; border-width:1px; border-style:solid"'
            lines.append('<tr><td {0}>{1}</td><td {0}>{2}</td></tr>'.format(style_td,
                                                                            attname,
                                                                            attval))
        lines.append('</table>')
    else:
        raise ValueError('format "%s" not supported' % format)

    return '\n'.join(lines)
