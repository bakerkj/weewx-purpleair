# -*- coding: utf-8 -*-
# Copyright 2018 Kenneth Baker <bakerkj@umich.edu>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

"""weewx module that records PurpleAir air quality data.

This is directly modeled after the weewx cmon plugin
(https://github.com/weewx/weewx/wiki/cmon) by Matthew Wall.

This file contains a weewx service.

Installation

Put this file in the bin/user directory.


Service Configuration

Add the following to weewx.conf:

[PurpleAirMonitor]
    data_binding = purpleair_binding
    hostname = <URL of purpleair sensor> OR <ID# of purpleair sensor>
    port = 80

[DataBindings]
    [[purpleair_binding]]
        database = purpleair_sqlite
        manager = weewx.manager.DaySummaryManager
        table_name = archive
        schema = user.purpleair.schema

[Databases]
    [[purpleair_sqlite]]
        root = %(WEEWX_ROOT)s
        database_name = archive/purpleair.sdb
        driver = weedb.sqlite

"""

# FIXME: ...

import sys
import time
import requests
import configobj

import weewx
import weeutil.weeutil
from weewx.engine import StdService
import weewx.units

WEEWX_PURPLEAIR_VERSION = "0.4"

PY3 = sys.version_info[0] == 3

if PY3:
    binary_type = bytes
else:
    binary_type = str


if weewx.__version__ < "3":
    raise weewx.UnsupportedFeature("weewx 3 is required, found %s" %
                                   weewx.__version__)

# set up appropriate units
weewx.units.USUnits['group_concentration'] = 'microgram_per_meter_cubed'
weewx.units.MetricUnits['group_concentration'] = 'microgram_per_meter_cubed'
weewx.units.MetricWXUnits['group_concentration'] = 'microgram_per_meter_cubed'
weewx.units.default_unit_format_dict['microgram_per_meter_cubed'] = '%.3f'
weewx.units.default_unit_label_dict['microgram_per_meter_cubed']  = u'µg/m³',

# assign types of units to specific measurements
weewx.units.obs_group_dict['purple_temperature'] = 'group_temperature'
weewx.units.obs_group_dict['purple_humidity'] = 'group_percent'
weewx.units.obs_group_dict['purple_pressure'] = 'group_pressure'
weewx.units.obs_group_dict['pm1_0_cf_1'] = 'group_concentration'
weewx.units.obs_group_dict['pm1_0_atm'] = 'group_concentration'
weewx.units.obs_group_dict['pm2_5_cf_1'] = 'group_concentration'
weewx.units.obs_group_dict['pm2_5_atm'] = 'group_concentration'
weewx.units.obs_group_dict['pm10_0_cf_1'] = 'group_concentration'
weewx.units.obs_group_dict['pm10_0_atm'] = 'group_concentration'

# our schema
schema = [
    ('dateTime', 'INTEGER NOT NULL PRIMARY KEY'),
    ('usUnits', 'INTEGER NOT NULL'),
    ('interval', 'INTEGER NOT NULL'),
    ('purple_temperature','REAL'),
    ('purple_humidity','REAL'),
    ('purple_dewpoint','REAL'),
    ('purple_pressure','REAL'),
    ('pm1_0_cf_1','REAL'),
    ('pm1_0_atm','REAL'),
    ('pm2_5_cf_1','REAL'),
    ('pm2_5_atm','REAL'),
    ('pm10_0_cf_1','REAL'),
    ('pm10_0_atm','REAL'),
    ]


try:
    # Test for new-style weewx logging by trying to import weeutil.logger
    import weeutil.logger
    import logging
    log = logging.getLogger(__name__)

    def logdbg(msg):
        log.debug(msg)

    def loginf(msg):
        log.info(msg)

    def logerr(msg):
        log.error(msg)

except ImportError:
    # Old-style weewx logging
    import syslog

    def logmsg(level, msg):
        syslog.syslog(level, 'purpleair: %s:' % msg)

    def logdbg(msg):
        logmsg(syslog.LOG_DEBUG, msg)

    def loginf(msg):
        logmsg(syslog.LOG_INFO, msg)

    def logerr(msg):
        logmsg(syslog.LOG_ERR, msg)


def collect_data(session, hostname, port, timeout, now_ts = None):
    # used for testing
    if now_ts is None:
        now_ts = int(time.time() + 0.5)

    if isinstance(hostname, binary_type):
        hostname = hostname.decode('utf-8')

    # fetching data from www.purpleair.com
    if hostname.isnumeric():
        r = session.get(url="https://www.purpleair.com/json?show=%s" % (hostname), timeout=timeout)
        is_data_from_purpleair_website = True

    # fetching data from local device
    else:
        r = session.get(url="http://%s:%s/json" % (hostname, port), timeout=timeout)
        is_data_from_purpleair_website = False

    # raise error if status is invalid
    r.raise_for_status()
    # convert to json
    if is_data_from_purpleair_website:
        rj = r.json()
        j = rj['results'][0]
        k = rj['results'][1]
    else:
        j = r.json()

    record = dict()
    record['dateTime'] = now_ts
    record['usUnits'] = weewx.US

    # put items into record
    missed = []

    def get_and_update_missed(key):
        if key in j:
            return float(j[key])
        else:
            missed.append(key)
            return None

    if is_data_from_purpleair_website:
        record['purple_temperature'] = get_and_update_missed('temp_f')
        record['purple_humidity'] = get_and_update_missed('humidity')
    else:
        record['purple_temperature'] = get_and_update_missed('current_temp_f')
        record['purple_humidity'] = get_and_update_missed('current_humidity')
        record['purple_dewpoint'] = get_and_update_missed('current_dewpoint_f')
    
    pressure = get_and_update_missed('pressure')
    if pressure is not None:
        # convert pressure from mbar to US units.
        # FIXME: is there a cleaner way to do this
        pressure, units, group = weewx.units.convertStd((pressure, 'mbar', 'group_pressure'), weewx.US)
        record['purple_pressure'] = pressure

    if missed:
        loginf("sensor didn't report field(s): %s" % ','.join(missed))

    # for each concentration counter grab the average of the A and B channels and push into the record
    for key in ['pm1_0_cf_1', 'pm1_0_atm', 'pm2_5_cf_1', 'pm2_5_atm', 'pm10_0_cf_1', 'pm10_0_atm']:
        if is_data_from_purpleair_website:
            valA = float(j[key])
            valB = float(k[key])
        else:
            valA = float(j[key])
            valB = float(j[key + '_b'])
        if valA == 0.0 and valB != 0.0:
            record[key] = valB
        elif valB == 0.0 and valA != 0.0:
            record[key] = valA
        else:
            record[key] = (valA + valB) / 2.0
    return record


class PurpleAirMonitor(StdService):
    """Collect Purple Air air quality measurements."""

    def __init__(self, engine, config_dict):
        super(PurpleAirMonitor, self).__init__(engine, config_dict)
        loginf("service version is %s" % WEEWX_PURPLEAIR_VERSION)

        self.config_dict = config_dict.get('PurpleAirMonitor', {})
        try:
            self.config_dict['hostname']
        except KeyError as e:
            raise Exception("Data will not be posted: Missing option %s" % e)

        self.config_dict.setdefault('port', 80) # default port is HTTP
        self.config_dict.setdefault('timeout', 10) # url fetch timeout

        # get the database parameters we need to function
        binding = self.config_dict.get('data_binding', 'purpleair_binding')
        self.dbm = self.engine.db_binder.get_manager(data_binding=binding, initialize=True)

        # be sure schema in database matches the schema we have
        dbcol = self.dbm.connection.columnsOf(self.dbm.table_name)
        dbm_dict = weewx.manager.get_manager_dict(
            config_dict['DataBindings'],
            config_dict['Databases'],
            binding)

        memcol = [x[0] for x in dbm_dict['schema']]
        if dbcol != memcol:
            raise Exception('purpleair schema mismatch: %s != %s' % (dbcol, memcol))

        self.last_ts = None
        # listen for NEW_ARCHIVE_RECORDS
        self.bind(weewx.NEW_ARCHIVE_RECORD, self.new_archive_record)
        # create a session
        self.session = requests.Session()

    def shutDown(self):
        try:
            self.dbm.close()
        except:
            pass
        try:
            self.session.close()
        except:
            pass

    def new_archive_record(self, event):
        """save data to database"""
        now = int(time.time() + 0.5)
        delta = now - event.record['dateTime']
        if delta > event.record['interval'] * 60:
            logdbg("Skipping record: time difference %s too big" % delta)
            return
        if self.last_ts is not None:
            try:
                data = self.get_data(now, self.last_ts)
            except Exception as e:
                # failure to fetch data, log and then return
                logerr(e)
                return
            self.save_data(data)
        self.last_ts = now

    def save_data(self, record):
        """save data to database"""
        self.dbm.addRecord(record)

    def get_data(self, now_ts, last_ts):
        record = collect_data(self.session, self.config_dict['hostname'],
                              weeutil.weeutil.to_int(self.config_dict['port']),
                              weeutil.weeutil.to_int(self.config_dict['timeout']),
                              now_ts)
        record['interval'] = max(1, int((now_ts - last_ts) / 60))
        return record


# To test this extension, do the following:
#
# cd /home/weewx
# PYTHONPATH=bin python bin/user/purpleair.py
#
if __name__ == "__main__":
    usage = """%prog [options] [--help] [--debug]"""

    def main():
        import optparse
        # WeeWX Version 3.x uses syslog, later versions use logging.
        try:
            syslog.openlog('wee_purpleair', syslog.LOG_PID | syslog.LOG_CONS)
        except NameError:
            pass
        parser = optparse.OptionParser(usage=usage)
        parser.add_option('--config', dest='cfgfn', type=str, metavar="FILE",
                          help="Use configuration file FILE. Default is /etc/weewx/weewx.conf or /home/weewx/weewx.conf")
        parser.add_option('--binding', dest="binding", metavar="BINDING",
                          default='purpleair_binding',
                          help="The data binding to use. Default is 'purpleair_binding'.")
        parser.add_option('--test-collector', dest='tc', action='store_true',
                          help='test the data collector')
        parser.add_option('--hostname', dest='hostname', action='store',
                          help='hostname to use with --test-collector')
        parser.add_option('--port', dest='port', action='store',
                          type=int, default=80,
                          help="port to use with --test-collector. Default is '80'")
        parser.add_option('--test-service', dest='ts', action='store_true',
                          help='test the service')
        (options, args) = parser.parse_args()

        if options.tc:
            if not options.hostname:
                parser.error("--test-collector requires --hostname argument")
            test_collector(options.hostname, options.port)
        elif options.ts:
            if not options.hostname:
                parser.error("--test-service requires --hostname argument")
            test_service(options.hostname, options.port)

    def test_collector(hostname, port):
        session = requests.Session()
        while True:
            print (collect_data(session, hostname, port, 10))
            time.sleep(5)

    def test_service(hostname, port):
        from weewx.engine import StdEngine
        from tempfile import NamedTemporaryFile

        with NamedTemporaryFile() as temp_file:
            config = configobj.ConfigObj({
                'Station': {
                    'station_type': 'Simulator',
                    'altitude': [0, 'foot'],
                    'latitude': 0,
                    'longitude': 0},
                'Simulator': {
                    'driver': 'weewx.drivers.simulator',
                    'mode': 'simulator'},
                'PurpleAirMonitor': {
                    'binding': 'purpleair_binding',
                    'hostname': hostname,
                    'port': port},
                'DataBindings': {
                    'purpleair_binding': {
                        'database': 'purpleair_sqlite',
                        'manager': 'weewx.manager.DaySummaryManager',
                        'table_name': 'archive',
                        'schema': 'user.purpleair.schema'}},
                'Databases': {
                    'purpleair_sqlite': {
                        'root': '%(WEEWX_ROOT)s',
                        'database_name': temp_file.name,
                        'driver': 'weedb.sqlite'}},
                'Engine': {
                    'Services': {
                        'archive_services': 'user.purpleair.PurpleAirMonitor'}}})
            engine = StdEngine(config)
            svc = PurpleAirMonitor(engine, config)
            for _ in range(4):
                record = {
                    'dateTime': int(time.time()),
                    'interval': 1
                }
                event = weewx.Event(weewx.NEW_ARCHIVE_RECORD, record=record)
                svc.new_archive_record(event)

                time.sleep(5)
    main()
