# Purple Air - collect Purple Air air quality data

Copyright 2021-2023 - Kenneth Baker <bakerkj@umich.edu>

## What is it?
purpleair is a weewx extension to collect data from the local
interface of a Purple Air air sensor
(<https://www.purpleair.com/>). It saves this data to its own database
which can then be displayed in weewx reports and graphs.  The data is
saved at the archive interval of the station.

## Prerequisites

1) Purpleair requires the _requests_ Python library. This library does not
   come with the default installation of Python. It must be installed
   separately. Perhaps the fastest way to do so is to run:

    pip install requests

    or on a debian/ubuntu system run:

    apt install python-requests

## Installation

1) run the installer (from the git directory):

    wee_extension --install . 

2) restart weewx:

    sudo /etc/init.d/weewx stop
    sudo /etc/init.d/weewx start

This will install the purpleair.py extension into the weewx/user/
directory.  It will also add the necessary data bindings, hostname,
port number, database, and service configuration to the weewx.conf
configuration file.

Something like the following:

    [PurpleAirMonitor]
        data_binding = purpleair_binding
        hostname = purple-air.example.com
        port = 80
        # how often to fetch purple air data measured in seconds
        # should match your stations archive interval
        interval = 300
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

## Display the data

To make use of the plugin you will need to modify the templates in
/etc/weewx/skins/*.tmpl to include references to the new data found in
the purpleair.sdb file.

### Examples:
* The current value:

```$latest('purpleair_binding').pm2_5_cf_1```
    
* The maximum value today:

```$day('purpleair_binding').pm2_5_cf_1.max```

* The time today when the maximum value occurred:

```$day('purpleair_binding').pm2_5_cf_1.maxtime```

* The units:

```$unit.label.pm2_5_cf_1```

You can also graph these values by adding the appropriate
configuration to your skin.conf file:

    [[[daypurpleair]]]
        data_binding = purpleair_binding
        [[[[pm2_5_cf_1]]]]

The values stored in the database are as follows:

```
purple_temperature
purple_humidity
purple_pressure
pm1_0_cf_1
pm1_0_atm
pm2_5_cf_1
pm2_5_atm
pm10_0_cf_1
pm10_0_atm
```

### Notes

The `pm*_*` values stored in the database are averages from the two
sensors contained in the sensor.

More details about these values can be found in the document referred
to here <https://groups.google.com/d/msg/weewx-user/hzN9K3QH7kU/v4ETARANBQAJ>.
  
