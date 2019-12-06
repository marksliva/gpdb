@cross_subnet
Feature: cross subnet tests

    Scenario: gpinitsystem succeeds across subnets
        Given the database is running
          And all the segments are running
          And the segments are synchronized

  Scenario: gpaddmirrors: gprecoverseg works correctly on a newly added mirror with HBA_HOSTNAMES=0
    Given a working directory of the test as '/tmp/gpaddmirrors'
    And the database is not running
    And with HBA_HOSTNAMES "0" a cluster is created with no mirrors on "mdw-1" and "sdw1-1, sdw1-2"
    And pg_hba file "/tmp/gpaddmirrors/data/primary/gpseg0/pg_hba.conf" on host "sdw1-1" contains only cidr addresses
    And gpaddmirrors adds mirrors
    And pg_hba file "/tmp/gpaddmirrors/data/primary/gpseg0/pg_hba.conf" on host "sdw1-1" contains only cidr addresses
    And pg_hba file "/tmp/gpaddmirrors/data/primary/gpseg0/pg_hba.conf" on host "sdw1-1" contains entries for "samenet"
    Then verify the database has mirrors
    And the information of a "mirror" segment on a remote host is saved
    When user kills a "mirror" process with the saved information
    When the user runs "gprecoverseg -a"
    Then gprecoverseg should return a return code of 0
    And all the segments are running
    And the segments are synchronized
    Given a preferred primary has failed
    When the user runs "gprecoverseg -a"
    Then gprecoverseg should return a return code of 0
    And all the segments are running
    And the segments are synchronized
    When primary and mirror switch to non-preferred roles
    When the user runs "gprecoverseg -a -r"
    Then gprecoverseg should return a return code of 0
    And all the segments are running
    And the segments are synchronized
    And the user runs "gpstop -aqM fast"

  Scenario: gpaddmirrors: gprecoverseg works correctly on a newly added mirror with HBA_HOSTNAMES=1
    Given a working directory of the test as '/tmp/gpaddmirrors'
    And the database is not running
    And with HBA_HOSTNAMES "1" a cluster is created with no mirrors on "mdw-1" and "sdw1-1, sdw1-2"
    And pg_hba file "/tmp/gpaddmirrors/data/primary/gpseg0/pg_hba.conf" on host "sdw1-1" contains entries for "mdw-1, sdw1-1"
    And gpaddmirrors adds mirrors with options "--hba-hostnames"
    And pg_hba file "/tmp/gpaddmirrors/data/primary/gpseg0/pg_hba.conf" on host "sdw1-1" contains entries for "mdw-1, sdw1-1, sdw1-2, samenet"
    Then verify the database has mirrors
    And the information of a "mirror" segment on a remote host is saved
    When user kills a "mirror" process with the saved information
    When the user runs "gprecoverseg -a"
    Then gprecoverseg should return a return code of 0
    And all the segments are running
    And the segments are synchronized
    Given a preferred primary has failed
    When the user runs "gprecoverseg -a"
    Then gprecoverseg should return a return code of 0
    And all the segments are running
    And the segments are synchronized
    When primary and mirror switch to non-preferred roles
    When the user runs "gprecoverseg -a -r"
    Then gprecoverseg should return a return code of 0
    And all the segments are running
    And the segments are synchronized
    And the user runs "gpstop -aqM fast"

  Scenario: gpmovemirrors can change from group mirroring to spread mirroring
    Given verify that mirror segments are in "group" configuration
    And pg_hba file "/data/gpdata/primary/gpseg1/pg_hba.conf" on host "sdw1-1" contains only cidr addresses
    And a sample gpmovemirrors input file is created in "spread" configuration
    When the user runs "gpmovemirrors --input=/tmp/gpmovemirrors_input_spread"
    Then gpmovemirrors should return a return code of 0
        # Verify that mirrors are functional in the new configuration
    Then verify the database has mirrors
    And all the segments are running
    And the segments are synchronized
    And verify that mirror segments are in "spread" configuration
    And verify that mirrors are recognized after a restart
    And pg_hba file "/data/gpdata/primary/gpseg1/pg_hba.conf" on host "sdw1-1" contains only cidr addresses
    And the information of a "mirror" segment on a remote host is saved
    When user kills a "mirror" process with the saved information
    And an FTS probe is triggered
    And user can start transactions
    Then the saved "mirror" segment is marked down in config
    When the user runs "gprecoverseg -a"
    Then gprecoverseg should return a return code of 0
    And all the segments are running
    And the segments are synchronized
    And the information of the corresponding primary segment on a remote host is saved
    When user kills a "primary" process with the saved information
    And an FTS probe is triggered
    And user can start transactions
    When the user runs "gprecoverseg -a"
    Then gprecoverseg should return a return code of 0
    And all the segments are running
    And the segments are synchronized
    When primary and mirror switch to non-preferred roles
    When the user runs "gprecoverseg -a -r"
    Then gprecoverseg should return a return code of 0
    And all the segments are running
    And the segments are synchronized

  Scenario: gpmovemirrors can change from spread mirroring to group mirroring
    Given verify that mirror segments are in "spread" configuration
    And a sample gpmovemirrors input file is created in "group" configuration
    When the user runs "gpmovemirrors --input=/tmp/gpmovemirrors_input_group --hba-hostnames"
    Then gpmovemirrors should return a return code of 0
        # Verify that mirrors are functional in the new configuration
    Then verify the database has mirrors
    And all the segments are running
    And the segments are synchronized
        # gpmovemirrors_input_group moves mirror on sdw3 to sdw-2, corresponding primary should now have sdw1-2 entry
    And pg_hba file "/data/gpdata/primary/gpseg1/pg_hba.conf" on host "sdw1-1" contains entries for "sdw1-2"
    And verify that mirror segments are in "group" configuration
    And verify that mirrors are recognized after a restart
    And the information of a "mirror" segment on a remote host is saved
    When user kills a "mirror" process with the saved information
    And an FTS probe is triggered
    And user can start transactions
    Then the saved "mirror" segment is marked down in config
    When the user runs "gprecoverseg -a"
    Then gprecoverseg should return a return code of 0
    And all the segments are running
    And the segments are synchronized
    And the information of the corresponding primary segment on a remote host is saved
    When user kills a "primary" process with the saved information
    And an FTS probe is triggered
    And user can start transactions
    When the user runs "gprecoverseg -a"
    Then gprecoverseg should return a return code of 0
    And all the segments are running
    And the segments are synchronized
    When primary and mirror switch to non-preferred roles
    When the user runs "gprecoverseg -a -r"
    Then gprecoverseg should return a return code of 0
    And all the segments are running
    And the segments are synchronized
