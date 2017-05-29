# -*- coding: utf-8 -*-
"""
    Common utilities for the program
"""
# from __future__ import print_function  # , unicode_literals
import os
import yaml
import re
import time
import datetime as dt
from sqlalchemy.orm.scoping import scoped_session
from sqlalchemy.engine import create_engine
from sqlalchemy.orm.session import sessionmaker
from click import progressbar as click_progressbar
from collections import defaultdict
from stream2segment.io.db.models import Base
import sys
from itertools import izip
from contextlib import contextmanager


# THESE FUNCTIONS WERE IMPLEMENTED TO BE PYTHON2 AND 3 COMPLIANT, BUT WE DO NOT USE THEM ANYWHERE...
# def isstr(val):
#     """
#     :return: True if val denotes a string (`basestring` in python2 and `str` otherwise).
#     """
#     try:
#         return isinstance(val, basestring)
#     except NameError:  # python3
#         return isinstance(val, str)
# 
# 
# def isunicode(val):
#     """
#     :return: True if val denotes a unicode string (`unicode` in python2 and `str` otherwise)
#     """
#     try:
#         if isinstance(val, basestring):
#             return isinstance(val, unicode)
#     except NameError:  # python3
#         return isinstance(val, str)
# 
# 
# def tobytes(unicodestr, encoding='utf-8'):
#     """
#         Converts unicodestr to a byte sequence, with the given encoding. Python 2-3 compatible.
#         :param unicodestr: a unicode string. If already byte string, this method just returns it
#         :param encoding: the encoding used. Defaults to 'utf-8' when missing
#         :return: a `bytes` object (same as `str` in python2) resulting from encoding unicodestr
#     """
#     if isinstance(unicodestr, bytes):  # works for both py2 and py3
#         return unicodestr
#     return unicodestr.encode(encoding)

class strconvert(object):

    @staticmethod
    def sql2wild(text):
        """
        :return: a string by replacing in `text` all sql 'like' wildcards ('%', '_') with text
        search equivalent ('*', '?')
        """
        return text.replace("%", "*").replace("_", "?")

    @staticmethod
    def wild2sql(text):
        """
        :return: a string by replacing in `text` all text search wildcards ('*', '?') with
        sql 'like' equivalent ('%', '_')
        """
        return text.replace("*", "%").replace("?", "_")

    @staticmethod
    def wild2re(text):
        """
        :return: a string by replacing in `text` all text search wildcards ('*', '?') with
        regular expression equivalent ('.*', '.')
        """
        return re.escape(text).replace(r"\*", ".*").replace(r"\?", ".")

    @staticmethod
    def sqld2re(text):
        """
        :return: a string by replacing in `text` all sql 'like' wildcards ('%', '_') with
        regular expression equivalent ('.*', '.')
        """
        return re.escape(text).replace(r"\%", ".*").replace(r"\_", ".")


# def strconvert(string, src='text', dest='regex'):
#     """
#     Converts text to regular expression (regex) or sql like constructs. Does not escape `string`,
#     so string should not have wildcards (special characters) in the `dest` language:
# 
#     :param string: the string to convert
#     :param src: the string identifying the source "language": 'text' (using normal
#     wildcards '*' and '?'), 'regexp ('.*', '*') or 'sql' ('%', '_')
# 
#     Summary table
#     =============
# 
#     wildcard character meaning                         regexp equivalent sql 'like' equivalent
#     ================== =============================== ================= =====================
#     *                  matches zero or more characters .*                %
#     ?                  matches exactly one character   .                 _
# 
#     returns a sql "like" expression from a given fdsn channel constraint parameters
#     (network,    station,    location    and channel) converting wildcards, if any"""
# 
#     assert src in ('text', 'regex', 'sql')
#     assert dest in ('text', 'regex', 'sql')
#     wildcs = {'text': ['*', '?'], 'regex': ['.*', '.'], 'sql': ['%', '_']}
#     for char_src, char_dest in izip(wildcs[src], wildcs['dest']):
#         string = string.replace(char_src, char_dest)
#     return string


def load_source(pyfilepath):
    """Loads a source python file and returns it"""
    if sys.version_info[0] == 2:
        import imp  # @UnresolvedImport
        return imp.load_source('processing_module_name', pyfilepath)
    else:
        import importlib.util  # @UnresolvedImport
        spec = importlib.util.spec_from_file_location('processing_module_name', pyfilepath)
        foo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(foo)
        return foo


def tounicode(bytestr, decoding='utf-8'):
    """
        Converts bytestr to unicode string, with the given decoding. Python 2-3 compatible.
        :param bytestr: a `bytes` object. If already unicode string (`unicode` in python2,
        `str` in python3) this method just returns it
        :param decoding: the decoding used. Defaults to 'utf-8' when missing
        :return: a string (`str` in python3, `unicode` string in python2) resulting from decoding
        `bytestr`
    """
    return bytestr.decode(decoding) if isinstance(bytestr, bytes) else bytestr


def strptime(string, formats=None):
    """
        Converts a date in string format into a datetime python object. The inverse can be obtained
        by calling dt.isoformat() (which returns 'T' as date time separator, and optionally
        microseconds if they are not zero). This function is an easy version of
        `dateutil.parser.parse` for parsing iso-like datetime format (e.g. fdnsws standard)
        without the need of a module import
        :param: string: if a datetime object, returns it. If date object, converts to datetime
        and returns it. Otherwise must be a string representing a datetime
        :type: string: a string, a date or a datetime object (in that case just returns it)
        :param formats: if list or iterable, it holds the strings denoting the formats to be used
        to convert string (in the order they are declared). If None (the default), the datetime
        format will be guessed from the string length among the following (with optional 'Z', and
        with 'T' replaced by space as vaild option):
           - '%Y-%m-%dT%H:%M:%S.%fZ'
           - '%Y-%m-%dT%H:%M:%SZ'
           - '%Y-%m-%dZ'
        :raise: ValueError if the string cannot be parsed
        :type: on_err_return_none: object or Exception
        :return: a datetime object
        :Example:
        ```
            strptime("2016-06-01T09:04:00.5600Z")
            strptime("2016-06-01T09:04:00.5600")
            strptime("2016-06-01 09:04:00.5600Z")
            strptime("2016-06-01T09:04:00Z")
            strptime("2016-06-01T09:04:00")
            strptime("2016-06-01 09:04:00Z")
            strptime("2016-06-01")
        ```
    """
    if isinstance(string, dt.datetime):
        return string

    string = string.strip()

    if formats is None:
        has_z = string[-1] == 'Z'
        has_t = 'T' in string
        if has_t or has_z or ' ' in string:
            t_str, z_str = 'T' if has_t else ' ', 'Z' if has_z else ''
            formats = ['%Y-%m-%d{}%H:%M:%S.%f{}'.format(t_str, z_str),
                       '%Y-%m-%d{}%H:%M:%S{}'.format(t_str, z_str)]
        else:
            formats = ['%Y-%m-%d']

    for dtformat in formats:
        try:
            return dt.datetime.strptime(string, dtformat)
        except ValueError:  # as exce:
            pass

    raise ValueError("%s: invalid date time" % string)


def yaml_load(filepath, raw=False, **defaults):
    """Loads default config from yaml file, normalizing relative sqlite file paths if any
    assuming they are relative to `filepath`, and setting the given defaults (if any)
    for arguments missing in the config
    (if raw is True)"""
    with open(filepath, 'r') as stream:
        ret = yaml.safe_load(stream) if not raw else stream.read()
    if not raw:
        configfilepath = os.path.abspath(os.path.dirname(filepath))
        # convert relative sqlite path to absolute, assuming they are relative to the config:
        sqlite_prefix = 'sqlite:///'
        # we cannot modify a dict while in iteration, thus create a new dict of possibly
        # modified sqlite paths and use later dict.update
        newdict = {}
        for k, v in ret.iteritems():
            try:
                if v.startswith(sqlite_prefix) and ":memory:" not in v:
                    dbpath = v[len(sqlite_prefix):]
                    if not os.path.isabs(dbpath):
                        newdict[k] = sqlite_prefix + \
                            os.path.normpath(os.path.join(configfilepath, dbpath))
            except AttributeError:
                pass
        if newdict:
            ret.update(newdict)

        for key, val in defaults.iteritems():
            if key not in ret:
                ret[key] = val
    return ret


def yaml_load_doc(filepath):
    """Loads the doc from a yaml. The doc is intended to be all consecutive commented lines (i.e.,
    without blank lines) before each top-level variable (nested variables are not considered).
    The returned dict is a defaultdict which returns as string values (**unicode** strings in
    python 2) or an empty string for non-found documented variables.
    :param filepath: The yaml file to read the doc from
    """
    last_comment = ''
    prev_line = None
    reg = re.compile("([^:]+):.*")
    reg_comment = re.compile("\\s*#+(.*)")
    ret = defaultdict(str)
    isbytes = None
    with open(filepath, 'r') as stream:
        while True:
            line = stream.readline()
            if isbytes is None:
                isbytes = isinstance(line, bytes)
            if not line:
                break
            m = reg_comment.match(line)
            if m and m.groups():  # set comment (append or new if previous was a newline)
                comment = m.groups()[0]
                if prev_line == '\n':
                    last_comment = comment
                else:
                    last_comment += comment
            elif line in ('\n', '\r') or line[:2] == '\r\n':  # normalize newlines
                line = '\n'
            else:  # try to see if it's a variable, and in case set the doc (if any)
                m = reg.match(line)
                if m and m.groups():
                    ret[m.groups()[0]] = last_comment.decode('utf8') if isbytes else last_comment
                last_comment = ''
            prev_line = line
    return ret


def get_session(dbpath, scoped=False):  # , enable_fk_if_sqlite=True):
    """
    Create an sql alchemy session for IO db operations
    :param dbpath: the path to the database, e.g. sqlite:///path_to_my_dbase.sqlite
    :param scoped: boolean (False by default) if the session must be scoped session
    """
    # init the session:
    engine = create_engine(dbpath)
    Base.metadata.create_all(engine)  # @UndefinedVariable

    # enable fkeys if sqlite. This can be added also as event listener as outlined here:
    # http://stackoverflow.com/questions/13712381/how-to-turn-on-pragma-foreign-keys-on-in-sqlalchemy-migration-script-or-conf
    # NOT implemented YET. See models.py

    if not scoped:
        # create a configured "Session" class
        session = sessionmaker(bind=engine)
        # create a Session
        return session()
    # return session
    else:
        session_factory = sessionmaker(bind=engine)
        return scoped_session(session_factory)


def timedeltaround(tdelta):
    """Rounds a timedelta to seconds"""
    add = 1 if tdelta.microseconds >= 500000 else 0
    return dt.timedelta(days=tdelta.days, seconds=tdelta.seconds+add, microseconds=0)


def secure_dburl(dburl):
    """Returns a printable database name by removing passwords, if any
    :param dbpath: string, in the format:
    dialect+driver://username:password@host:port/database
    For infor see:
    http://docs.sqlalchemy.org/en/latest/core/engines.html#database-urls
    """
    return re.sub(r"://(.*?):(.*)@", r"://\1:***@", dburl)


# https://stackoverflow.com/questions/24946321/how-do-i-write-a-no-op-or-dummy-class-in-python
class Nop(object):
    def __init__(self, *a, **kw):
        pass

    @staticmethod
    def __nop(*args, **kw):
        pass

    def __getattr__(self, _):
        return self.__nop


@contextmanager
def get_progressbar(show, **kw):
    """Returns a `click.progressbar` if `show` is True, otherwise a No-op class, so that we can
    run programs from code (do not print progress) and from terminal (print progress) by simply
    doing:
    ```
        isterminal = True  # or False for no-op class
        with get_progressbar(isterminal, length=..., ...) as bar:
            # do your stuff in iterators and call
            bar.update(num_increments)  # will update the terminal with a progressbar, or
                                        # do nothing (no-op) if isterminal=True
    ```
    """
    if not show or kw.get('length', 1) == 0:
        yield Nop(**kw)
    else:
        # some custom setup if missing:
        if 'fill_char' not in kw:
            kw['fill_char'] = "●"
        if 'empty_char' not in kw:
            kw['empty_char'] = '○'
        if 'bar_template' not in kw:
            kw['bar_template'] = '%(label)s %(bar)s %(info)s'
        with click_progressbar(**kw) as bar:
            yield bar


def indent(string, n_chars=3):
    """Indents the given string (or each line of string if multi-line)
    with n_chars spaces.
    :param n_chars: int or string: the number of spaces to use for indentation. If 'tab',
    indents using the tab character"""
    reg = re.compile("^", re.MULTILINE)
    return reg.sub("\t" if n_chars == 'tab' else " " * n_chars, string)


# def printfunc(isterminal=False):
#     """Returns the print function if isterminal is True else a no-op function"""
#     if isterminal:
#         return print
#     else:
#         return lambda *a, **v: None
