purpleair - collect Purple Air air quality data
Copyright 2018 - Kenneth Baker

purpleair is a weewx extension to collect data from the local
interface of a Purple Air air sensor (https://www.purpleair.com/). It
saves this data to its own database which can then be displayed in
weewx reports and graphs.  The data is saved at the archive interval
of the station.

1) run the installer (from the git directory):
   wee_extension --install . 

2) restart weewx:

  sudo /etc/init.d/weewx stop
  sudo /etc/init.d/weewx start


This will install the purpleair.py extension into the weewx/user/
directory.  It will also add the necessary data bindings, hostname,
database, and service configuration to the weewx.conf configuration
file.

Something like the following:
  [PurpleAirMonitor]
    data_binding = purpleair_binding
    hostname = purple-air
  [DataBindings]
    [[purpleair_binding]]
        database = purpleair_sqlite
        manager = weewx.manager.DaySummaryManager
        table_name = archive
        schema = user.purpleair.schema

  [Databases]
    [[purpleair_sqlite]]
        database_name = purpleair.sdb
        driver = weedb.sqlite

To make use of the plugin you will need to modify the templates in
/etc/weewx/skins/*.tmpl to include references to the new data found in
the purpleair.sdb file.

Examples:
  The current value:
    $latest('purpleair_binding').pm2_5_cf_1.formatted
  The maximum value today:
    $day('purpleair_binding').pm2_5_cf_1.max.formatted
  The time today when the maximum value occurred:
    $day('purpleair_binding').pm2_5_cf_1.maxtime
  The units:
    $unit.label.pm2_5_cf_1

You can also graph these values by adding the appropriate
configuration to your skin.conf file:
  [[[daypurpleair]]]
    data_binding = purpleair_binding
    [[[[pm2_5_cf_1]]]]
				
The values stored in the database are as follows:
  purple_temperature
  purple_humidity
  purple_pressure
  pm1_0_cf_1
  pm1_0_atm
  pm2_5_cf_1
  pm2_5_atm
  pm10_0_cf_1
  pm10_0_atm


The pm*_* values stored in the database are averages from the two
sensors contained in the sensor.

More details about these values can be found in the document referred
to in this post:
  https://groups.google.com/d/msg/weewx-user/hzN9K3QH7kU/v4ETARANBQAJ
