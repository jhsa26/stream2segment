# -*- coding: utf-8 -*-
# from __future__ import print_function

"""query_utils: utilities of the package

   :Platform:
       Mac OSX, Linux
   :Copyright:
       Deutsches GFZ Potsdam <XXXXXXX@gfz-potsdam.de>
   :License:
       To be decided!
"""

# standard imports:
from StringIO import StringIO
import sys
import logging
# import logging
# from matplotlib.dates import date2num
# from datetime import datetime
from datetime import timedelta, datetime
from stream2segment.utils import EstRemTimer, url_read, tounicode
from stream2segment import io as s2sio
from stream2segment import __version__ as program_version
import numpy as np
import pandas as pd
# third party imports:
# from obspy.taup.taup import getTravelTimes
from obspy.taup import TauPyModel
from obspy.geodetics import locations2degrees
from obspy.taup.helper_classes import TauModelError


def get_min_travel_time(source_depth_in_km, distance_in_degree, model='ak135'):  # FIXME: better!
    """
        Assess and return the travel time of P phases.
        Uses obspy.getTravelTimes
        :param source_depth_in_km: Depth in kilometer.
        :type source_depth_in_km: float
        :param distance_in_degree: Distance in degrees.
        :type distance_in_degree: float
        :param model: Either ``'iasp91'`` or ``'ak135'`` velocity model.
         Defaults to 'ak135'.
        :type model: str, optional
        :return the number of seconds of the assessed arrival time, or None in case of error
        :raises: ValueError (wrapping TauModel error in case)
    """
    taupmodel = TauPyModel(model)
    try:
        tt = taupmodel.get_travel_times(source_depth_in_km, distance_in_degree)
        # return min((ele['time'] for ele in tt if (ele.get('phase_name') or ' ')[0] == 'P'))
        return min((ele.time for ele in tt))
    except (TauModelError, ValueError) as err:
        raise ValueError(("Unable to find minimum travel time (dist=%s, depth=%s, model=%s). "
                          "Source error: %s: %s"),
                         str(distance_in_degree), str(source_depth_in_km), str(model),
                         err.__class__.__name__, str(err))


def get_arrival_time(distance_in_degrees, ev_depth_km, ev_time):
    """
        Returns the tuple w,c where w is the waveform from the given parameters, and c is the
        relative channel
        :param distance_in_degrees: the distance in degrees
        :type distance_in_degrees: float. See obspy.locations2degrees
        :param dc: the datacenter to query from
        :type dc: string
        :param st: the station to query from
        :type st: string
        :param listCha: the list of channels, e.g. ['HL?', 'SL?', 'BL?']. The function iterates
            over the given channels and returns the first available data
        :type listCha: iterable (e.g., list)
        :param arrivalTime: the query time. The request will be built with a time start and end of
            +-minBeforeP (see below) minutes from arrivalTime
        :type arrivalTime: date or datetime
        :param minBeforeP: the minutes before P wave arrivalTime
        :type minBeforeP: float
        :param minAfterP: the minutes after P wave arrivalTime
        :type minAfterP: float
        :return: the tuple data, channel (bytes and string)
        :raises: ValueError
    """
    travel_time = get_min_travel_time(ev_depth_km, distance_in_degrees)
    arrivalTime = ev_time + timedelta(seconds=float(travel_time))
    return arrivalTime


def get_arrival_times(distances_series, ev_depth_km, ev_time, col_name=None):
    """returns a Series object """
    def atime(dista):
        try:
            return get_arrival_time(dista, ev_depth_km, ev_time)
        except ValueError:
            return None
            # logging.info('arrival time error: %s' % str(verr))
            # continue
    return distances_series.apply(atime)


def get_time_range(origTime, days=0, hours=0, minutes=0, seconds=0):
    """
        Returns the tuple (origTime - timeDeltaBefore, origTime + timeDeltaAfter), where the deltas
        are built according to the given parameters. Any of the parameters can be an int
        OR an iterable (list, tuple) of two elements specifying the days before and after,
        respectively

        :Example:
            - get_time_range(t, seconds=(1,2)) returns the tuple with elements:
                - t minus 1 second
                - t plus 2 seconds
            - get_time_range(t, minutes=4) returns the tuple with elements:
                - t minus 4 minutes
                - t plus 4 minutes
            - get_time_range(t, days=1, seconds=(1,2)) returns the tuple with elements:
                - t minus 1 day and 1 second
                - t plus 1 day and 2 seconds

        :param days: the day shift from origTime
        :type days: integer or tuple of positive integers (of length 2)
        :param minutes: the minutes shift from origTime
        :type minutes: integer or tuple of positive integers (of length 2)
        :param seconds: the second shift from origTime
        :type seconds: integer or tuple of positive integers (of length 2)
        :return: the tuple (timeBefore, timeAfter)
        :rtype: tuple of datetime objects (timeBefore, timeAfter)
    """
    td1 = []
    td2 = []
    for val in (days, hours, minutes, seconds):
        try:
            td1.append(val[0])
            td2.append(val[1])
        except TypeError:
            td1.append(val)
            td2.append(val)

    start = origTime - timedelta(days=td1[0], hours=td1[1], minutes=td1[2], seconds=td1[3])
    endt = origTime + timedelta(days=td2[0], hours=td2[1], minutes=td2[2], seconds=td2[3])
    return start, endt


def get_search_radius(mag, mmin=3, mmax=7, dmin=1, dmax=5):  # FIXME: better!
    """From a given magnitude, determines and returns the max radius (in degrees).
        Given dmin and dmax and mmin and mmax (FIXME: TO BE CALIBRATED!),
        this function returns D from the f below:

             |
        dmax +                oooooooooooo
             |              o
             |            o
             |          o
        dmin + oooooooo
             |
             ---------+-------+------------
                    mmin     mmax

    """
    if mag < mmin:
        radius = dmin
    elif mag > mmax:
        radius = dmax
    else:
        radius = dmin + (dmax - dmin) / (mmax - mmin) * (mag - mmin)
    return radius


def get_events(**kwargs):
    """
        Returns a tuple of two elements: the first one is the DataFrame representing the stations
        read from the specified arguments. The second is the the number of rows (denoting stations)
        which where dropped from the url query due to errors in parsing
        :param kwargs: a variable length list of arguments, including:
            eventws (string): the event web service
            minmag (float): the minimum magnitude
            start (string): the event start, in string format (e.g., datetime.isoformat())
            end (string): the event end, in string format (e.g., datetime.isoformat())
            minlon (float): the event min longitude
            maxlon (float): the event max longitude
            minlat (float): the event min latitude
            maxlat (float): the event max latitude
        :raise: ValueError, TypeError, IOError
    """
    eventQuery = ('%(eventws)squery?minmagnitude=%(minmag)1.1f&start=%(start)s'
                  '&minlon=%(minlon)s&maxlon=%(maxlon)s&end=%(end)s'
                  '&minlat=%(minlat)s&maxlat=%(maxlat)s&format=text') % kwargs

    result = url_read(eventQuery, decoding='utf8')

    return evt_to_dframe(result)


def evt_to_dframe(event_query_result):
    """
        :return: the tuple dataframe, dropped_rows (int >=0)
        raises: ValueError
    """
    dfr = query2dframe(event_query_result)
    oldlen = len(dfr)
    if not dfr.empty:
        for key, cast_func in {'Time': pd.to_datetime,
                               'Depth/km': pd.to_numeric,
                               'Latitude': pd.to_numeric,
                               'Longitude': pd.to_numeric,
                               'Magnitude': pd.to_numeric,
                               }.iteritems():
            dfr[key] = cast_func(dfr[key], errors='coerce')

        dfr.dropna(inplace=True)

    return dfr, oldlen - len(dfr)


def get_stations(dc, listCha, origTime, lat, lon, max_radius):
    """
        Returns a tuple of two elements: the first one is the DataFrame representing the stations
        read from the specified arguments. The second is the the number of rows (denoting stations)
        which where dropped from the url query due to errors in parsing
        :param dc: the datacenter
        :type dc: string
        :param listCha: the list of channels, e.g. ['HL?', 'SL?', 'BL?'].
        :type listCha: iterable (e.g., list)
        :param origTime: the origin time. The request will be built with a time start and end of +-1
            day from origTime
        :type origTime: date or datetime
        :param lat: the latitude
        :type lat: float
        :param lon: the longitude
        :type lon: float
        :param max_radius: the radius distance from lat and lon, in degrees FIXME: check!
        :type max_radius: float
        :return: the DataFrame representing the stations, and the stations dropped (int)
        :raise: ValueError, TypeError, IOError
    """

    start, endt = get_time_range(origTime, days=1)
    stationQuery = ('%s/station/1/query?latitude=%3.3f&longitude=%3.3f&'
                    'maxradius=%3.3f&start=%s&end=%s&channel=%s&format=text&level=station')
    aux = stationQuery % (dc, lat, lon, max_radius, start.isoformat(),
                          endt.isoformat(), ','.join(listCha))
    dcResult = url_read(aux, decoding='utf8')
    return station_to_dframe(dcResult)


def station_to_dframe(stations_query_result):
    """
        :return: the tuple dataframe, dropped_rows (int >=0)
        raises: ValueError
    """
    dfr = query2dframe(stations_query_result)
    oldlen = len(dfr)
    if not dfr.empty:
        for key, cast_func in {'StartTime': pd.to_datetime,
                               'Elevation': pd.to_numeric,
                               'Latitude': pd.to_numeric,
                               'Longitude': pd.to_numeric,
                               }.iteritems():
            dfr[key] = cast_func(dfr[key], errors='coerce')

        dfr.dropna(inplace=True)
        dfr['EndTime'] = pd.to_datetime(dfr['EndTime'], errors='coerce')

    return dfr, oldlen - len(dfr)


def query2dframe(query_result_str):
    """
        Returns a pandas dataframne fro the given query_result_str
        :param: query_result_str
        :raise: ValueError in case of errors
    """
    if not query_result_str:
        return pd.DataFrame()

    events = query_result_str.splitlines()

    data = None
    columns = [e.strip() for e in events[0].split("|")]
    for ev in events[1:]:
        evt_list = ev.split('|')
        # Use numpy and then build the dataframe
        # For info on other solutions:
        # http://stackoverflow.com/questions/10715965/add-one-row-in-a-pandas-dataframe:
        if data is None:
            data = [evt_list]
        else:
            data = np.append(data, [evt_list], axis=0)

    if data is not None:
        # check that data rows and columns have the same length
        # cause DataFrame otherwise might do some weird stuff (e.g., one
        # column and rows of N>1 elemens, the DataFrame is built with
        # a single column packing those N elements as list in it)
        # Note that if we are here we are sure data rows are the same length
        np.append(data, [columns], axis=0)

    return pd.DataFrame(data=data, columns=columns)


def get_wav_query(dc, channel, station_name, start_time, end_time):
    qry = '%s/dataselect/1/query?station=%s&channel=%s&start=%s&end=%s'
    return qry % (dc, station_name, channel, start_time.isoformat(), end_time.isoformat())


def get_wav_queries(dc_series, channel_series, station_name_series, start_time_series,
                    end_time_series):
    val = np.array([dc_series.values, channel_series.values, station_name_series.values,
                    start_time_series.values, end_time_series.values])

    def getwq(arg):
        return get_wav_query(*arg)
    ret_val = np.apply_along_axis(getwq, axis=0, arr=val)
    return pd.Series(ret_val)


def get_distances(latitude_series, longitude_series, ev_lat, ev_lon):
    """returns a Series object """
    return pd.DataFrame({'lat': latitude_series,
                         'lon': longitude_series}).apply(lambda row: locations2degrees(ev_lat,
                                                                                       ev_lon,
                                                                                       row['lat'],
                                                                                       row['lon']),
                                                         axis=1)


def get_time_ranges(arrival_times_series, days=0, hours=0, minutes=0, seconds=0):
    """returns two series objects with 'StartTime' 'EndTime' """
    def func(val):
        try:
            a, b = get_time_range(val['start'], days=days, hours=hours, minutes=minutes,
                                  seconds=seconds)
        except TypeError:
            a, b = None, None
        val['start'], val['end'] = a, b
        return val
    # FIXME: as we are modifying the data frame, try not to reutnr anything and not assign apply
    # (just call it), it should work
    retval = pd.DataFrame({'start': arrival_times_series,
                           'end': arrival_times_series}).apply(func, axis=1)
    # http://pandas.pydata.org/pandas-docs/stable/dsintro.html#name-attribute
    # The Series name will be assigned automatically in many cases, in particular when taking 1D
    # slices of DataFrame (as it is now). Problem: the constructor
    # (pd.DataFrame(series, columns=[new_col]) will produce a DataFrame with  NaN data in it if
    # new_col is not the same as series name. Solution 1: use pd.dataFrame({'new_name':series}) but
    # for safety there is also the rename method:
    return retval['start'].rename(None), retval['end'].rename(None)


def read_wav_data(query_str):
    try:
        return url_read(query_str)
    except (IOError, ValueError, TypeError) as _:
        return None


def read_wavs_data(query_series, logger=None, ert=None):
    def func_dwav(query_str):
        data = read_wav_data(query_str)
        if logger is not None or ert is not None:
            num = ("%d: " % ert.done) if ert else ""
            msg = "%s%d bytes downloaded from: %s" % (num, len(data), query_str)
            if logger is not None:
                logger.debug(msg)
            if ert is not None:
                ert.print_progress(epilog=msg)
        return data

    return query_series.apply(func_dwav)


def pd_str(dframe):
    with pd.option_context('display.max_rows', len(dframe),
                           'display.max_columns', len(dframe.columns),
                           'max_colwidth', 50, 'expand_frame_repr', False):
        return str(dframe)


class LoggerHandler(object):
    """Object handling the root loggers and two Handlers: one writing to StringIO (verbose, being
    saved to db) the other writing to stdout (or stdio) (less verbose, not saved).
    This class has all four major logger methods info, warning, debug and error, plus a save
    method to save the logger text to a database"""
    def __init__(self, out=sys.stdout):
        """
            Initializes a new LoggerHandler, attaching to the root logger two handlers
        """
        rootLogger = logging.getLogger()
        rootLogger.setLevel(10)
        stringio = StringIO()
        fileHandler = logging.StreamHandler(stringio)  # stream=StringIO())
        # fileHandler.setLevel(10)
        rootLogger.addHandler(fileHandler)
        consoleHandler = logging.StreamHandler(out)
        consoleHandler.setLevel(20)
        rootLogger.addHandler(consoleHandler)
        self.rootlogger = rootLogger
        self.errors = 0
        self.warnings = 0
        self.stringio = stringio

    def info(self, *args, **kw):
        """forwards the arguments to L.info, where L is the root Logger"""
        self.rootlogger.info(*args, **kw)

    def debug(self, *args, **kw):
        """forwards the arguments to L.debug, where L is the root Logger"""
        self.rootlogger.debug(*args, **kw)

    def warning(self, *args, **kw):
        """forwards the arguments to L.debug (with "WARNING: " inserted at the beginning of the log
        message), where L is the root logger. This allows this kind of log messages
        to be printed to the db log but NOT on the screen (less verbose)"""
        args = list(args)  # it's a tuple ...
        args[0] = "WARNING: " + args[0]
        self.warnings += 1
        self.rootlogger.debug(*args, **kw)

    def error(self, *args, **kw):
        """forwards the arguments to L.error, where L is the root Logger"""
        self.errors += 1
        self.rootlogger.error(*args, **kw)

    def to_df(self, seg_found, seg_written, close_stream=True):
        """Saves the logger informatuon to database"""
#         db_handler.write(pd.DataFrame([[datetime.utcnow(), tounicode(self.stringio.getvalue()),
#                                         self.warnings, self.errors, str(program_version)]],
#                                       columns=["Time", "Log", "Warnings", "Errors",
#                                                "ProgramVersion"]
#                                       ), "logs", "Time")
        pddf = pd.DataFrame([[datetime.utcnow(), tounicode(self.stringio.getvalue()), self.warnings,
                              self.errors, seg_found, seg_written, seg_found - seg_written,
                              ".".join(str(v) for v in program_version)]],
                            columns=["Time", "Log", "Warnings", "Errors", "SegmentsFound",
                                     "SegmentsWritten", "SegmentsSkipped", "ProgramVersion"])
        if close_stream:
            self.stringio.close()
        return pddf


def save_waveforms(eventws, minmag, minlat, maxlat, minlon, maxlon, search_radius_args,
                   datacenters_dict, channelList, start, end, ptimespan, outpath):
    """
        Downloads waveforms related to events to a specific path
        :param eventws: Event WS to use in queries. E.g. 'http://seismicportal.eu/fdsnws/event/1/'
        :type eventws: string
        :param minmaa: Minimum magnitude. E.g. 3.0
        :type minmaa: float
        :param minlat: Minimum latitude. E.g. 30.0
        :type minlat: float
        :param maxlat: Maximum latitude E.g. 80.0
        :type maxlon: float
        :param minlon: Minimum longitude E.g. -10.0
        :type minlon: float
        :param maxlon: Maximum longitude E.g. 60.0
        :type maxlon: float
        :param search_radius_args: The arguments required to get the search radius R whereby all
            stations within R will be queried from a given event location E_lat, E_lon
        :type search_radius_args: list or iterable of numeric values:
            (min_magnitude, max_magnitude, min_distance, max_distance)
        :param datacenters_dict: a dict of data centers as a dictionary of the form
            {name1: url1, ..., nameN: urlN} where url1, url2,... are strings
        :type datacenters_dict dict of key: string entries
        :param channelList: iterable (e.g. list) of channels. Each channels is in turn an iterable
            of strings, e.g. ['HH?', 'SH?', 'BH?']
            Thus, channelList might be [['HH?', 'SH?', 'BH?'], ['HN?', 'SN?', 'BN?']]
        :type channelList: iterable of iterables of strings
        :param start: Limit to events on or after the specified start time
            E.g. (date.today() - timedelta(days=1))
        :type start: datetime or string, as returned from datetime.isoformat() FIXME: STRING NOT IMPLEMENTED!
        :param end: Limit to events on or before the specified end time
            E.g. date.today().isoformat()
        :type end: datetime or string, as returned from datetime.isoformat() FIXME: STRING NOT IMPLEMENTED!
        :param ptimespan: the minutes before and after P wave arrival for the waveform query time
            span
        :type ptimespan: iterable of two float
        :param outpath: path where to store mseed files E.g. '/tmp/mseeds'
        :type outpath: string
    """
    _args_ = dict(locals())  # this must be the first statement, so that we catch all arguments and
    # no local variable (none has been declared yet). Note: dict(locals()) avoids problems with
    # variables created inside loops, when iterating over _args_ (see below)

    logger = LoggerHandler()

    # print local vars:
    logger.info("Arguments:")
    for arg, varg in _args_.iteritems():
        msg = "\t%s = %s" % (str(arg), str(varg))
        logger.info(msg)

    # a little bit hacky, but convert to dict as the function gets dictionaries
    # Note: we might want to use dict(locals()) as above but that does NOT
    # preserve order and tests should be rewritten. It's too much pain for the moment
    args = {"eventws": eventws,
            "minmag": minmag,
            "minlat": minlat,
            "maxlat": maxlat,
            "minlon": minlon,
            "maxlon": maxlon,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "outpath": outpath}

    logger.debug("")
    logger.info("Querying Event WS:")

    # initialize our Database handler:
    try:
        db_handler = s2sio.DbHandler(outpath)
    except IOError as err:
        logger.error(str(err))
        logger.save(db_handler)
        return 1

    try:
        events, skipped = get_events(**args)
        # raise ValueError()
    except (IOError, ValueError, TypeError) as err:
        logger.error(str(err))
        logger.save(db_handler)
        return 1
    else:
        if skipped > 0:
            logger.warning(("%d events skipped (possible cause: bad formatting, "
                            "e.g. invalid datetimes or numbers") % skipped)

    logger.info('%s events found', len(events))
    logger.debug('Events: %s', pd_str(events))

    wav_dframe = None

    ert = EstRemTimer(len(events) * len(datacenters_dict) * len(channelList))

    logger.debug("")
    msg = "Querying Station WS:"
    logger.info(msg)

    for ev in events.values:  # FIXME: use str labels?
        ev_mag = ev[10]
        ev_id = ev[0]
        ev_loc_name = ev[12]
        ev_time = ev[1]
        ev_lat = ev[2]
        ev_lon = ev[3]
        ev_depth_km = ev[4]

        max_radius = get_search_radius(ev_mag,
                                       search_radius_args[0],
                                       search_radius_args[1],
                                       search_radius_args[2],
                                       search_radius_args[3])

        for DCID, dc in datacenters_dict.iteritems():
            for chName, chList in channelList.iteritems():

                msg = "Event %s (%s): querying stations within %f deg. to %s (channels: %s))" % \
                    (ev_id, ev_loc_name, max_radius, DCID, str(chList))

                logger.debug("")
                logger.debug(msg)
                ert.print_progress(epilog=msg)

                try:
                    stations, skipped = get_stations(dc, chList, ev_time, ev_lat, ev_lon,
                                                     max_radius)
                except (IOError, ValueError, TypeError) as exc:
                    logger.warning(exc.__class__.__name__ + ": " + str(exc))
                    continue

                logger.debug('%d stations found (data center: %s, channel: %s)',
                             len(stations), str(DCID), str(chList))

                if skipped > 0:
                    logger.warning(("%d stations skipped (possible cause: bad formatting, "
                                    "e.g. invalid datetimes or numbers") % skipped)

                if stations.empty:
                    continue

                logger.debug("Downloaded stations:")
                logger.debug(pd_str(stations))

                # Do the core calculation now...
                # Calculate distances, arrival times and time ranges
                distances = get_distances(stations['Latitude'], stations['Longitude'], ev_lat,
                                          ev_lon)
                arr_times = get_arrival_times(distances, ev_depth_km, ev_time)
                start_times, end_times = get_time_ranges(arr_times, minutes=ptimespan)
                # concat all together:
                atime_col = "ArrivalTime"
                dist_col = "Distance_Event_Station/deg"
                stime_col = "DataStartTime"
                etime_col = "DataEndTime"

                # NOTE: start_times and end_times are NAMED series. Thus this sets a dataframe of
                # empty values:
                # pd.DataFrame(start_times, columns=[stime_col]) if stime_col name is different
                # than start_times name (it is the case)
                # this works (reassign the label):
                # pd.DataFrame(stime_col: start_times)
                wdf = pd.concat([pd.DataFrame({stime_col: start_times}),
                                 pd.DataFrame({etime_col: end_times}),
                                 pd.DataFrame({atime_col: arr_times}),
                                 pd.DataFrame({dist_col: distances}),
                                 stations], axis=1)  # , ignore_index=True)
                # NOTE ABOVE: FIXME: do not use ignore_index otherwise column names are lost
                # BUT: what if we have the same index? check!

                # dropna D from distances, arr_times, time_ranges which are na
                # FIXME: print to debug the removed dframe? do the same for stations and events df?
                dict_ = {(dist_col,): "station-event distance",
                         (atime_col,): "arrival time",
                         (stime_col, etime_col): "time-range around arrival time"}
                for subset, reason in dict_.iteritems():
                    _l_ = len(wdf)
                    wdf.dropna(subset=subset, inplace=True)
                    _l_ -= len(wdf)
                    if _l_ > 0:
                        logger.warning("%d stations removed (reason %s)" % (_l_, reason))

                # create channel column: expand D by 3, in such a way that for each row R at
                # position i, two new rows (copy of R) are inserted at i+1 and i+2
                wdf = pd.DataFrame(np.repeat(wdf.values, len(chList), axis=0), columns=wdf.columns)
                wdf.reset_index(inplace=True, drop=True)
                # add channels column at position 0 (first one for the moment):
                wdf.insert(0, 'Channel', '')
                # populate channels column. Assuming channels is ['a', 'B'], then the newly created
                # channel column values (from top to bottom) should be: a,B,a,B,a,B,...
                for i in xrange(len(chList)):
                    wdf.loc[wdf.index % len(chList) == i, 'Channel'] = chList[i]

                # add event id column at position 0
                wdf.insert(0, '#EventID', ev_id)

                colpos = len(wdf.columns) - len(stations.columns)
                # set a column position from which to add next columns
                # Basically from here on append them at the end so that
                # inspecting the table with some tool the relevant ones are first)
                # add single valued columns:
                for col_name, col_val in [('DataCenter', dc), ('Location', ''), ('ClassLabel', '')]:
                    wdf.insert(colpos, col_name, col_val)
                    colpos += 1

                # add the query string
                wdf.insert(colpos, 'QueryStr', get_wav_queries(wdf['DataCenter'], wdf['Channel'],
                                                               wdf['Station'], wdf['DataStartTime'],
                                                               wdf['DataEndTime']))

                # skip when the dataframe is empty. Moreover, this apparently avoids shuffling
                # column order
                if not wdf.empty:
                    wav_dframe = wdf if wav_dframe is None else wav_dframe.append(wdf,
                                                                                  ignore_index=True)

    ert.print_progress(epilog="Done")

    logger.debug("")
    logger.info("Querying Datacenter WS")

    total = 0
    skipped_error = 0
    skipped_empty = 0
    skipped_already_saved = 0
    if wav_dframe is not None:

        total = len(wav_dframe)

        # append reorders the columns, so set them as we wanted
        # Note that wdf is surely defined
        # Note also that now column order is not anymore messed up, but do this for safety:
        wav_dframe = wav_dframe[wdf.columns]

        # purge wav_data (this creates a column id primary key):
        wav_data = db_handler.purge_df(db_handler.tables.data, wav_dframe)
        skipped_already_saved = total - len(wav_data)

        logger.debug("Downloading and saving %d of %d waveforms (%d already saved)",
                     len(wav_data), len(wav_dframe), len(wav_dframe) - len(wav_data))

        ert = EstRemTimer(len(wav_data))

        # it turns out that now wav_data is a COPY of wav_dframe
        # any further operation on it raises a SettingWithCopyWarning, thus avoid issuing it:
        # http://stackoverflow.com/questions/23688307/settingwithcopywarning-even-when-using-loc
        wav_data.is_copy = False

        logger.debug("")
        logger.debug("Segments ready to be downloaded (one row per segment) "
                     "after processing and purging invalid data:")
        # print dframe except two verbose columns
        # (Data which is byte and QueryStr is much data to be printed and in any case
        # we will print it later). Note: Data is not in the dataframe anymore (will ba added later)
        logger.debug(pd_str(wav_data[[c for c in wav_data.columns if c not in ("QueryStr", "Id")]]))
        logger.debug("")

        # insert binary data (empty)
        bin_data_series = read_wavs_data(wav_data['QueryStr'], logger, ert)
        wav_data.insert(1, 'Data', bin_data_series)

        # purge stuff which is not good:
        wav_data.dropna(subset=['Data'], inplace=True)
        skipped_error = (total - skipped_already_saved) - len(wav_data)
        wav_data = wav_data[wav_data['Data'] != b'']
        skipped_empty = (total - skipped_already_saved - skipped_error) - len(wav_data)

    ert.print_progress(epilog="Done")
    logger.debug("")
    if logger.warnings:
        print "%d warnings (check log for details)" % logger.warnings

    seg_written = total-skipped_empty-skipped_error-skipped_already_saved
    logger.info(("%d of %d segments written to '%s', "
                 "%d skipped (%d already saved, %d due to url error, %d empty)"),
                seg_written,
                total,
                outpath,
                total - seg_written,
                skipped_already_saved,
                skipped_error,
                skipped_empty)

    # write events:
    # first purge them then write
    new_events = db_handler.purge_df(db_handler.tables.events, events)
    db_handler.write_df(db_handler.tables.events, new_events)
    # write data:
    db_handler.write_df(db_handler.tables.data, wav_data)
    # write log:
    log_dframe = logger.to_df(seg_found=total, seg_written=seg_written)
    db_handler.write_df(db_handler.tables.logs, log_dframe)

    return 0
