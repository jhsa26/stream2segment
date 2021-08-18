"""
s2s process database ORM

:date: Jul 15, 2016

.. moduleauthor:: Riccardo Zaccarelli <rizac@gfz-potsdam.de>
"""

import os
from datetime import datetime
from math import pi
from io import BytesIO
import gzip
import zipfile
import zlib
import bz2

from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship, backref, load_only
from sqlalchemy.orm.session import object_session
from sqlalchemy.sql.expression import text, case, select, or_
from obspy.core.stream import _read  # noqa
from obspy.core.inventory.inventory import read_inventory

from stream2segment.io.db.sqlconstructs import missing_data_ratio, missing_data_sec, \
    duration_sec, deg2km, concat, substr
from stream2segment.process.db.sqlevalexpr import exprquery
from stream2segment.io.db import models


class SkipSegment(Exception):
    """Stream2segment exception indicating a segment processing error that should
    resume to the next segment without interrupting the whole routine
    """
    pass  # (we can also pass an exception in the __init__, superclass converts it)


Base = declarative_base(cls=models.Base)


class Download(Base, models.Download):  # pylint: disable=too-few-public-methods
    """Model representing the executed downloads"""
    pass


class Event(Base, models.Event):  # pylint: disable=too-few-public-methods
    """Model representing a seismic Event"""
    pass


class WebService(Base, models.WebService):
    """Model representing a web service (e.g., event web service)"""
    pass


class DataCenter(Base, models.DataCenter):
    """Model representing a Data center (data provider, e.g. EIDA Node)"""
    pass


# listen for insertion and updates and check Datacenter URLS (the call below
# is the same as decorating check_datacenter_urls_fdsn with '@event.listens_for'):
event.listens_for(DataCenter, 'before_insert')(models.check_datacenter_urls_fdsn)
event.listens_for(DataCenter, 'before_update')(models.check_datacenter_urls_fdsn)


class Class(Base, models.Class):
    """Model representing a segment class label"""
    pass


class ClassLabelling(Base, models.ClassLabelling):
    """Model representing a class labelling (or segment annotation), i.e. a
    pair (segment, class label)"""
    pass


class Channel(Base, models.Channel):
    """Model representing a Channel"""

    @hybrid_property
    def band_code(self):
        """Return the first letter of the channel field"""
        return self.channel[0:1]  # if len(self.channel) == 3 else None

    @band_code.expression
    def band_code(cls):  # pylint:disable=no-self-argument
        """Return the sql expression returning the first letter of the channel
        field"""
        # return an sql expression matching the last char or None if not three
        # letter channel
        return substr(cls.channel, 1, 1)

    @hybrid_property
    def instrument_code(self):
        """Return the second letter of the channel field"""
        return self.channel[1:2]  # if len(self.channel) == 3 else None

    @instrument_code.expression
    def instrument_code(cls):  # pylint:disable=no-self-argument
        """Return the sql expression returning the second letter of the channel
        field"""
        # return an sql expression matching the last char or None if not three
        # letter channel
        return substr(cls.channel, 2, 1)

    @hybrid_property
    def band_instrument_code(self):
        """Return the first two letters of the channel field. Useful when we
        want to get the same record on different orientations/components"""
        return self.channel[0:2]  # if len(self.channel) == 3 else None

    @band_instrument_code.expression
    def band_instrument_code(cls):  # pylint:disable=no-self-argument
        """Return the sql expression returning the first two letters of the
        channel field. Useful for queries where we want to get the same record
        on different orientations/components"""
        # return an sql expression matching the last char or None if not three
        # letter channel
        return substr(cls.channel, 1, 2)

    @hybrid_property
    def orientation_code(self):
        """Return the third letter of the channel field"""
        return self.channel[2:3]  # if len(self.channel) == 3 else None

    @orientation_code.expression
    def orientation_code(cls):  # pylint:disable=no-self-argument
        """Return the sql expression returning the third letter of the channel
        field"""
        # return an sql expression matching the last char or None if not three
        # letter channel
        return substr(cls.channel, 3, 1)


class Station(Base, models.Station):
    """Model representing a Station"""

    @hybrid_property
    def netsta_code(self):
        return "%s.%s" % (self.network, self.station)

    @netsta_code.expression
    def netsta_code(cls):  # pylint:disable=no-self-argument
        """Return the station code, i.e. self.network + '.' + self.station"""
        dot = text("'.'")
        return concat(Station.network, dot, Station.station). \
            label('networkstationcode')


    def inventory(self, reload=False):
        """Return the inventory as ObsPy Response object"""
        # inventory is lazy loaded. The output of the loading process
        # (or the Exception raised, if any) is stored in the self._inventory
        # attribute. When querying the inventory a further time, the stored value
        # is returned, or raised (if it is an Exception)
        inventory = getattr(self, "_inventory", None)
        if reload and inventory is not None:
            inventory = None
        if inventory is None:
            try:
                inventory = self._inventory = get_inventory(self)
            except Exception as exc:   # pylint: disable=broad-except
                inventory = self._inventory = \
                    SkipSegment("Station inventory (xml) error: %s" %
                                (str(exc) or str(exc.__class__.__name__)))
        if isinstance(inventory, Exception):
            raise inventory
        return inventory


def get_inventory(station):
    """Return the inventory object for the given station.
    Raises :class:`SkipSegment` if inventory data is empty
    """
    data = station.inventory_xml
    if not data:
        raise SkipSegment('no data')
    return get_inventory_from_bytes(data)


def get_inventory_from_bytes(bytestr):
    """Return the inventory object given an input bytes sequence representing an
    inventory (xml) from, e.g., downloaded data
    :param bytestr: the sequence of bytes. It can be compressed with any of the function
    defined when saving the byte string (gzip, bz and so on). The method will first try
    to de-compress data. Then, the de-compressed data (if de-compression does not fail)
    or the data passed as argument will be passed to ObsPy `read_inventory`

    :return: an `class: obspy.core.inventory.inventory.Inventory` object
    """
    try:
        bytestr = decompress(bytestr)
    except(IOError, zipfile.BadZipfile, zlib.error) as _:
        pass  # try anyway to open the file (who knows)
    return read_inventory(BytesIO(bytestr), format="STATIONXML")


def decompress(bytestr):
    """Decompress `bytestr` (a sequence of bytes) trying to guess the compression
    format. If no guess can be made, returns bytestr. Otherwise, returns the
    de-compressed sequence of bytes. Raises IOError, zipfile.BadZipfile, zlib.error if
    compression is detected but did not work. Note that this might happen if
    (accidentally) the sequence of bytes is not compressed but starts with bytes
    denoting a compression type. Thus function caller should not necessarily raise
    exceptions if this function does, but try to read `bytestr` as if it was not
    compressed
    """
    # check if the data is compressed (https://stackoverflow.com/a/19127748):
    if bytestr.startswith(b"\x1f\x8b\x08"):  # gzip
        # raises IOError in case
        with gzip.GzipFile(mode='rb', fileobj=BytesIO(bytestr)) as gzip_obj:
            bytestr = gzip_obj.read()
    elif bytestr.startswith(b"\x42\x5a\x68"):  # bz2
        bytestr = bz2.decompress(bytestr)  # raises IOError in case
    elif bytestr.startswith(b"\x50\x4b\x03\x04"):  # zip
        # raises zipfile.BadZipfile in case
        with zipfile.ZipFile(BytesIO(bytestr), 'r') as zip_obj:
            namelist = zip_obj.namelist()
            if len(namelist) != 1:
                raise ValueError("Found zipped content with %d archives, "
                                 "can only uncompress single archive "
                                 "content" % len(namelist))
            bytestr = zip_obj.read(namelist[0])
    else:
        barray = bytearray(bytestr[:2])  # py 2+3 https://stackoverflow.com/a/41843740
        byte1 = barray[0]
        byte2 = barray[1]
        if (byte1 * 256 + byte2) % 31 == 0 and (byte1 & 143) == 8:  # zlib. 143=int('10001111', 2)
            bytestr = zlib.decompress(bytestr)  # raises zlib.error in case
    return bytestr


class Segment(Base, models.Segment):
    """Model representing a Waveform segment"""

    # DEFINE HYBRID PROPERTIES WITH RELATIVE SELECTION EXPRESSIONS FOR QUERYING
    # THE DB:

    @hybrid_property
    def event_distance_km(self):
        return self.event_distance_deg * (2.0 * 6371 * pi / 360.0)

    @event_distance_km.expression
    def event_distance_km(cls):  # pylint:disable=no-self-argument
        return deg2km(cls.event_distance_deg)

    @hybrid_property
    def duration_sec(self):
        try:
            return (self.end_time - self.start_time).total_seconds()
        except TypeError:  # some None(s)
            return None

    @duration_sec.expression
    def duration_sec(cls):  # pylint:disable=no-self-argument
        return duration_sec(cls.start_time, cls.end_time)

    @hybrid_property
    def missing_data_sec(self):
        try:
            return (self.request_end - self.request_start).total_seconds() - \
                (self.end_time - self.start_time).total_seconds()
        except TypeError:  # some None(s)
            return None

    @missing_data_sec.expression
    def missing_data_sec(cls):  # pylint:disable=no-self-argument
        return missing_data_sec(cls.start_time, cls.end_time,
                                cls.request_start, cls.request_end)

    @hybrid_property
    def missing_data_ratio(self):
        try:
            ratio = ((self.end_time - self.start_time).total_seconds() /
                     (self.request_end - self.request_start).total_seconds())
            return 1.0 - ratio
        except TypeError:  # some None's
            return None

    @missing_data_ratio.expression
    def missing_data_ratio(cls):  # pylint:disable=no-self-argument
        return missing_data_ratio(cls.start_time, cls.end_time,
                                  cls.request_start, cls.request_end)

    @hybrid_property
    def has_class(self):
        return len(self.classes) > 0

    @has_class.expression
    def has_class(cls):  # pylint:disable=no-self-argument
        return cls.classes.any()

    def sds_path(self, root='.'):
        """Return a string representing the seiscomp data structure (sds) path
        where to store the given segment or any data associated with it.
        The returned path has no extension (to be supplied by the user)
        and has the following format (e_id=event id, y=year, d=day of year):
        [root]/[e_id]/[net]/[sta]/[loc]/[cha].D/[net].[sta].[loc].[cha].[y].[d]
        For info see:
        https://www.seiscomp3.org/doc/applications/slarchive/SDS.html

        :param root: Optional (defaults to '.' when missing). The root path of this
            segment file (first argument of `os.path.join`)
        """
        # year > N > S > L > C.D > segments > N.S.L.C.year.day.event_id.mseed
        seg_dtime = self.request_start  # note that start_time might be None
        year = seg_dtime.year
        net, sta = self.station.network, self.station.station
        loc, cha = self.channel.location, self.channel.channel
        # day is in [1, 366], padded with zeroes:
        day = '%03d' % ((seg_dtime - datetime(year, 1, 1)).days + 1)
        eid = self.event_id
        return os.path.join(root,
                            str(eid), str(year), net, sta, loc, cha + ".D",
                            '.'.join((net, sta, loc, cha, str(year), day)))

    def del_classlabel(self, *class_ids_or_labels, commit=True):
        """Delete class labels previously associated to this segment

        :param class_ids_or_labels: variable length argument denoting the ids
            (int) or unique labels (str) of the classes to be removed from this
            segment. When NO ids or labels are provided, ALL class labels
            associated to this segment will be deleted. E.g.: `segment.del_classes()`

        :param commit: boolean (default: True) denoting if any change
            should be saved to the database (flush pending changes and commit
            the current transaction).
            Advanced users can set this parameter to False to manage the
            transaction manually and eventually call `segment.dbsession.commit()`
            when needed

        :raise: :class:`sqlalchemy.exc.SQLAlchemy` if a commit error occurs.
            For info see:
            https://docs.sqlalchemy.org/en/latest/orm/session_basics.html
        """
        needs_commit = False
        if not class_ids_or_labels:
            if self.classes.count():
                self.classes = []
                needs_commit = True
        else:
            for cla in list(self.classes.options(load_only(Class.id, Class.label))):
                if cla.id in class_ids_or_labels or cla.label in class_ids_or_labels:
                    needs_commit = True
                    self.classes.remove(cla)

        if needs_commit and commit:
            object_session(self).commit()
            needs_commit = False

        return needs_commit

    def add_classlabel(self, *class_ids_or_labels, commit=True, empty_first=False,
                       annotator=None):
        """Add class label(s) to this segment. Old class labellings are not removed

        :param class_ids_or_labels: list of int (denoting class ids) or str (denoting
            class label). Classes already assigned to this segment will be
            removed, as well as class ids ot labels not matching any database class

        :param commit: boolean (default: True) denoting if any change
            should be saved to the database (flush pending changes and commit
            the current transaction).
            Advanced users can set this parameter to False to manage the
            transaction manually and eventually call `segment.dbsession.commit()`
            when needed

        :param annotator: (str, default: None). The annotator assigning the labelling.
            A None annotator should mean that the label assignment is the result of a
            classifier prediction and not human inspection: providing an annotator
            (not None) will set the `is_hand_labelled` property of the Class labelling
            to True

        :param empty_first: boolean (default False) telling if all existing class
            labels associated to this segment should be removed first, before
            adding new class labels

        :raise: :class:`sqlalchemy.exc.SQLAlchemy` if a commit error occurs or,
            if `safety_check` is False, if any id ir label is incorrect.
            For info see:
            https://docs.sqlalchemy.org/en/latest/orm/session_basics.html
        """
        if empty_first:
            needs_commit = self.del_classlabel(commit=False)
            my_cls_ids = set()
        else:
            my_cls_ids = set(_.id for _ in self.classes.options(load_only(Class.id)))
            needs_commit = False

        if class_ids_or_labels:
            sess = object_session(self)
            qry = sess.query(Class)

            ids2add = set(_ for _ in class_ids_or_labels if isinstance(_, int))
            labels2add = set(str(_) for _ in class_ids_or_labels if not isinstance(_, int))

            # we need to 1. Convert labels to id and 2. Assure that any passed id or
            # label actually exist (and skip non-existing id or labels)
            qry = qry.filter((Class.label.in_(labels2add) if labels2add else False) |
                             (Class.id.in_(ids2add) if ids2add else False))

            ids2add = set(c.id for c in qry.options(load_only(Class.id))) - my_cls_ids

            if ids2add:
                needs_commit = True
                sess.add_all((ClassLabelling(class_id=cid,
                                             segment_id=self.id,
                                             annotator=annotator,
                                             is_hand_labelled=annotator is not None)
                              for cid in ids2add))

        if needs_commit and commit:
            sess.commit()
            needs_commit = False

        return needs_commit

    def siblings(self, parent=None, include_self=False):
        """Return an SQL-Alchemy query (basically, an iterable of Segments)
        yielding all its siblings according to `parent` (and optionally this
        segment too, if `include_me` is True).

        For huge collections, consider loading only the desired attributes,
        e.g.,given a Segment instance `seg`:
        ```
        from stream2segment.process import Segment
        from sqlalchemy.orm import load_only
        for seg in seg.siblings('event').options(load_only(Segment.id))):
            seg_id = seg.id
            ...
        ```

        :param parent: str or None (default: None). Any of the following:

            - `None`: return all db segments of the same recorded event, on the
               other channel orientations (e.g., if this segment is the recorded
               event on a channel vertical component "Z", return the segments of
               the two horizontal components, "N" and "E". For details see
               "Orientation code" here:
               http://www.fdsn.org/pdf/SEEDManual_V2.4_Appendix-A.pdf)

            - `networkname`: return all db segments of the same network (using the
               network code as identifier)

            - `stationname`: return all db segments of the same station, where
               a station is uniquely identified by the tuple:
               (newtwork code, station code)

            - `station`, `channel`, `datacenter`, `event`: return all db
               segments from the associated foreign key. Note: a station in this
               case is uniquely identified by the tuple:
               (network code, station code, start_time)

        :param include_self: boolean (default: False). Whether to include this
            segment among the yielded siblings
        """

        session = object_session(self)
        qry = session.query(Segment)

        if parent is None:
            qry = qry.join(Segment.channel).\
                filter((Segment.event_id == self.event_id) &
                       (Channel.station_id == self.channel.station_id) &
                       (Channel.location == self.channel.location) &
                       (Channel.band_instrument_code ==
                        self.channel.band_instrument_code))
        elif parent == 'stationname':
            qry = qry.join(Segment.channel, Channel.station).\
                filter((Station.network == self.channel.station.network) &
                       (Station.station == self.channel.station.station))
        elif parent == 'networkname':
            qry = qry.join(Segment.channel, Channel.station).\
                filter((Station.network == self.channel.station.network))
        elif parent == 'station':
            qry = qry.join(Segment.channel).\
                filter((Channel.station_id == self.channel.station_id))
        else:
            try:
                qry = qry.filter(getattr(Segment, parent + '_id') ==
                                 getattr(self, parent + '_id'))
            except AttributeError:
                raise TypeError("invalid 'parent' argument '%s'" % parent)

        if not include_self:
            qry = qry.filter(Segment.id != self.id)
        return qry

    @hybrid_property
    def seed_id(self):
        try:
            return self.data_seed_id or \
                ".".join([self.station.network, self.station.station,
                          self.channel.location, self.channel.channel])
        except (TypeError, AttributeError):
            return None

    @seed_id.expression
    def seed_id(cls):  # pylint:disable=no-self-argument
        """Return data_seed_id if the latter is not None, else net.sta.loc.cha
        by querying the relative channel and station"""
        # Needed note: To know what we are doing in 'sel' below, please look:
        # http://docs.sqlalchemy.org/en/latest/orm/extensions/hybrid.html#correlated-subquery-relationship-hybrid
        # Notes
        # - we use limit(1) cause we might get more than one result. Regardless
        #   of why it happens (because we don't join or apply a distinct?) it
        #   is relevant for us to get the first result which has the requested
        #   network+station and location + channel strings
        # - the label(...) at the end makes all the difference. The doc is, as
        #   it often happens, convoluted:
        #   http://docs.sqlalchemy.org/en/latest/core/sqlelement.html#sqlalchemy.sql.expression.label
        dot = text("'.'")
        sel = select([concat(Station.network, dot, Station.station, dot,
                             Channel.location, dot, Channel.channel)]).\
            where((Channel.id == cls.channel_id) &
                  (Station.id == Channel.station_id)).\
            limit(1).label('seedidentifier')
        return case([(cls.data_seed_id.isnot(None), cls.data_seed_id)],
                    else_=sel)

    def inventory(self, reload=False):
        """Return the inventory of the segment Station as ObsPy Response object

        :param reload: bool. Optional (default: False). Force reloading the Response
            object from the downloaded waveform data (bytes sequence). In most cases
            you can ignore this parameter as a Response object is usually never modified
            but used as read-only object
        """
        return self.station.inventory(reload)

    @property
    def dbsession(self):
        """Return the database session to which this object is attached"""
        return object_session(self)

    def stream(self, reload=False):
        """Return the ObsPy Stream object representing the segment waveform data

        :param reload: bool. Optional (default: False). Force reloading the Stream
            object from the downloaded waveform data (bytes sequence), discarding
            any in-place modification
        """
        # stream is lazy loaded. The output of the loading process
        # (or the Exception raised, if any) is stored in the self._stream attribute.
        # When querying the stream a further time, the stored value is returned,
        # or raised (if it is an Exception)
        stream = getattr(self, "_stream", None)
        if reload and stream is not None:
            stream = None
        if stream is None:
            try:
                stream = self._stream = get_stream(self)
            except Exception as exc:  # pylint: disable=broad-except
                stream = self._stream = \
                    SkipSegment("MiniSeed error: %s" %
                                (str(exc) or str(exc.__class__.__name__)))

        if isinstance(stream, Exception):
            raise stream
        return stream

    # Relationships:

    event = relationship("Event", backref=backref("segments",
                                                  lazy="dynamic"))
    channel = relationship("Channel", backref=backref("segments",
                                                      lazy="dynamic"))
    # (station relationship is implemented in superclass, as it's needed for download)
    classes = relationship("Class",  lazy='dynamic',  # viewonly=True,
                           # `secondary` must be table name in metadata:
                           secondary="class_labellings",
                           backref=backref("segments", lazy="dynamic"))
    datacenter = relationship("DataCenter", backref=backref("segments",
                                                            lazy="dynamic"))
    download = relationship("Download", backref=backref("segments",
                                                        lazy="dynamic"))


def get_stream(segment, format="MSEED", headonly=False, **kwargs):  # noqa
    """Return a Stream object relative to the given segment. The optional
    arguments are the same than `obspy.core.stream.read` (excepts than "format"
    defaults to "MSEED")

    :param segment: a model ORM instance representing a Segment (waveform data
        db row)
    :param format: string, optional (default "MSEED"). Format of the file to
        read. See ObsPy `Supported Formats`_ section below for a list of
        supported formats. If `format` is set to ``None`` it will be
        automatically detected which results in a slightly slower reading. If a
        format is specified, no further format checking is done.
    :param headonly: bool, optional (dafult: False). If set to ``True``, read
        only the data header. This is most useful for scanning available meta
        information of huge data sets
    :param kwargs: Additional keyword arguments passed to the underlying
        waveform reader method.
    """
    data = segment.data
    if not data:
        raise SkipSegment('no data')
    # Do not call `obspy.core.stream.read` because, when passed a BytesIO, if
    # it fails reading it stores the bytes data to a temporary file and
    # re-tries by reading the file. This is a useless and time-consuming
    # behavior in our case: `data` is directly downloaded from the data-center:
    # if we fail we should raise immediately. To do that, we call
    # ``obspy.core.stream._read`, which is what `obspy.core.stream.read` does
    # internally. Note that calling _read might require some attention as
    # "private" methods might change across versions. Also, FYI, the source
    # function which does the real job is "obspy.io.mseed.core._read_mseed"
    try:
        return _read(BytesIO(data), format, headonly, **kwargs)
    except Exception as terr:
        raise SkipSegment(str(terr))
