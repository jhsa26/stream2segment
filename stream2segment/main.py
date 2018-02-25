# -*- coding: utf-8 -*-
"""
Main module with all root functions (download, process, ...)

:date: Feb 2, 2016

.. moduleauthor:: Riccardo Zaccarelli <rizac@gfz-potsdam.de>
"""
from __future__ import print_function

# make the following(s) behave like python3 counterparts if running from python2.7.x
# (http://python-future.org/imports.html#explicit-imports):
from builtins import (ascii, bytes, chr, dict, filter, hex, input,
                      int, map, next, oct, open, pow, range, round,
                      str, super, zip, object)

import logging
import re
import sys
import os
from contextlib import contextmanager
import shutil
import inspect
from datetime import datetime, timedelta
from sqlalchemy.exc import SQLAlchemyError

# this can not apparently be fixed with the future package:
# The problem is io.StringIO accepts unicodes in python2 and strings in python3:
try:
    from cStringIO import StringIO  # python2.x
except ImportError:
    from io import StringIO

import yaml
import click

from stream2segment.utils.log import configlog4download, configlog4processing
from stream2segment.io.db.models import Download
from stream2segment.process.main import to_csv
from stream2segment.download.main import run as run_download, new_db_download
from stream2segment.utils import get_session, secure_dburl, strptime, strconvert, iterfuncs, load_source
from stream2segment.utils.resources import get_templates_fpaths, yaml_load, get_ttable_fpath
from stream2segment.gui.main import create_p_app, run_in_browser, create_d_app
from stream2segment.process import math as s2s_math
from stream2segment.download.utils import nslc_param_value_aslist, QuitDownload
from stream2segment.traveltimes.ttloader import TTTable
import time


# set root logger if we are executing this module as script, otherwise as module name following
# logger conventions. Discussion here:
# http://stackoverflow.com/questions/30824981/do-i-need-to-explicitly-check-for-name-main-before-calling-getlogge
# howver, based on how we configured entry points in config, the name is (as november 2016)
# 'stream2segment.main', which messes up all hineritances. So basically setup a main logger
# with the package name
logger = logging.getLogger("stream2segment")


def download(configfile, verbosity=2, **param_overrides):
    """
        Downloads the given segment providing a set of keyword arguments to match those of the
        config file (see confi.example.yaml for details)
        
        :param configfile: a valid path to a file in yaml format
        :param verbosity: integer: 0 means: no logger configured, no print to standard output.
            Use this option if you want to have maximum flexibility (e.g. configure your logger)
            and - in principle - shorter execution time (although the real benefits have not been
            measured): this means however that no log information will be saved to the database
            (including the execution time) unless a logger has been explicitly set by the user
            beforehand (see :clas:`DbHandler` in case)
            1 means: configure default logger, no print to standard output. Use this option if you
            are not calling this function from the command line but you want to have all log
            information stored to the database (including execution time)
            2 (the default) means: configure default logger, and print to standard output. Use this
            option if calling this program from the command line. This is the same as verbosity=1
            but in addition some informations are printed to the standard output, including
            progresss bars for displaying the estimated remaining time of each sub-task

        :raise: ValueError if some parameter is invalid in configfile (yaml format)
    """
    # implementation details: this function can return 0 on success and 1 on failure.
    # First, it can raise ValueError for a bad parameter (checked before starting db session and
    # logger),
    # Then, during download, if the process completed 0 is returned. This includes the case
    # when according to our config, there are no segments to download
    # For any other case where we cannot proceed (we do not have data, e.g. no stations,
    # for whatever reason it is), 1 is returned. We should actually check better if there
    # might be some of these cases where 0 should be returned instead of 1.
    # When 1 is returned, a QuitDownload is raised and logged to error.
    # Other exceptions are caught, logged with the stack trace as critical, and raised
    
    input_yaml_dict = read_configfile(configfile, **param_overrides)
    # the obect above will be saved to db, make a copy for mainpulation here:
    yaml_dict = dict(input_yaml_dict)
    # param check before setting stuff up. All these raise BadParameter(s) in case:
    adjust_nslc_params(yaml_dict)
    adjust_times(yaml_dict)
    load_tt_table(yaml_dict)  # pops 'traveltimes_model' from yaml_dict, adds tt_table key
    session = create_session(extract_dburl(yaml_dict))  # pops dburl from yaml_dict

    # print yaml_dict to terminal if needed. Do not use input_yaml_dict as
    # params needs to be shown as expanded/converted so the user can check their correctness
    # Do no use loggers yet:
    is_from_terminal = verbosity >= 2
    if is_from_terminal:
        # replace dburl hiding passowrd for printing to terminal, tt_table with a short repr str,
        # and restore traveltimes_model because we popped from yaml_dict it out in load_tt_table
        yaml_safe = dict(yaml_dict, dburl=secure_dburl(input_yaml_dict['dburl']),
                         tt_table="<%s object>" % TTTable.__class__.__name__,
                         traveltimes_model=input_yaml_dict['traveltimes_model'])
        ip_params = yaml.safe_dump(yaml_safe, default_flow_style=False)
        ip_title = "Input parameters"
        print("%s\n%s\n%s\n" % (ip_title, "-" * len(ip_title), ip_params))
        
    
    download_id = new_db_download(session, input_yaml_dict)
    loghandlers = configlog4download(logger, is_from_terminal) if verbosity > 0 else []
    ret = 0
    noexc_occurred = True
    stime, etime = None, None
    try:
        if is_from_terminal:  # (=> loghandlers not empty)
            print("Log file:\n'%s'\n"
                  "(if the program does not quit for unexpected exceptions or external causes, "
                  "e.g., memory overflow,\n"
                  "the file will be deleted before exiting and its content will be written\n"
                  "to the table '%s', column '%s')" % (str(loghandlers[0].baseFilename),
                                                       Download.__tablename__,
                                                       Download.log.key))

        stime = time.time()
        try:
            run_download(session=session, download_id=download_id, isterminal=is_from_terminal,
                         **yaml_dict)
        except QuitDownload as quitdownloadexc:
            if quitdownloadexc._iserror:  #pylint: disable=protected-access
                logger.error(quitdownloadexc)
                ret = 1  # that's the program return
            else:
                logger.info(str(quitdownloadexc))
        etime = time.time()

    except:  # print the exception traceback (only last) witha  custom logger, and raise,
        # so that in principle the full traceback is printed on terminal (or caught by the caller) 
        noexc_occurred = False
        # https://stackoverflow.com/questions/5191830/best-way-to-log-a-python-exception:
        logger.critical("Download aborted", exc_info=True)
        raise
    finally:
        if noexc_occurred:
            logger.info("Completed in %s", str(totimedelta(stime, etime)))
            logger.info("\n%d total error(s), %d total warning(s)", loghandlers[0].errors,
                        loghandlers[0].warnings)
        
        # write log to db if custom handlers provided:
        if loghandlers:
            loghandlers[0].finalize(session, download_id, removefile=noexc_occurred)
        closesession(session)
        
    return ret


def read_configfile(configfile, **param_overrides):
    pname = 'configfile'
    
    try:
        if not os.path.isfile(configfile):
            raise Exception('file does not exist')
        
        return yaml_load(configfile, **param_overrides)
    except Exception as exc:
        raise BadParameter(exc, pname)


def extract_dburl(yaml_dict):
    pname = 'dburl'
    try:
        return yaml_dict.pop(pname)
    except KeyError:
        raise MissingConfigfileParameter(pname)


def create_session(dburl):
    try:
        return get_session(dburl, scoped=False)
    except SQLAlchemyError as exc:
        raise BadParameter(exc, 'dburl')


def load_tt_table(yaml_dict):
    pname = 'traveltimes_model'
    try:
        file_or_name = yaml_dict.get(pname, None)
        filepath = get_ttable_fpath(file_or_name)
        if not os.path.isfile(filepath):
            filepath = file_or_name
        if not os.path.isfile(filepath):
            raise Exception('file or builtin model name not found')
        yaml_dict['tt_table'] = TTTable(filepath)
    except KeyError:
        raise MissingConfigfileParameter(pname)
    except Exception as exc:
        raise BadParameter(exc, pname)

def adjust_times(yaml_dict):
    try:
        for pname in ['start', 'end']:
            yaml_dict[pname] = valid_date(yaml_dict[pname])
    except KeyError:
        raise MissingConfigfileParameter(pname)
    except ValueError as exc:
        raise BadParameter(exc, pname)


def valid_date(obj):
    try:
        return strptime(obj)  # if obj is datetime, returns obj
    except ValueError as _:
        try:
            days = int(obj)
            now = datetime.utcnow()
            endt = datetime(now.year, now.month, now.day, 0, 0, 0, 0)
            return endt - timedelta(days=days)
        except Exception:
            pass
    raise ValueError("date-time or an integer required")


def adjust_nslc_params(yaml_dic):
    '''Scans `dic` keys and returtns the tuple
        ```
        (N, S, L, C)
        ```
    where each element is a list of networks (N), stations (S), locations (L) or channels (C)
    composed by strings in valid ASCII characters with three special characters:
    the 2 FDSN-compliant wildcards '*' and '?', and '!' which means NOT (when placed as first
    character only).

    This function basically returns `",".join(dic[key])` where `key` is any of the following: 
        'net', 'network' or 'networks'
        'sta', 'stations' or 'stations'
        'loc', 'location' or 'locations'
        'cha', 'channel' or 'channels'
    In case of keys conflicts (e.g. 'net' and 'network' are both in `dict`) a ValueError is raised.
    In case a key not found, None or '*', the corresponding element will be the empty list.
    A returned empty list has to be interpreted as "accept all" (i.e. no filter for that key).
    All string elements are stripped, meaning that leading and trailing spaces are removed.

    This function doe salso some preliminary check on each string, so that e.g.
    strings like "!*", or both "A?" and !A?"specified will raise a ValueError in case

    :return: a 4-element tuple net, sta, loc, cha. All elements are lists of strings. Returned
        empty lists mean: no filter for that key (accept all)
    '''
    
    params = [('net', 'network', 'networks'), ('sta', 'station', 'stations'),
              ('loc', 'location', 'locations'), ('cha', 'channel', 'channels')]
    
    for i, pars in enumerate(params):
        
        arg = None
        parconflicts = []
        for p in pars:
            if p in yaml_dic:
                parconflicts.append(p)
                arg = yaml_dic.pop(p)
            if len(parconflicts) > 1:
                raise BadParameter("name conflict: %s both specified" %
                                 (" and ".join('%s' % _ for _ in parconflicts)),
                                 "/".join(parconflicts))
            
        s2s_name = pars[-1]
        val = []
        if len(parconflicts) and arg is not None and arg not in ([], ()):
            try:
                val = nslc_param_value_aslist(i, arg)
            except ValueError as verr:
                raise BadParameter(verr, parconflicts[-1])

        yaml_dic[s2s_name] = val
        

def process(dburl, pyfile, funcname=None, configfile=None, outfile=None, verbose=False):
    """
        Process the segment saved in the db and optionally saves the results into `outfile`
        in .csv format
        If `outfile` is given, `pyfile` should return lists/dicts to be written as
            csv row, and logging errors/ warnings/ infos /critical messages will be printed to a
            file whose path is `[outfile].log`
        If `outfile` is not given, then the returned values of `pyfile` will be ignored
            (`pyfile` is supposed to process data without returning a value, e.g. save processed
            miniSeed to the FileSystem), and logging errors/warnings/infnos/critical messages
            will be printed to `stderr`.
        In both cases, if `verbose` is True, log informations and errors, and a progressbar will be
            printed to standard output, otherwise nothing will be printed
    """
    # implementation details: this function returns 0 on success and raises otherwise.
    # First, it can raise ValueError for a bad parameter (checked before starting db session and
    # logger),
    # Then, during processing, each segment error which is not (ImportError, NameError,
    # AttributeError, SyntaxError, TypeError) is logged as warning and the program continues.
    # Other exceptions are raised, caught here and logged as error, with the stack trace:
    # this allows to help users to discovers possible bugs in pyfile, without waiting for
    # the whole process to finish. Note that this does not distinguish the case where
    # we have any other exception (e.g., keyboard interrupt), but that's not a requirement
    
    # param check before setting stuff up. All these raise BadParameter(s) in case:
    session = create_session(dburl)
    funcname, pyfunc = read_processing_module(pyfile, funcname)
    config_dict = {} if not configfile else read_configfile(configfile)
        
    configlog4processing(logger, outfile, verbose)
    try:
        if verbose:
            if outfile:
                logger.info('Output file: %s', outfile)
            logger.info("Executing '%s' in '%s'", funcname, pyfile)
            logger.info("Input database: '%s", secure_dburl(dburl))
            if configfile:
                logger.info("Config. file: %s", str(configfile))
    
        stime = time.time()
        to_csv(outfile, session, pyfunc, config_dict, verbose)
        logger.info("Completed in %s", str(totimedelta(stime)))
        return 0  # contrarily to download, an exception should always raise and log as error
        # with the stack trace
        # (this includes pymodule exceptions e.g. TypeError)
    except:
        logger.error("Process aborted", exc_info=True)  # see comment above
        raise
    finally:
        closesession(session)


def read_processing_module(pyfile, funcname=None):
    '''Returns the python module from the given python file'''
    reg = re.compile("^(.*):([a-zA-Z_][a-zA-Z_0-9]*)$")
    m = reg.match(pyfile)
    if m and m.groups():
        pyfile = m.groups()[0]
        funcname = m.groups()[1]
    elif funcname is None:
        funcname = default_processing_funcname() 
    
    pname = 'pyfile'

    try:
        if not os.path.isfile(pyfile):
            raise Exception('file does not exist')
    
        return funcname, load_source(pyfile).__dict__[funcname]
    except Exception as exc:
        raise BadParameter(exc, pname)


def default_processing_funcname():
    '''returns 'main', the default function name for processing, when such a name is not given'''
    return 'main'


def totimedelta(t0_sec, t1_sec=None):
    '''time elapsed from `t0_sec` until `t1_sec`, as `timedelta` object rounded to
    seconds.
    If `t1_sec` is None, it will default to `time.time()` (the current time since the epoch,
    in seconds)

    :param t0_sec: (float) the start time in seconds. Usually it is the result of a
        previous call to `time.time()`, before starting a process that had to be monitored
    :param t1_sec: (float) the end time in seconds. If None, it defaults to `time.time()`
        (current time since the epoch, in seconds)
        
    :return: a timedelta object, rounded to seconds
    '''
    return timedelta(seconds=round((time.time() if t1_sec is None else t1_sec) - t0_sec))


def closesession(session):
    '''closes the session, 
    This method simply calls `session.close()`, passing all exceptions, if any. Useful for unit
    testing and mock
    '''
    try:
        session.close()
    except:
        pass

def show(dburl, pyfile, configfile):
    run_in_browser(create_p_app(dburl, pyfile, configfile))
    return 0


def show_download_report(dburl):
    run_in_browser(create_d_app(dburl))
    return 0


def init(outpath, prompt=True, *filenames):
    # get the template files. Use all files except those with more than one dot
    # This might be better implemented
    if not os.path.isdir(outpath):
        os.makedirs(outpath)
        if not os.path.isdir(outpath):
            raise Exception("Unable to create '%s'" % outpath)
    template_files = get_templates_fpaths(*filenames)
    if prompt:
        existing_files = [t for t in template_files
                          if os.path.isfile(os.path.join(outpath, os.path.basename(t)))]
        non_existing_files = [t for t in template_files if t not in existing_files]
        if existing_files:
            suffix = ("Type:\n1: overwrite all files\n2: write only non-existing\n"
                      "0 or any other value: do nothing (exit)")
            msg = ("The following file(s) "
                   "already exist on '%s':\n%s"
                   "\n\n%s") % (outpath, "\n".join([os.path.basename(_)
                                                    for _ in existing_files]), suffix)
            val = click.prompt(msg)
            try:
                val = int(val)
                if val == 2:
                    if not len(non_existing_files):
                        raise ValueError()
                    else:
                        template_files = non_existing_files
                elif val != 1:
                    raise ValueError()
            except ValueError:
                return []
    copied_files = []
    for tfile in template_files:
        shutil.copy2(tfile, outpath)
        copied_files.append(os.path.join(outpath, os.path.basename(tfile)))
    return copied_files


class BadParameter(ValueError):
    '''An exception that needs to be raised when a bad parameter value is encountered.
    It inherits from click.BadParameter so that it can be processed by click, and when raised
    as "normal" exception and caught by some other function it provides the same formatted message
    than click
    '''
    def __init__(self, error_msg, param_name=None):
        '''Calls the super constructor without context and param information but
        providing explicitly a parameter name'''
        super(BadParameter, self).__init__(str(error_msg))
        self.param_name = str(param_name) if param_name else None

    @property
    def message(self):
        err_msg = self.args[0]  # in ValueError, is the error_msg passed in the constructor
        if self.param_name:
            msg = "Invalid value for %s: %s" % (self.param_name, err_msg)
        else:
            msg = err_msg
        return msg

    def toClickExc(self):
        return click.BadParameter(self.message, param_hint=self.param_name)
    
    def __str__(self):
        ''''''
        return "Error: %s" % self.message
    

class MissingConfigfileParameter(BadParameter):
    
    def __init__(self, param_name=None):
        super(MissingConfigfileParameter, self).__init__('Missing parameter in config. file',
                                                         param_name)
    
    def toClickExc(self):
        return click.MissingParameter('', param_hint=self.param_name or None)
    
    @property
    def message(self):
        # in ValueError, is the error_msg passed in the constructor
        return "%s%s" % (self.args[0], (': ' + str(self.param_name)) if self.param_name else '')


def helpmathiter(type, filter):  # @ReservedAssignment pylint: disable=redefined-outer-name
    '''iterator yielding the doc-string of :module:`stream2segment.process.math.ndarrays` or
    :module:`stream2segment.process.math.traces`

    :param type: select the module: 'numpy' for doc of
        :module:`stream2segment.process.math.ndarrays`,
        'obspy' for the doc of :module:`stream2segment.process.math.traces`, 'all' for both

    :param filter: a filter (with wildcard expressions allowed) to filter by function name

    :return: doc-string for all matching functions and classes
    '''
    itr = [s2s_math.ndarrays] if type == 'numpy' else [s2s_math.traces] if type == 'obspy' else \
        [s2s_math.ndarrays, s2s_math.traces]
    reg = re.compile(strconvert.wild2re(filter))
    INDENT = "   "

    def render(string, indent_num=0):
        '''renders a string stripping newlines at beginning and end and with the intended indent
        number'''
        if not indent_num:
            return string
        indent = INDENT.join('' for _ in range(indent_num+1))
        return '\n'.join("%s%s" % (indent, s) for s in
                         string.replace('\r\n', '\n').split('\n'))

    for pymodule in itr:
        module_doc_printed = False
        for func in iterfuncs(pymodule, False):
            if func.__name__[0] != '_' and reg.search(func.__name__):
                if not module_doc_printed:
                    modname = pymodule.__name__
                    yield "=" * len(modname)
                    yield modname
                    yield "=" * len(modname)
                    yield pymodule.__doc__
                    module_doc_printed = True
                    yield "-" * len(modname) + "\n"
                yield "%s%s:" % (func.__name__, inspect.signature(func))
                yield render(func.__doc__ or '(No documentation found)', indent_num=1)
                if inspect.isclass(func):
                    for funcname, func in inspect.getmembers(func):
                        if funcname != "__class__" and not funcname.startswith("_"):
                            # Consider anything that starts with _ private
                            # and don't document it
                            yield "\n"
                            yield "%s%s%s:" % (INDENT, funcname, inspect.signature(func))
                            yield render(func.__doc__, indent_num=2)

                yield "\n"
