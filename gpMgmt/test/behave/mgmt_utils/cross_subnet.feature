@cross_subnet
Feature: cross subnet tests

    Scenario: gpinitsystem succeeds across subnets
        Given the database is running
          And all the segments are running
          And the segments are synchronized

    Scenario: gpmovemirrors succeeds across subnets
        Given the database is running


    Scenario: gpaddmirrors succeeds across subnets
        Given the database is running
