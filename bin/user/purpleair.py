# -*- coding: utf-8 -*-
# Copyright 2021-2023 Kenneth Baker <bakerkj@umich.edu>
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
    interval = <how often to fetch data in seconds>
    ### optional
    api_key = <Read API key retrieved from PurpleAir support (contact@purpleair.com)>

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
import threading
import socket
import math
import datetime

import weewx
import weeutil.weeutil
from weewx.engine import StdService
import weewx.units

WEEWX_PURPLEAIR_VERSION = "0.8"

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
weewx.units.default_unit_label_dict['microgram_per_meter_cubed']  = u'µg/m³'

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


def collect_data(session, hostname, port, timeout, api_key):
    if isinstance(hostname, binary_type):
        hostname = hostname.decode('utf-8')

    # fetching data from www.purpleair.com
    if hostname.isnumeric():
        # get only required fields to save purpleair API points
        api_fields = ["temperature", "humidity", "pressure", "last_seen",
                      "pm1.0_cf_1_a", "pm1.0_cf_1_b",
                      "pm1.0_atm_a", "pm1.0_atm_b",
                      "pm2.5_cf_1_a", "pm2.5_cf_1_b",
                      "pm2.5_atm_a", "pm2.5_atm_b",
                      "pm10.0_cf_1_a", "pm10.0_cf_1_b",
                      "pm10.0_atm_a", "pm10.0_atm_b"]

        url = "https://api.purpleair.com/v1/sensors/%s?api_key=%s&fields=%s" % (hostname, api_key, ",".join(api_fields))
        r = session.get(url, timeout=timeout)
        is_data_from_purpleair_website = True

    # fetching data from local device
    else:
        r = session.get(url="http://%s:%s/json" % (hostname, port), timeout=timeout)
        is_data_from_purpleair_website = False

    # update data only when "last_seen/response_date" is not older than 10 minutes - makes sense for purpleair website only
    valid_timeout = datetime.timedelta(minutes=10)

    # raise error if status is invalid
    r.raise_for_status()
    # convert to json
    if is_data_from_purpleair_website:
        rj = r.json()
        j = rj['sensor']
        last_seen = datetime.datetime.utcfromtimestamp(j['last_seen'])
    else:
        j = r.json()
        last_seen = datetime.datetime.utcfromtimestamp(j['response_date'])

    record = dict()
    record['dateTime'] = int(time.time())
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
        record['purple_temperature'] = get_and_update_missed('temperature')
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

    # when last seen field is older than 10 minutes do not return any particle data
    if datetime.datetime.utcnow() - last_seen < valid_timeout:
        # for each concentration counter grab the average of the A and B channels and push into the record

        # NEWLY are values from PA website json with dot so it´s necessary to remap it
        remap_dot = {'pm1_0_cf_1':'pm1.0_cf_1','pm1_0_atm':'pm1.0_atm','pm2_5_cf_1':'pm2.5_cf_1',\
                   'pm2_5_atm':'pm2.5_atm','pm10_0_cf_1':'pm10.0_cf_1','pm10_0_atm':'pm10.0_atm'}

        for key in ['pm1_0_cf_1', 'pm1_0_atm', 'pm2_5_cf_1', 'pm2_5_atm', 'pm10_0_cf_1', 'pm10_0_atm']:
            if is_data_from_purpleair_website:
                valA = float(j[remap_dot[key] + '_a'])
                valB = float(j[remap_dot[key] + '_b'])
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
            if self.config_dict['hostname'].isnumeric():
                self.config_dict['api_key']
        except KeyError as e:
            raise Exception("Data will not be posted: Missing option %s" % e)

        self.config_dict.setdefault('port', 80) # default port is HTTP
        self.config_dict.setdefault('timeout', 10) # url fetch timeout
        self.config_dict.setdefault('interval', 300) # how often to fetch data
        self.config_dict.setdefault('api_key', 'API_KEY') # API_KEY to get data from PurpleAir website

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

        # listen for NEW_ARCHIVE_RECORDS
        self.bind(weewx.NEW_ARCHIVE_RECORD, self.new_archive_record)

        # init and start up data collection thread
        self._thread = PurpleAirMonitorDataThread(self.config_dict)
        self._thread.start()

    def shutDown(self):
        try:
            self.dbm.close()
        except:
            pass

        if self._thread:
            self._thread.running = False
            self._thread.join()
            self._thread = None

    def new_archive_record(self, event):
        """save data to database"""
        record = self._thread.get_record()
        if not record:
            logdbg("Skipping record: empty")
        else:
            delta = math.fabs(record['dateTime'] - event.record['dateTime'])
            if delta > self.config_dict['interval'] * 1.5:
                logdbg("Skipping record: time difference %f too big" % delta)
            else:
                self.save_data(record)

    def save_data(self, record):
        """save data to database"""
        self.dbm.addRecord(record)



class PurpleAirMonitorDataThread(threading.Thread):
    def __init__(self, config_dict):
        threading.Thread.__init__(self, name="PurpleAirMonitor")
        self.config_dict = config_dict
        self._lock = threading.Lock()
        self._record = None
        self.running = False

    def get_record(self):
        with self._lock:
            if not self._record:
                return None
            else:
                return self._record.copy()

    def run(self):
        # starting thread running
        self.running = True

        # create a session
        session = requests.Session()

        # keep track of the last time we aquired the data
        last_ts = None
        while self.running:
            try:
                # if we haven't fetched data before, or the last time we fetched the data was longer than an interval
                if not last_ts or time.time() - last_ts >= weeutil.weeutil.to_int(self.config_dict['interval']):
                    record = collect_data(session, self.config_dict['hostname'],
                                          weeutil.weeutil.to_int(self.config_dict['port']),
                                          weeutil.weeutil.to_int(self.config_dict['timeout']),
                                          self.config_dict['api_key'])
                    record['interval'] = int(weeutil.weeutil.to_int(self.config_dict['interval']) / 60)

                    with self._lock:
                        self._record = record

                    # store the last time data was fetched successfully
                    last_ts = time.time()

                time.sleep(1)

            except socket.error as e:
                loginf("Socket error: %s" % e)
                time.sleep(weeutil.weeutil.to_int(self.config_dict['interval']))
            except requests.RequestException as e:
                loginf("Requests error: %s" % e)
                time.sleep(weeutil.weeutil.to_int(self.config_dict['interval']))
            except Exception as e:
                loginf("Exception: %s" % e)
                time.sleep(weeutil.weeutil.to_int(self.config_dict['interval']))

        try:
            session.close()
        except:
            pass


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
            syslog.openlog('weewx_purpleair', syslog.LOG_PID | syslog.LOG_CONS)
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
        parser.add_option('--api-key', dest='api_key', action='store',
                          help='purple air website api key', default=None)
        (options, args) = parser.parse_args()

        if options.tc:
            if not options.hostname:
                parser.error("--test-collector requires --hostname argument")
            test_collector(options.hostname, options.port, options.api_key)
        elif options.ts:
            if not options.hostname:
                parser.error("--test-service requires --hostname argument")
            test_service(options.hostname, options.port)

    def test_collector(hostname, port, apikey):
        session = requests.Session()
        while True:
            print (collect_data(session, hostname, port, 10, apikey))
            time.sleep(5)

    def test_service(hostname, port):
        from weewx.engine import StdEngine, DummyEngine
        from tempfile import NamedTemporaryFile

        INTERVAL = 60
        NUM_INTERATIONS = 3

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
                    'port': port,
                    'interval': INTERVAL},
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
                        'archive_services': 'user.purpleair.PurpleAirMonitor'
                    }
                }})

            weeutil.logger.setup("weewx_purpleair", {
                'Logging': {
                    'root' : {
                        'handlers': ['console' ]
                    }
                }
            })

            print("NOTICE: please be patient this will take ~%d seconds to run" % (INTERVAL * (NUM_INTERATIONS - 0.5)))

            engine = DummyEngine(config)
            manager = engine.db_binder.get_manager(data_binding='purpleair_binding')

            last_time = time.time()
            try:
                # wait a moment for the 1st download
                time.sleep(INTERVAL / 2)

                for x in range(NUM_INTERATIONS):
                    record = {
                        'dateTime': int(time.time()),
                    }
                    event = weewx.Event(weewx.NEW_ARCHIVE_RECORD, record=record)
                    engine.dispatchEvent(event)

                    # get and print all the current records
                    now_time = time.time()
                    for record in manager.genBatchRecords(last_time - 1, now_time + 1):
                        print(record)

                    # update the time window
                    last_time = now_time

                    # wait for the INTERVAL if this isn't the last cycle
                    if x < NUM_INTERATIONS - 1:
                        time.sleep(INTERVAL)

            except KeyboardInterrupt:
                pass
            finally:
                try:
                    svc.shutDown()
                except:
                    pass
            engine.shutDown()

    main()
