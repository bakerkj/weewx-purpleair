# Copyright 2017 Ken Baker

from setup import ExtensionInstaller

def loader():
    return PurpleAirMonitorInstaller()

class PurpleAirMonitorInstaller(ExtensionInstaller):
    def __init__(self):
        super(PurpleAirMonitorInstaller, self).__init__(
            version="0.1",
            name='purpleair',
            description='Collect Purple Air air quality data.',
            author="Kenneth Baker",
            author_email="bakerkj@umich.edu",
            process_services='user.cmon.PurpleAirMonitor',
            config={
                'PurpleAirMonitor': {
                    'data_binding': 'purpleair_binding',
                    'hostname': 'purple-air' },
                'DataBindings': {
                    'purpleair_binding': {
                        'database': 'purpleair_sqlite',
                        'table_name': 'archive',
                        'manager': 'weewx.manager.DaySummaryManager',
                        'schema': 'user.purpleair.schema'}},
                'Databases': {
                    'purpleair_sqlite': {
                        'database_name': 'purpleair.sdb',
                        'driver': 'weedb.sqlite'}},
            },
            files=[('bin/user', ['bin/user/purpleair.py']), ]
            )
