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
    hostname = purple-air.example.com
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

import os
import syslog
import time
import requests
import configobj

import weewx
import weeutil.weeutil
from weewx.engine import StdService
import weewx.units

WEEWX_PURPLEAIR_VERSION = "0.1"

if weewx.__version__ < "3":
    raise weewx.UnsupportedFeature("weewx 3 is required, found %s" %
                                   weewx.__version__)

# set up appropriate units
weewx.units.USUnits['group_concentration'] = 'microgram_per_meter_cubed'
weewx.units.MetricUnits['group_concentration'] = 'microgram_per_meter_cubed'
weewx.units.MetricWXUnits['group_concentration'] = 'microgram_per_meter_cubed'
weewx.units.default_unit_format_dict['microgram_per_meter_cubed'] = '%.3f'
weewx.units.default_unit_label_dict['microgram_per_meter_cubed']  = ' \xc2\xb5g/m\xc2\xb3'

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
    ('aqi2_5','INTEGER'),
    ]

def logmsg(level, msg):
    syslog.syslog(level, 'purpleair: %s' % msg)

def logdbg(msg):
    logmsg(syslog.LOG_DEBUG, msg)

def loginf(msg):
    logmsg(syslog.LOG_INFO, msg)

def logerr(msg):
    logmsg(syslog.LOG_ERR, msg)

# the various ranges of AQI vs. pm2_5 observations
# ref: https://www.airnow.gov/index.cfm?action=aqibasics.aqi
AQImapping = {
   "green" : { 'AQImin':   0, 'AQImax':  50, 'PMmin':   0  , 'PMmax':  15.4, 'Category': "Good"                           },
   "yellow": { 'AQImin':  51, 'AQImax': 100, 'PMmin':  15.5, 'PMmax':  40.4, 'Category': "Moderate"                       },
   "orange": { 'AQImin': 101, 'AQImax': 150, 'PMmin':  40.5, 'PMmax':  65.4, 'Category': "Unhealthy for Sensitive Groups" },
   "red"   : { 'AQImin': 151, 'AQImax': 200, 'PMmin':  65.5, 'PMmax': 150.5, 'Category': "Unhealthy"                      },
   "purple": { 'AQImin': 201, 'AQImax': 300, 'PMmin': 150.5, 'PMmax': 250.4, 'Category': "Very Unhealthy"                 },
   "maroon": { 'AQImin': 301, 'AQImax': 500, 'PMmin': 250.5, 'PMmax': 500.4, 'Category': "Hazardous"                      },
}

# the mapping matching this particular observation is later used by calculateAQI() below
def lookUpColor(PMobs):
  for mapping in AQImapping:
    if (PMobs >= AQImapping[mapping]['PMmin']) and (PMobs <= AQImapping[mapping]['PMmax'] ):
        return (mapping,AQImapping[mapping])

# calculate AQI based on passed in values for that color range ---
#    PMobs  = current observation of PM2.5 in micrograms per cubic liter
#    PMmin  = concentration breakpoint that is <= PMobs
#    PMmax  = concentration breakpoint that is >= PMobs
#    AQImin = index breakpoint corresponding to PMmin
#    AQImax = index breakpoint corresponding to PMmax
def calculateAQI(PMobs,PMmin,PMmax,AQImin,AQImax):
    AQI = ( ( ( ( PMobs - PMmin ) * ( AQImax - AQImin ) ) / ( PMmax - PMmin) ) + AQImin )
    return int(AQI)

def collect_data(session, hostname, timeout, now_ts = None):
    # used for testing
    if now_ts is None:
        now_ts = int(time.time() + 0.5)

    record = dict()
    record['dateTime'] = now_ts
    record['usUnits'] = weewx.US

    # fetch data
    r = session.get(url="http://%s/json" % (hostname), timeout=timeout)
    # raise error if status is invalid
    r.raise_for_status()
    # convert to json
    j = r.json()

    # put items into record
    record['purple_temperature'] = j['current_temp_f']
    record['purple_humidity'] = j['current_humidity']
    record['purple_dewpoint'] = j['current_dewpoint_f']

    # convert pressure from mbar to US units.
    # FIXME: is there a cleaner way to do this
    pressure, units, group = weewx.units.convertStd((j['pressure'], 'mbar', 'group_pressure'), weewx.US)
    record['purple_pressure'] = pressure

    # for each concentration counter grab the average of the A and B channels and push into the record
    for key in ['pm1_0_cf_1', 'pm1_0_atm', 'pm2_5_cf_1', 'pm2_5_atm', 'pm10_0_cf_1', 'pm10_0_atm']:
        record[key] = (j[key] + j[key + '_b']) / 2.0

    # calculate AQI based on average observed data from the sensors
    # and the mapping ranges that match this particular observation
    PMobs=record['pm2_5_cf_1']
    try:
        (color,mapping) = lookUpColor(PMobs)
    except:
        # hopefully this will return null for AQI if we got bad data outside a known range
        logdbg("purpleair - cannot find mapping for pm2_5_cf_1 = %s" % record['pm2_5_cf_1'])
        return record

    # we should only get here if we can map the PMobs to a color range
    PMmax    = mapping['PMmax']
    PMmin    = mapping['PMmin']
    AQImax   = mapping['AQImax']
    AQImin   = mapping['AQImin']
    Category = mapping['Category']
    AQIcalc = calculateAQI(PMobs, PMmin, PMmax, AQImin, AQImax)
    record['aqi2_5'] = AQIcalc

    # this could be a logdbg() message for high levels of debugging potentially
    #####print("color:",color,", PMobs:",PMobs,", AQI:",AQIcalc,", Category:",Category)

    return record

class PurpleAirMonitor(StdService):
    """Collect Purple Air air quality measurements."""

    def __init__(self, engine, config_dict):
        super(PurpleAirMonitor, self).__init__(engine, config_dict)
        loginf("service version is %s" % WEEWX_PURPLEAIR_VERSION)

        self.config_dict = config_dict.get('PurpleAirMonitor', {})
        try:
            self.config_dict['hostname']
        except KeyError, e:
            raise Exception("Data will not be posted: Missing option %s" % e)

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
            except Exception, e:
                # failure to fetch data, log and then return
                logerr(e)
                return
            self.save_data(data)
        self.last_ts = now

    def save_data(self, record):
        """save data to database"""
        self.dbm.addRecord(record)

    def get_data(self, now_ts, last_ts):
        record = collect_data(self.session, self.config_dict['hostname'], weeutil.weeutil.to_int(self.config_dict['timeout']), now_ts)
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
        import weecfg
        syslog.openlog('wee_purpleair', syslog.LOG_PID | syslog.LOG_CONS)
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
        parser.add_option('--test-service', dest='ts', action='store_true',
                          help='test the service')
        (options, args) = parser.parse_args()

        if options.tc:
            if not options.hostname:
                parser.error("--test-collector requires --hostname argument")
            test_collector(options.hostname)
        elif options.ts:
            if not options.hostname:
                parser.error("--test-service requires --hostname argument")
            test_service(options.hostname)

    def test_collector(hostname):
        session = requests.Session()
        while True:
            print collect_data(session, hostname, 10)
            time.sleep(5)

    def test_service(hostname):
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
                    'hostname': hostname},
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
