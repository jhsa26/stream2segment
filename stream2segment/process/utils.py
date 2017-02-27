'''
Created on Feb 24, 2017

@author: riccardo
'''
from obspy.core import read, Stream, Trace
from cStringIO import StringIO
from stream2segment.io.db import models
from sqlalchemy.sql.expression import and_


# def iterstream(segment, session, include_segment=True):
#     """Returns an iterator yielding the tuples (seg_id, stream) over all the `obspy.Stream`
#     objects of the given segment, including the segments of the different components (channels)
#     of `segment`, i.e. those
#     segments with same time range, same station and same location.
#     The order of the returned stream is unpredictable. To know which stream corresponds
#     to the given segment, use `stream[0].stats.channel == segment.channel.location + "." +
#     segment.channel.channel`
#     """
#     conditions = [models.Channel.station_id == segment.station.id,
#                   models.Channel.location == segment.channel.location,
#                   models.Segment.start_time == segment.start_time,
#                   models.Segment.end_time == segment.end_time]
# 
#     if not include_segment:
#         conditions.append(models.Segment.id != segment.id)
# 
#     for segid, dat in session.query(models.Segment.id, models.Segment.data).\
#             join(models.Channel).filter(and_(*conditions)):
#             yield segid, read(StringIO(dat))
# 
# 
def get_stream(segment):
    """
        Returns a Stream object or a list of streams (if all_channels=True)
        relative to the given segment.
        :param segment: a model ORM instance representing a Segment (waveform data db row)
        :param session: a SqlAlchemy session
        :param all_channels: if False, returns the Stream object of segment. If False,
        sets the Stream object of segment as the first element of the list that will be returned
        The other elements of the list are the Stream objects relative to the other components
        (i.e., all segments with same data range, same station and same location, but different
        channel)
        :param onerr: if 'raise', the default, then each exception raises. If any other value,
        then None's are returned for those Stream which resulted in errors
    """
    return read(StringIO(segment.data))


def itercomponents(segment, session):
    conditions = [models.Channel.station_id == segment.station.id,
                  models.Channel.location == segment.channel.location,
                  models.Segment.start_time == segment.start_time,
                  models.Segment.end_time == segment.end_time,
                  models.Segment.id != segment.id]

    for seg in session.query(models.Segment).join(models.Channel).filter(and_(*conditions)):
        yield seg


# FIXME: not implemented! remove?!!
def has_data(segment, session):
    pass